#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "== verify reader ux dc v0.6 ==" >&2
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


def reader_get(path: str) -> dict:
    req = Request(base + path, method="GET")
    with urlopen(req, timeout=8) as resp:
        body = json.loads(resp.read().decode("utf-8") or "{}")
        return body if isinstance(body, dict) else {}


def reader_post(path: str, payload: dict) -> dict:
    req = Request(
        base + path,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=8) as resp:
        body = json.loads(resp.read().decode("utf-8") or "{}")
        return body if isinstance(body, dict) else {}


try:
    r = post_chat("biblioteca rescan")
    ensure("biblioteca" in str(r.get("reply", "")).lower(), f"rescan_failed reply={r}")
    print("PASS biblioteca_rescan")

    r = post_chat("biblioteca")
    ensure("1)" in str(r.get("reply", "")) or "biblioteca" in str(r.get("reply", "")).lower(), f"biblioteca_failed reply={r}")
    print("PASS biblioteca_list")

    # Manual default start + visible content in the same reply.
    blocks = []
    r = post_chat("leer libro 1")
    reply = str(r.get("reply", ""))
    ensure("bloque" in reply.lower(), f"leer_libro_no_block reply={reply}")
    ensure("PARTE" in reply, f"leer_libro_no_text reply={reply[:220]}")
    ensure(not bool(r.get("reader", {}).get("auto_continue", True)), f"leer_libro_should_be_manual payload={r}")
    ensure(not bool(r.get("reader", {}).get("continuous_enabled", True)), f"leer_libro_continuous_enabled payload={r}")
    blocks.append(reply)
    print("PASS leer_libro_manual_start")

    # No auto-run in manual mode: cursor must remain unchanged without commands.
    status_before_wait = get_status()
    time.sleep(3.0)
    status_after_wait = get_status()
    ensure(
        int(status_after_wait.get("cursor", -1)) == int(status_before_wait.get("cursor", -2)),
        f"manual_autorun_detected before={status_before_wait} after={status_after_wait}",
    )
    print("PASS manual_no_auto_run")

    # Manual mode: two explicit "seguí" should advance one block each and stay manual.
    cursor0 = int(status_after_wait.get("cursor", 0) or 0)
    manual_1 = post_chat("seguí")
    reply_1 = str(manual_1.get("reply", ""))
    ensure("bloque" in reply_1.lower() or "fin de lectura" in reply_1.lower(), f"manual_seg1_bad_reply={manual_1}")
    ensure(not bool(manual_1.get("reader", {}).get("auto_continue", True)), f"manual_seg1_auto_continue payload={manual_1}")
    st1 = get_status()
    ensure(int(st1.get("cursor", 0) or 0) == (cursor0 + 1), f"manual_seg1_bad_cursor status={st1} cursor0={cursor0}")
    manual_2 = post_chat("seguí")
    reply_2 = str(manual_2.get("reply", ""))
    ensure("bloque" in reply_2.lower() or "fin de lectura" in reply_2.lower(), f"manual_seg2_bad_reply={manual_2}")
    ensure(not bool(manual_2.get("reader", {}).get("auto_continue", True)), f"manual_seg2_auto_continue payload={manual_2}")
    st2 = get_status()
    ensure(int(st2.get("cursor", 0) or 0) == (cursor0 + 2), f"manual_seg2_bad_cursor status={st2} cursor0={cursor0}")
    print("PASS manual_segui_two_steps")

    # Continuous opt-in.
    cont_on = post_chat("continuo on")
    ensure("continua" in str(cont_on.get("reply", "")).lower(), f"continuo_on_bad_reply={cont_on}")
    st_cont_on = get_status()
    ensure(bool(st_cont_on.get("continuous_enabled", False)), f"continuo_on_not_enabled status={st_cont_on}")
    step_cont = post_chat("seguí")
    ensure(
        bool(step_cont.get("reader", {}).get("continuous_enabled", False)),
        f"continuous_step_missing_enabled payload={step_cont}",
    )
    print("PASS continuous_opt_in")

    # Interruption: any non-reader message should stop continuous mode.
    post_chat("hola")
    status = get_status()
    ensure(status.get("ok"), f"status_failed payload={status}")
    ensure(not bool(status.get("continuous_enabled", True)), f"interrupt_not_applied status={status}")
    print("PASS interruption_stops_continuous")

    # Explicit pause command should also stop continuous mode immediately.
    post_chat("pausa lectura")
    status = get_status()
    ensure(status.get("ok"), f"status_after_pause_failed payload={status}")
    ensure(not bool(status.get("continuous_enabled", True)), f"pause_not_applied status={status}")
    print("PASS pausa_lectura_stops_continuous")

    # v0.6: barge-in bookmark + continue/seek/rewind commands.
    reader_post(
        "/api/reader/session/start",
        {
            "session_id": session_id,
            "chunks": ["Inicio académico. Punto matriz para retomar. Cierre del ejemplo."],
            "reset": True,
        },
    )
    reader_get(f"/api/reader/session/next?session_id={session_id}")
    barge = reader_post(
        "/api/reader/session/barge_in",
        {"session_id": session_id, "detail": "verify_mid_block_cut", "playback_ms": 650},
    )
    ensure(bool(barge.get("interrupted", False)), f"barge_in_not_interrupted payload={barge}")
    bookmark = barge.get("bookmark", {}) if isinstance(barge.get("bookmark"), dict) else {}
    ensure(int(bookmark.get("offset_chars", -1)) >= 0, f"bookmark_missing_offset payload={barge}")
    ensure(str(barge.get("reader_state", "")) in ("commenting", "paused"), f"barge_in_state_bad payload={barge}")
    print("PASS barge_in_bookmark")

    post_chat("comentario académico breve")
    resumed = post_chat("continuar")
    resumed_reply = str(resumed.get("reply", ""))
    ensure("bloque" in resumed_reply.lower(), f"continuar_no_block payload={resumed}")
    print("PASS continuar_from_bookmark")

    resumed_from = post_chat('continuar desde "matriz"')
    resumed_from_reply = str(resumed_from.get("reply", "")).lower()
    ensure(("matriz" in resumed_from_reply) or ("bloque" in resumed_from_reply), f"continuar_desde_bad payload={resumed_from}")
    print("PASS continuar_desde_phrase")

    rewind = post_chat("volver una frase")
    rewind_reply = str(rewind.get("reply", ""))
    ensure("bloque" in rewind_reply.lower(), f"volver_una_frase_bad payload={rewind}")
    print("PASS volver_una_frase")

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
