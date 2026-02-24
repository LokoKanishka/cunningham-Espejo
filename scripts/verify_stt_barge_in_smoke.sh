#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "== verify stt barge-in smoke ==" >&2

python3 - <<'PY'
import json
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str((__import__("pathlib").Path.cwd() / "scripts")))
import openclaw_direct_chat as direct_chat  # noqa: E402


class _DummyWorker:
    def __init__(self) -> None:
        self.last_error = ""

    def start(self) -> None:
        return

    def stop(self, timeout: float = 0.0) -> None:
        return

    def is_running(self) -> bool:
        return True


def request(base: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(base + path, method=method, data=data, headers=headers)
    try:
        with urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
            body = json.loads(raw or "{}")
            return int(resp.getcode()), body if isinstance(body, dict) else {}
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw or "{}")
        except Exception:
            body = {}
        return int(e.code), body if isinstance(body, dict) else {}


def ensure(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


session_id = "verify_stt_barge"
httpd = direct_chat.ThreadingHTTPServer(("127.0.0.1", 0), direct_chat.Handler)
httpd.gateway_token = "verify-token"
httpd.gateway_port = 18789
th = threading.Thread(target=httpd.serve_forever, daemon=True)
th.start()
time.sleep(0.05)
base = f"http://127.0.0.1:{httpd.server_address[1]}"

mgr = direct_chat._STT_MANAGER
with mgr._lock:
    mgr._enabled = True
    mgr._owner_session_id = session_id
    mgr._worker = _DummyWorker()
    mgr._clear_queue_locked()

try:
    code, started = request(
        base,
        "POST",
        "/api/reader/session/start",
        {
            "session_id": session_id,
            "chunks": ["Bloque uno.", "Bloque dos."],
            "reset": True,
        },
    )
    ensure(code == 200 and bool(started.get("ok")), f"start_failed code={code} body={started}")
    direct_chat._READER_STORE.set_continuous(session_id, True, reason="verify_stt")
    request(base, "GET", f"/api/reader/session/next?session_id={session_id}")
    print("PASS setup")

    code, inj_pause = request(base, "POST", "/api/stt/inject", {"session_id": session_id, "cmd": "pause"})
    ensure(code == 200 and bool(inj_pause.get("ok")), f"inject_pause_failed code={code} body={inj_pause}")
    code, polled = request(base, "GET", f"/api/stt/poll?session_id={session_id}&limit=2")
    ensure(code == 200 and bool(polled.get("ok")), f"poll_pause_failed code={code} body={polled}")
    items = polled.get("items", [])
    ensure(isinstance(items, list) and items, f"pause_poll_empty body={polled}")
    first = items[0] if isinstance(items[0], dict) else {}
    ensure(str(first.get("cmd", "")) == "pause", f"pause_cmd_missing item={first}")
    print("PASS inject_pause_poll")

    code, paused = request(
        base,
        "POST",
        "/api/chat",
        {
            "session_id": session_id,
            "message": "pausa lectura",
            "allowed_tools": ["tts"],
            "history": [],
        },
    )
    ensure(code == 200, f"pause_chat_failed code={code} body={paused}")
    code, status = request(base, "GET", f"/api/reader/session?session_id={session_id}")
    ensure(code == 200 and not bool(status.get("continuous_enabled", True)), f"pause_not_applied status={status}")
    print("PASS pause_applied")

    code, inj_continue = request(base, "POST", "/api/stt/inject", {"session_id": session_id, "cmd": "continue"})
    ensure(code == 200 and bool(inj_continue.get("ok")), f"inject_continue_failed code={code} body={inj_continue}")
    code, polled_cont = request(base, "GET", f"/api/stt/poll?session_id={session_id}&limit=2")
    ensure(code == 200 and bool(polled_cont.get("ok")), f"poll_continue_failed code={code} body={polled_cont}")
    items2 = polled_cont.get("items", [])
    ensure(isinstance(items2, list) and items2, f"continue_poll_empty body={polled_cont}")
    first2 = items2[0] if isinstance(items2[0], dict) else {}
    ensure(str(first2.get("cmd", "")) == "continue", f"continue_cmd_missing item={first2}")
    print("PASS inject_continue_poll")

    code, resumed = request(
        base,
        "POST",
        "/api/chat",
        {
            "session_id": session_id,
            "message": "continuar",
            "allowed_tools": ["tts"],
            "history": [],
        },
    )
    ensure(code == 200, f"continue_chat_failed code={code} body={resumed}")
    rmeta = resumed.get("reader", {}) if isinstance(resumed, dict) else {}
    ensure(bool(rmeta.get("continuous_enabled", False)) or bool(rmeta.get("done", False)), f"resume_not_continuous body={resumed}")
    print("PASS continue_applied")
    print("STT_BARGE_IN_SMOKE_OK")
finally:
    try:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=1.0)
    except Exception:
        pass
    with mgr._lock:
        mgr._enabled = False
        mgr._owner_session_id = ""
        mgr._worker = None
        mgr._clear_queue_locked()
PY
