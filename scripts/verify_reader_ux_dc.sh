#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "== verify reader ux dc v0.4 ==" >&2
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
os.environ["DIRECT_CHAT_READER_CHUNK_MAX_CHARS"] = "600"
os.environ["DIRECT_CHAT_READER_PACING_MIN_MS"] = "1500"
os.environ["DIRECT_CHAT_READER_BURST_WINDOW_MS"] = "10000"
os.environ["DIRECT_CHAT_READER_BURST_MAX_CHUNKS"] = "6"
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
    ensure(int(r.get("reader", {}).get("next_auto_after_ms", 0) or 0) >= 1200, f"leer_libro_no_pacing_meta payload={r}")
    blocks.append(reply)
    print("PASS leer_libro_continuous_start")

    # Anti-flood: in 3 seconds there should be at most 2 chunk replies total.
    # (1 initial + max 1 additional), regardless of "seguí" spam rate.
    started_mono = time.monotonic()
    chunk_count_3s = 1
    while (time.monotonic() - started_mono) < 3.0:
        r = post_chat("seguí")
        reply = str(r.get("reply", ""))
        if "bloque" in reply.lower():
            chunk_count_3s += 1
            blocks.append(reply)
        time.sleep(0.20)
    ensure(chunk_count_3s <= 2, f"anti_flood_failed chunk_count_3s={chunk_count_3s}")
    print("PASS anti_flood_3s")

    # Keep reading with pacing-aware waits until we gather at least one extra valid chunk.
    loop_guard = 0
    while len(blocks) < 3:
        loop_guard += 1
        ensure(loop_guard <= 20, "continuous_loop_guard_exceeded")
        wait_ms = int(r.get("reader", {}).get("next_auto_after_ms", 0) or 0)
        time.sleep(max(0.15, min(2.0, wait_ms / 1000.0)))
        r = post_chat("seguí")
        reply = str(r.get("reply", ""))
        if "bloque" in reply.lower():
            ensure(len(reply.strip()) >= 80, f"auto_next_reply_too_short reply={reply}")
            blocks.append(reply)
    print("PASS continuous_paced_progress")

    # Interruption: any non-reader message should stop continuous mode.
    post_chat("hola")
    status = get_status()
    ensure(status.get("ok"), f"status_failed payload={status}")
    ensure(not bool(status.get("continuous_active", True)), f"interrupt_not_applied status={status}")
    print("PASS interruption_stops_continuous")

    # Explicit pause command should also stop continuous mode immediately.
    post_chat("pausa lectura")
    status = get_status()
    ensure(status.get("ok"), f"status_after_pause_failed payload={status}")
    ensure(not bool(status.get("continuous_active", True)), f"pause_not_applied status={status}")
    print("PASS pausa_lectura_stops_continuous")

    # Manual mode after pause: two explicit "seguí" should advance one block each
    # and must not reactivate continuous auto mode.
    manual_1 = post_chat("seguí")
    reply_1 = str(manual_1.get("reply", ""))
    ensure("bloque" in reply_1.lower() or "fin de lectura" in reply_1.lower(), f"manual_seg1_bad_reply={manual_1}")
    ensure(not bool(manual_1.get("reader", {}).get("auto_continue", False)), f"manual_seg1_reactivated_auto payload={manual_1}")
    manual_2 = post_chat("seguí")
    reply_2 = str(manual_2.get("reply", ""))
    ensure("bloque" in reply_2.lower() or "fin de lectura" in reply_2.lower(), f"manual_seg2_bad_reply={manual_2}")
    ensure(not bool(manual_2.get("reader", {}).get("auto_continue", False)), f"manual_seg2_reactivated_auto payload={manual_2}")
    print("PASS manual_segui_two_steps")

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
