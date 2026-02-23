#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "== verify reader mode v0.1 ==" >&2
echo "tmp_dir=${TMP_DIR}" >&2

python3 - "${TMP_DIR}" <<'PY'
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


tmp_dir = Path(sys.argv[1])
repo_root = Path.cwd()
sys.path.insert(0, str(repo_root / "scripts"))

import openclaw_direct_chat as direct_chat  # noqa: E402

os.environ["DIRECT_CHAT_TTS_DRY_RUN"] = "1"

state_path = tmp_dir / "reading_sessions.json"
lock_path = tmp_dir / ".reading_sessions.lock"
direct_chat._READER_STORE = direct_chat.ReaderSessionStore(
    state_path=state_path,
    lock_path=lock_path,
)

httpd = direct_chat.ThreadingHTTPServer(("127.0.0.1", 0), direct_chat.Handler)
httpd.gateway_token = "verify-token"
httpd.gateway_port = 18789
th = threading.Thread(target=httpd.serve_forever, daemon=True)
th.start()
time.sleep(0.05)
base = f"http://127.0.0.1:{httpd.server_address[1]}"


def request(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    headers = {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(base + path, method=method, data=data, headers=headers)
    try:
        with urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw or "{}")
            if not isinstance(parsed, dict):
                parsed = {}
            return int(resp.getcode()), parsed
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw or "{}")
        except Exception:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        return int(e.code), parsed


def ensure(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


try:
    code, started = request(
        "POST",
        "/api/reader/session/start",
        {
            "session_id": "verify_rm_v01",
            "chunks": [
                "Primer bloque autocommit.",
                "Segundo bloque para interrupcion y replay.",
                "Tercer bloque final.",
            ],
            "reset": True,
        },
    )
    ensure(code == 200 and bool(started.get("ok")), f"start_failed code={code} body={started}")
    print("PASS start_session")

    code, first = request("GET", "/api/reader/session/next?session_id=verify_rm_v01&speak=1&autocommit=1")
    ensure(code == 200 and bool(first.get("ok")), f"next_1_failed code={code} body={first}")
    ensure(bool(first.get("speak_started")), f"next_1_speak_not_started body={first}")
    ensure(bool(first.get("autocommit_registered")), f"next_1_autocommit_not_registered body={first}")
    print("PASS next_chunk_1_with_autocommit")

    status = {}
    for _ in range(80):
        code, status = request("GET", "/api/reader/session?session_id=verify_rm_v01")
        ensure(code == 200, f"status_poll_failed code={code} body={status}")
        if int(status.get("cursor", -1)) == 1 and status.get("pending") is None:
            break
        time.sleep(0.05)
    ensure(int(status.get("cursor", -1)) == 1, f"autocommit_did_not_advance body={status}")
    ensure(status.get("pending") is None, f"autocommit_did_not_clear_pending body={status}")
    print("PASS tts_end_autocommit")

    code, second = request("GET", "/api/reader/session/next?session_id=verify_rm_v01&speak=1&autocommit=1")
    ensure(code == 200 and bool(second.get("ok")), f"next_2_failed code={code} body={second}")
    chunk2 = second.get("chunk", {}) if isinstance(second, dict) else {}
    chunk2_id = str(chunk2.get("chunk_id", ""))
    stream_id = int(second.get("tts_stream_id", 0) or 0)
    ensure(bool(chunk2_id), f"next_2_missing_chunk_id body={second}")
    ensure(stream_id > 0, f"next_2_missing_stream_id body={second}")

    # Simular interrupcion: estado final de voz en false antes de completar TTS.
    direct_chat._set_voice_status(stream_id, False, "playback_interrupted")
    code, interrupted = request(
        "POST",
        "/api/reader/session/barge_in",
        {"session_id": "verify_rm_v01", "detail": "vad+rms threshold hit"},
    )
    ensure(code == 200 and bool(interrupted.get("interrupted")), f"barge_in_failed code={code} body={interrupted}")
    ensure(int(interrupted.get("cursor", -1)) == 1, f"barge_in_bad_cursor body={interrupted}")
    print("PASS interrupted_does_not_commit")

    direct_chat._READER_STORE = direct_chat.ReaderSessionStore(state_path=state_path, lock_path=lock_path)
    code, replay = request("GET", "/api/reader/session/next?session_id=verify_rm_v01")
    ensure(code == 200 and bool(replay.get("ok")), f"next_after_restart_failed code={code} body={replay}")
    ensure(bool(replay.get("replayed")), f"next_after_restart_should_replay body={replay}")
    ensure(str(replay.get("chunk", {}).get("chunk_id", "")) == chunk2_id, f"next_after_restart_wrong_chunk body={replay}")
    print("PASS restart_replays_interrupted_pending")

    print("READER_MODE_V01_OK")
finally:
    try:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=1.0)
    except Exception:
        pass
PY
