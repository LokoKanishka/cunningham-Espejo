#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import time
from typing import Any, Tuple

IPC_DIR = os.environ.get(
    "X11_FILE_IPC_DIR", "/home/lucy-ubuntu/Lucy_Workspace/infra/ipc"
)

IPC = pathlib.Path(IPC_DIR)
INBOX = IPC / "inbox"
OUTBOX = IPC / "outbox"
PROCESSED = IPC / "payloads"

for d in (INBOX, OUTBOX, PROCESSED):
    d.mkdir(parents=True, exist_ok=True)

LOG = IPC / "agent.log"

DEFAULT_TIMEOUT = float(os.environ.get("X11_FILE_AGENT_TIMEOUT", "6"))
LEGACY_OUTBOX = os.environ.get("X11_FILE_AGENT_LEGACY_OUTBOX", "true").lower() == "true"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def log(msg: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(msg.rstrip() + "\n")
    except Exception:
        pass


def run_cmd(cmd: str, timeout_s: float) -> Tuple[int, str, str]:
    env = os.environ.copy()
    env.pop("X11_FILE_IPC_DIR", None)
    env["X11_FORCE_LOCAL"] = "1"
    wrap_dir = (pathlib.Path(__file__).resolve().parent / "x11_wrap").resolve()
    path_val = env.get("PATH", "")
    if path_val:
        parts = [p for p in path_val.split(":") if p]
        parts = [p for p in parts if os.path.realpath(p) != str(wrap_dir)]
        env["PATH"] = ":".join(parts)

    proc = subprocess.Popen(
        ["bash", "-lc", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        preexec_fn=os.setsid,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        rc = proc.returncode if proc.returncode is not None else 0
        return rc, stdout or "", stderr or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        time.sleep(0.15)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass
        return 124, "", "Timed out."


def parse_legacy_payload(text: str) -> Tuple[str, str]:
    line = text.strip().splitlines()[0] if text.strip() else ""
    if ":" in line:
        kind, rest = line.split(":", 1)
        return kind.strip().upper(), rest.strip()
    if line:
        return "EXEC", line.strip()
    return "NOOP", ""


def parse_request(path: pathlib.Path, content: str) -> Tuple[str, str, str, dict[str, Any]]:
    correlation_id = path.stem

    try:
        raw = json.loads(content)
    except Exception:
        kind, command = parse_legacy_payload(content)
        return correlation_id, kind, command, {}

    if not isinstance(raw, dict):
        return correlation_id, "NOOP", "", {}

    correlation_id = str(raw.get("correlation_id") or correlation_id)
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    command = ""
    if isinstance(meta.get("command"), str) and meta.get("command").strip():
        command = meta.get("command", "").strip()
    elif isinstance(payload.get("text"), str) and payload.get("text").strip():
        command = payload.get("text", "").strip()

    kind = str(payload.get("kind") or "EXEC").upper()
    if kind in {"TEXT", "VOICE"}:
        kind = "EXEC"
    return correlation_id, kind, command, payload


def build_outbox(
    correlation_id: str,
    ok: bool,
    status: str,
    rc: int,
    stdout: str,
    stderr: str,
    stage: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": "lucy_output_v1",
        "ok": ok,
        "correlation_id": correlation_id,
        "status": status,
        "response_ts": now_iso(),
    }

    if ok:
        base["result"] = {
            "rc": rc,
            "stdout": stdout,
            "stderr": stderr,
        }
    else:
        message = stderr.strip() or stdout.strip() or f"Command failed with rc={rc}"
        base["error"] = {
            "rc": rc,
            "message": message,
            "stderr": stderr,
            "stdout": stdout,
            "stage": stage,
        }

    return base


def handle_request(path: pathlib.Path) -> None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = ""

    cid, kind, command, _payload = parse_request(path, content)
    timeout_s = DEFAULT_TIMEOUT
    stage = "dispatch"

    if kind == "NOTIFY":
        msg = command or "Lucy notification"
        cmd = f"notify-send {shlex.quote('Lucy')} {shlex.quote(msg)}"
        rc, stdout, stderr = run_cmd(cmd, timeout_s)
        stage = "notify"
    elif kind == "EXEC":
        if not command:
            rc, stdout, stderr = 2, "", "Missing EXEC command."
            stage = "parse"
        else:
            rc, stdout, stderr = run_cmd(command, timeout_s)
            stage = "exec"
    elif kind == "NOOP":
        rc, stdout, stderr = 0, "NOOP\n", ""
        stage = "noop"
    else:
        rc, stdout, stderr = 2, "", f"UNKNOWN_COMMAND: {kind}"
        stage = "parse"

    ok = rc == 0
    status = "ok" if ok else "error"
    outbox = build_outbox(
        correlation_id=cid,
        ok=ok,
        status=status,
        rc=rc,
        stdout=stdout,
        stderr=stderr,
        stage=stage,
    )

    out_path = OUTBOX / f"{cid}.json"
    try:
        out_path.write_text(json.dumps(outbox, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        log(f"x11_file_agent: outbox write failed cid={cid} err={exc}")

    if LEGACY_OUTBOX:
        legacy = f"RC={rc}\n"
        if stdout:
            legacy += stdout if stdout.endswith("\n") else stdout + "\n"
        if stderr:
            legacy += stderr if stderr.endswith("\n") else stderr + "\n"
        try:
            (OUTBOX / f"res_{cid}.json").write_text(legacy, encoding="utf-8", errors="replace")
        except Exception:
            pass

    try:
        path.rename(PROCESSED / path.name)
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass


def main() -> None:
    log(f"x11_file_agent: ipc={IPC}")
    log(f"x11_file_agent: inbox={INBOX}")
    log(f"x11_file_agent: outbox={OUTBOX}")

    while True:
        try:
            reqs = sorted(INBOX.iterdir(), key=lambda p: p.stat().st_mtime)
        except Exception:
            reqs = []

        if not reqs:
            time.sleep(0.1)
            continue

        for req in reqs:
            if not req.is_file():
                continue
            if req.name.startswith(".") or req.name.endswith(".tmp"):
                continue
            handle_request(req)


if __name__ == "__main__":
    if not IPC_DIR:
        print("x11_file_agent: ERROR: IPC dir not set", file=sys.stderr)
        sys.exit(2)
    main()
