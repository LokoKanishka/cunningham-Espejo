from __future__ import annotations

import json
import os
import subprocess
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(APP_DIR / "templates"))

IPC_ROOT = Path(os.environ.get("IPC_ROOT", "/data/lucy_ipc"))
REPO_ROOT = Path(os.environ.get("REPO_ROOT", "/repo"))
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://host.docker.internal:5678/webhook/lucy-input")
MAX_BROWSE = int(os.environ.get("LUCY_PANEL_MAX_BROWSE", "50"))

ACK_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
ACK_CACHE_MAX = 200

ALLOWED_SMOKES = {
    "webhook_smoke": ["./scripts/webhook_smoke.sh"],
    "gateway_e2e": ["./scripts/n8n_gateway_e2e.sh"],
    "both": ["./scripts/webhook_smoke.sh", "./scripts/n8n_gateway_e2e.sh"],
}

app = FastAPI(title="Lucy UI Panel")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json_safe(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        return {"_error": f"read_failed: {exc}", "_path": str(path)}

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {"_error": "not_an_object", "_path": str(path), "_raw": raw}
    except Exception as exc:
        return {"_error": f"invalid_json: {exc}", "_path": str(path), "_raw": raw}


def find_cid_file(box: str, cid: str) -> Path | None:
    base = IPC_ROOT / box
    if not base.exists():
        return None

    candidates = [base / f"{cid}.json"]
    if box == "outbox":
        candidates.append(base / f"res_{cid}.json")
    if box == "inbox":
        candidates.append(IPC_ROOT / "payloads" / f"{cid}.json")

    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def list_box(box: str, limit: int = MAX_BROWSE) -> list[dict[str, Any]]:
    base = IPC_ROOT / box
    if not base.exists():
        return []

    files = sorted(
        [p for p in base.iterdir() if p.is_file() and not p.name.startswith(".")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]

    rows: list[dict[str, Any]] = []
    for p in files:
        cid = p.stem
        if p.name.startswith("res_"):
            cid = p.stem.removeprefix("res_")
        rows.append({
            "name": p.name,
            "cid": cid,
            "size": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        })
    return rows


def cache_ack(ack: dict[str, Any]) -> None:
    cid = str(ack.get("correlation_id") or "")
    if not cid:
        return
    ACK_CACHE[cid] = ack
    ACK_CACHE.move_to_end(cid)
    while len(ACK_CACHE) > ACK_CACHE_MAX:
        ACK_CACHE.popitem(last=False)


def run_allowed_smoke(which: str, timeout_s: int = 120) -> dict[str, Any]:
    cmds = ALLOWED_SMOKES.get(which)
    if cmds is None:
        return {
            "ok": False,
            "which": which,
            "error": "not_allowed",
            "allowed": sorted(ALLOWED_SMOKES.keys()),
        }

    outputs: list[dict[str, Any]] = []
    for cmd in cmds:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        merged = (proc.stdout or "") + (proc.stderr or "")
        lines = merged.splitlines()
        outputs.append(
            {
                "cmd": cmd,
                "returncode": proc.returncode,
                "tail": "\n".join(lines[-80:]),
            }
        )

    ok = all(item["returncode"] == 0 for item in outputs)
    return {
        "ok": ok,
        "which": which,
        "outputs": outputs,
        "ts": now_iso(),
    }


@app.get("/")
def home(request: Request):
    return TEMPLATES.TemplateResponse(
        "home.html",
        {
            "request": request,
            "gateway_url": GATEWAY_URL,
            "inbox": list_box("inbox", 10),
            "outbox": list_box("outbox", 10),
            "deadletter": list_box("deadletter", 10),
        },
    )


@app.post("/send")
def send(
    request: Request,
    text: str = Form(...),
    kind: str = Form("text"),
    source: str = Form("ui_panel"),
):
    payload = {
        "kind": kind,
        "source": source,
        "ts": now_iso(),
        "text": text,
        "meta": {"via": "lucy_panel"},
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(GATEWAY_URL, json=payload)
        body = res.json()
    except Exception as exc:
        return TEMPLATES.TemplateResponse(
            "home.html",
            {
                "request": request,
                "gateway_url": GATEWAY_URL,
                "error": f"send_failed: {exc}",
                "inbox": list_box("inbox", 10),
                "outbox": list_box("outbox", 10),
                "deadletter": list_box("deadletter", 10),
            },
            status_code=502,
        )

    if isinstance(body, dict):
        body["_http_status"] = res.status_code
        cache_ack(body)
        cid = str(body.get("correlation_id") or "")
        if cid:
            return RedirectResponse(url=f"/cid/{cid}", status_code=303)

    return TEMPLATES.TemplateResponse(
        "home.html",
        {
            "request": request,
            "gateway_url": GATEWAY_URL,
            "error": f"invalid_ack_http_{res.status_code}",
            "ack": body,
            "inbox": list_box("inbox", 10),
            "outbox": list_box("outbox", 10),
            "deadletter": list_box("deadletter", 10),
        },
        status_code=502,
    )


@app.post("/cid_lookup")
def cid_lookup(cid: str = Form(...)):
    cid = cid.strip()
    return RedirectResponse(url=f"/cid/{cid}", status_code=303)


@app.get("/cid/{cid}")
def cid_detail(request: Request, cid: str):
    inbox_file = find_cid_file("inbox", cid)
    outbox_file = find_cid_file("outbox", cid)
    deadletter_file = find_cid_file("deadletter", cid)

    inbox_data = load_json_safe(inbox_file) if inbox_file else None
    outbox_data = load_json_safe(outbox_file) if outbox_file else None
    deadletter_data = load_json_safe(deadletter_file) if deadletter_file else None

    return TEMPLATES.TemplateResponse(
        "cid_detail.html",
        {
            "request": request,
            "cid": cid,
            "ack": ACK_CACHE.get(cid),
            "inbox_file": str(inbox_file) if inbox_file else None,
            "outbox_file": str(outbox_file) if outbox_file else None,
            "deadletter_file": str(deadletter_file) if deadletter_file else None,
            "inbox": inbox_data,
            "outbox": outbox_data,
            "deadletter": deadletter_data,
            "status": "pending" if outbox_data is None and deadletter_data is None else "done",
        },
    )


@app.get("/browse/{box}")
def browse_box(request: Request, box: str):
    if box not in {"inbox", "outbox", "deadletter", "payloads"}:
        return TEMPLATES.TemplateResponse(
            "browse.html",
            {
                "request": request,
                "box": box,
                "rows": [],
                "error": "invalid_box",
            },
            status_code=404,
        )

    rows = list_box(box, MAX_BROWSE)
    return TEMPLATES.TemplateResponse(
        "browse.html",
        {
            "request": request,
            "box": box,
            "rows": rows,
            "error": None,
        },
    )


@app.post("/ops/smoke")
def ops_smoke(request: Request, which: str = Form("both")):
    result = run_allowed_smoke(which)
    return TEMPLATES.TemplateResponse(
        "ops_result.html",
        {
            "request": request,
            "result": result,
        },
        status_code=200 if result.get("ok") else 500,
    )
