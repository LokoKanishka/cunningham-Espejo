#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "== verify reader mode v0 ==" >&2
echo "tmp_dir=${TMP_DIR}" >&2

python3 - "${TMP_DIR}" <<'PY'
import json
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
            "session_id": "verify_rm",
            "chunks": [
                "Primer bloque de lectura.",
                "Segundo bloque para probar barge-in.",
                "Tercer bloque final.",
            ],
            "reset": True,
            "metadata": {"source": "verify_reader_mode"},
        },
    )
    ensure(code == 200 and bool(started.get("ok")), f"start_failed code={code} body={started}")
    print("PASS start_session")

    code, first = request("GET", "/api/reader/session/next?session_id=verify_rm")
    chunk1 = first.get("chunk", {}) if isinstance(first, dict) else {}
    chunk1_id = str(chunk1.get("chunk_id", ""))
    ensure(code == 200 and bool(first.get("ok")), f"next_1_failed code={code} body={first}")
    ensure(int(chunk1.get("chunk_index", -1)) == 0, f"next_1_bad_index body={first}")
    ensure(not bool(first.get("replayed")), f"next_1_should_not_replay body={first}")
    print("PASS next_chunk_1")

    code, commit1 = request("POST", "/api/reader/session/commit", {"session_id": "verify_rm", "chunk_id": chunk1_id})
    ensure(code == 200 and bool(commit1.get("committed")), f"commit_1_failed code={code} body={commit1}")
    ensure(int(commit1.get("cursor", -1)) == 1, f"commit_1_bad_cursor body={commit1}")
    print("PASS commit_chunk_1")

    code, second = request("GET", "/api/reader/session/next?session_id=verify_rm")
    chunk2 = second.get("chunk", {}) if isinstance(second, dict) else {}
    chunk2_id = str(chunk2.get("chunk_id", ""))
    ensure(code == 200 and bool(second.get("ok")), f"next_2_failed code={code} body={second}")
    ensure(int(chunk2.get("chunk_index", -1)) == 1, f"next_2_bad_index body={second}")
    print("PASS next_chunk_2")

    code, interrupted = request(
        "POST",
        "/api/reader/session/barge_in",
        {"session_id": "verify_rm", "detail": "vad+rms threshold hit"},
    )
    ensure(code == 200 and bool(interrupted.get("interrupted")), f"barge_in_failed code={code} body={interrupted}")
    ensure(int(interrupted.get("cursor", -1)) == 1, f"barge_in_bad_cursor body={interrupted}")
    ensure(int(interrupted.get("barge_in_count", 0)) == 1, f"barge_in_bad_count body={interrupted}")
    print("PASS barge_in_pending")

    # Reinicio simulado: nueva instancia en memoria sobre el mismo estado persistido.
    direct_chat._READER_STORE = direct_chat.ReaderSessionStore(state_path=state_path, lock_path=lock_path)
    code, replay = request("GET", "/api/reader/session/next?session_id=verify_rm")
    ensure(code == 200 and bool(replay.get("ok")), f"next_after_restart_failed code={code} body={replay}")
    ensure(bool(replay.get("replayed")), f"next_after_restart_should_replay body={replay}")
    ensure(str(replay.get("chunk", {}).get("chunk_id", "")) == chunk2_id, f"next_after_restart_wrong_chunk body={replay}")
    print("PASS restart_replays_pending_chunk")

    code, commit2 = request("POST", "/api/reader/session/commit", {"session_id": "verify_rm", "chunk_id": chunk2_id})
    ensure(code == 200 and bool(commit2.get("committed")), f"commit_2_failed code={code} body={commit2}")
    ensure(int(commit2.get("cursor", -1)) == 2, f"commit_2_bad_cursor body={commit2}")
    print("PASS commit_chunk_2")

    code, third = request("GET", "/api/reader/session/next?session_id=verify_rm")
    chunk3 = third.get("chunk", {}) if isinstance(third, dict) else {}
    chunk3_id = str(chunk3.get("chunk_id", ""))
    ensure(code == 200 and int(chunk3.get("chunk_index", -1)) == 2, f"next_3_failed code={code} body={third}")
    print("PASS next_chunk_3")

    code, commit3 = request("POST", "/api/reader/session/commit", {"session_id": "verify_rm", "chunk_id": chunk3_id})
    ensure(code == 200 and bool(commit3.get("committed")), f"commit_3_failed code={code} body={commit3}")
    ensure(bool(commit3.get("done")), f"commit_3_not_done body={commit3}")
    print("PASS commit_chunk_3")

    code, eof = request("GET", "/api/reader/session/next?session_id=verify_rm")
    ensure(code == 200 and bool(eof.get("ok")), f"next_eof_failed code={code} body={eof}")
    ensure(eof.get("chunk") is None, f"next_eof_expected_null_chunk body={eof}")
    ensure(bool(eof.get("done")), f"next_eof_expected_done body={eof}")
    print("PASS eof")

    code, status = request("GET", "/api/reader/session?session_id=verify_rm")
    ensure(code == 200 and bool(status.get("ok")), f"status_failed code={code} body={status}")
    ensure(int(status.get("cursor", -1)) == 3, f"status_bad_cursor body={status}")
    ensure(int(status.get("barge_in_count", 0)) == 1, f"status_bad_bargein_count body={status}")
    print("PASS persisted_status")

    print("READER_MODE_OK")
finally:
    try:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=1.0)
    except Exception:
        pass
PY
