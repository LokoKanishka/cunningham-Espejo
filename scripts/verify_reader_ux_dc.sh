#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "== verify reader ux dc v0.3 ==" >&2
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
os.environ["DIRECT_CHAT_READER_CHUNK_MAX_CHARS"] = "420"
# Keep verifier deterministic and local-only.
direct_chat._sync_stt_with_voice = lambda enabled, session_id="": None  # type: ignore
direct_chat.Handler._call_model_backend = (  # type: ignore
    lambda self, backend, payload: {
        "id": "verify-local-model",
        "choices": [{"message": {"role": "assistant", "content": "MODELO_OK"}}],
    }
)

library_dir = tmp_dir / "Lucy_Library"
library_dir.mkdir(parents=True, exist_ok=True)
text = "\n\n".join(
    [
        "PARTE UNO. " + "Frase de lectura fluida. " * 28,
        "PARTE DOS. " + "Contenido largo para segundo bloque. " * 26,
        "PARTE TRES. " + "Contenido largo para tercer bloque. " * 27,
        "PARTE CUATRO. " + "Contenido largo para cuarto bloque. " * 25,
    ]
)
(library_dir / "lectura_dc.txt").write_text(text, encoding="utf-8")

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


httpd = direct_chat.ThreadingHTTPServer(("127.0.0.1", 0), direct_chat.Handler)
httpd.gateway_token = "verify-token"
httpd.gateway_port = 18789
th = threading.Thread(target=httpd.serve_forever, daemon=True)
th.start()
time.sleep(0.05)
base = f"http://127.0.0.1:{httpd.server_address[1]}"
session_id = "verify_ux_dc"


def post_chat(message: str, allowed_tools=None) -> dict:
    payload = {
        "message": message,
        "session_id": session_id,
        "allowed_tools": allowed_tools or [],
        "history": [],
        "mode": "operativo",
        "attachments": [],
    }
    req = Request(
        base + "/api/chat",
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8") or "{}")
        return body if isinstance(body, dict) else {}


def get_status() -> dict:
    req = Request(base + f"/api/reader/session?session_id={session_id}", method="GET")
    with urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8") or "{}")
        return body if isinstance(body, dict) else {}


try:
    r = post_chat("biblioteca rescan")
    ensure("biblioteca" in str(r.get("reply", "")).lower(), f"rescan_failed reply={r}")
    print("PASS biblioteca_rescan")

    r = post_chat("biblioteca")
    ensure("1)" in str(r.get("reply", "")) or "biblioteca" in str(r.get("reply", "")).lower(), f"biblioteca_failed reply={r}")
    print("PASS biblioteca_list")

    # Continuous start + visible content in the same reply.
    blocks = []
    r = post_chat("leer libro 1")
    reply = str(r.get("reply", ""))
    ensure("bloque" in reply.lower(), f"leer_libro_no_block reply={reply}")
    ensure("PARTE" in reply, f"leer_libro_no_text reply={reply[:220]}")
    ensure(bool(r.get("reader", {}).get("auto_continue", False)), f"leer_libro_not_continuous payload={r}")
    blocks.append(reply)
    print("PASS leer_libro_continuous_start")

    # Simulate UI auto-loop deterministically via reader auto_continue metadata.
    loop_guard = 0
    while bool(r.get("reader", {}).get("auto_continue", False)) and len(blocks) < 3:
        loop_guard += 1
        ensure(loop_guard <= 10, "continuous_loop_guard_exceeded")
        r = post_chat("seguí")
        reply = str(r.get("reply", ""))
        ensure("bloque" in reply.lower(), f"auto_next_no_block reply={reply}")
        ensure(len(reply.strip()) >= 80, f"auto_next_reply_too_short reply={reply}")
        blocks.append(reply)

    ensure(len(blocks) >= 3, f"continuous_less_than_3_blocks blocks={len(blocks)}")
    print("PASS continuous_multi_block")

    # Interruption: any non-reader message should stop continuous mode.
    post_chat("hola")
    status = get_status()
    ensure(status.get("ok"), f"status_failed payload={status}")
    ensure(not bool(status.get("continuous_active", True)), f"interrupt_not_applied status={status}")
    print("PASS interruption_stops_continuous")

    # Estado should show progress and continuous mode state.
    r = post_chat("estado lectura")
    estado = str(r.get("reply", ""))
    ensure("cursor=" in estado and "continua=" in estado.lower(), f"estado_missing_fields reply={estado}")
    print("PASS estado_reflects_progress")

    print("READER_UX_DC_OK")
finally:
    try:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=1.0)
    except Exception:
        pass
PY
