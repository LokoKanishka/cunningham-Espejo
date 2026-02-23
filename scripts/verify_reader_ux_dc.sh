#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "== verify reader ux dc v0 ==" >&2
echo "tmp_dir=${TMP_DIR}" >&2

python3 - "${TMP_DIR}" <<'PY'
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen


tmp_dir = Path(sys.argv[1])
repo_root = Path.cwd()
sys.path.insert(0, str(repo_root / "scripts"))

import openclaw_direct_chat as direct_chat  # noqa: E402

os.environ["DIRECT_CHAT_TTS_DRY_RUN"] = "1"
# Avoid STT/audio side effects in verifier; this test targets reader UX commands.
direct_chat._sync_stt_with_voice = lambda enabled, session_id="": None  # type: ignore

library_dir = tmp_dir / "Lucy_Library"
library_dir.mkdir(parents=True, exist_ok=True)
(library_dir / "lectura_dc.txt").write_text(
    "Bloque uno para flujo UX.\n\nBloque dos para autocommit por TTS.",
    encoding="utf-8",
)

state_path = tmp_dir / "reading_sessions.json"
lock_path = tmp_dir / ".reading_sessions.lock"
index_path = tmp_dir / "reader_library_index.json"
index_lock = tmp_dir / ".reader_library_index.lock"
cache_dir = tmp_dir / "reader_cache"

direct_chat._READER_STORE = direct_chat.ReaderSessionStore(state_path=state_path, lock_path=lock_path)
direct_chat._READER_LIBRARY = direct_chat.ReaderLibraryIndex(
    library_dir=library_dir,
    index_path=index_path,
    lock_path=index_lock,
    cache_dir=cache_dir,
)

def ensure(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def parse_sse_text(raw: str) -> str:
    out = []
    for part in raw.split("\n\n"):
        lines = [ln for ln in part.split("\n") if ln.startswith("data: ")]
        if not lines:
            continue
        data = lines[0][6:]
        if data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except Exception:
            continue
        tok = str(payload.get("token", ""))
        if tok:
            out.append(tok)
    return "".join(out).strip()


httpd = direct_chat.ThreadingHTTPServer(("127.0.0.1", 0), direct_chat.Handler)
httpd.gateway_token = "verify-token"
httpd.gateway_port = 18789
th = threading.Thread(target=httpd.serve_forever, daemon=True)
th.start()
time.sleep(0.05)
base = f"http://127.0.0.1:{httpd.server_address[1]}"
session_id = "verify_ux_dc"


def chat_stream(message: str) -> str:
    payload = {
        "message": message,
        "session_id": session_id,
        "allowed_tools": ["tts"],
        "history": [],
    }
    req = Request(
        base + "/api/chat/stream",
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=8) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return parse_sse_text(body)


def get_status() -> dict:
    req = Request(base + f"/api/reader/session?session_id={session_id}", method="GET")
    with urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8") or "{}")
        return body if isinstance(body, dict) else {}


try:
    r = chat_stream("voz on")
    ensure("active" in r.lower() or "activ" in r.lower() or "listo" in r.lower(), f"voz_on_failed reply={r}")
    print("PASS voz_on")

    r = chat_stream("biblioteca rescan")
    ensure("biblioteca" in r.lower() or "libros" in r.lower(), f"rescan_failed reply={r}")
    print("PASS biblioteca_rescan")

    r = chat_stream("biblioteca")
    ensure("1)" in r or "biblioteca" in r.lower(), f"biblioteca_failed reply={r}")
    print("PASS biblioteca_list")

    r = chat_stream("leer libro 1")
    ensure("abrí" in r.lower() or "abri" in r.lower() or "listo" in r.lower(), f"leer_libro_failed reply={r}")
    print("PASS leer_libro_1")

    r = chat_stream("seguí")
    ensure("leyendo" in r.lower() or "bloque" in r.lower(), f"segui_failed reply={r}")

    status = {}
    for _ in range(80):
        status = get_status()
        if int(status.get("cursor", 0)) >= 1 and status.get("pending") is None:
            break
        time.sleep(0.05)
    ensure(int(status.get("cursor", 0)) >= 1, f"cursor_not_advanced status={status}")
    ensure(status.get("pending") is None, f"pending_not_cleared status={status}")
    print("PASS segui_autocommit")

    r = chat_stream("estado lectura")
    ensure("estado lectura" in r.lower() or "cursor=" in r.lower(), f"estado_failed reply={r}")
    print("PASS estado_lectura")

    print("READER_UX_DC_OK")
finally:
    try:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=1.0)
    except Exception:
        pass
PY
