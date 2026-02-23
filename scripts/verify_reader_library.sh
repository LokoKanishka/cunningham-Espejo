#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "== verify reader library v0 ==" >&2
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

library_dir = tmp_dir / "Lucy_Library"
library_dir.mkdir(parents=True, exist_ok=True)
book_path = library_dir / "libro_demo.txt"
book_path.write_text(
    "Primer bloque del libro de prueba.\n\n"
    "Segundo bloque para autocommit.\n\n"
    "Tercer bloque para reinicio.",
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
    code, rescanned = request("POST", "/api/reader/rescan", {})
    ensure(code == 200 and bool(rescanned.get("ok")), f"rescan_failed code={code} body={rescanned}")
    ensure(int(rescanned.get("count", 0)) >= 1, f"rescan_count_failed body={rescanned}")
    print("PASS rescan")

    code, books = request("GET", "/api/reader/books")
    ensure(code == 200 and bool(books.get("ok")), f"books_failed code={code} body={books}")
    listed = books.get("books", [])
    ensure(isinstance(listed, list) and listed, f"books_empty body={books}")
    b0 = listed[0]
    book_id = str(b0.get("book_id", ""))
    ensure(bool(book_id), f"book_id_missing body={books}")
    print("PASS books_list")

    code, started = request(
        "POST",
        "/api/reader/session/start",
        {"session_id": "verify_lib", "book_id": book_id, "reset": True},
    )
    ensure(code == 200 and bool(started.get("ok")) and bool(started.get("started")), f"start_failed code={code} body={started}")
    print("PASS start_from_book")

    code, first = request("GET", "/api/reader/session/next?session_id=verify_lib&speak=1&autocommit=1")
    ensure(code == 200 and bool(first.get("ok")), f"next_failed code={code} body={first}")
    ensure(bool(first.get("autocommit_registered")), f"autocommit_not_registered body={first}")

    status = {}
    for _ in range(80):
        code, status = request("GET", "/api/reader/session?session_id=verify_lib")
        ensure(code == 200, f"status_failed code={code} body={status}")
        if int(status.get("cursor", -1)) >= 1 and status.get("pending") is None:
            break
        time.sleep(0.05)
    ensure(int(status.get("cursor", -1)) >= 1, f"cursor_not_advanced body={status}")
    print("PASS autocommit_advances_cursor")

    direct_chat._READER_STORE = direct_chat.ReaderSessionStore(state_path=state_path, lock_path=lock_path)
    code, after_restart = request("GET", "/api/reader/session?session_id=verify_lib")
    ensure(code == 200 and bool(after_restart.get("ok")), f"status_after_restart_failed code={code} body={after_restart}")
    ensure(int(after_restart.get("cursor", -1)) >= 1, f"status_after_restart_bad_cursor body={after_restart}")
    print("PASS persisted_after_restart")

    print("READER_LIBRARY_OK")
finally:
    try:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=1.0)
    except Exception:
        pass
PY
