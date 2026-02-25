import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


import openclaw_direct_chat as direct_chat  # noqa: E402


class TestReaderLibraryHttpEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._state_path = base / "reading_sessions.json"
        self._lock_path = base / ".reading_sessions.lock"
        self._library_dir = base / "Lucy_Library"
        self._library_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = base / "reader_library_index.json"
        self._index_lock = base / ".reader_library_index.lock"
        self._cache_dir = base / "reader_cache"

        self._prev_store = direct_chat._READER_STORE
        self._prev_library = direct_chat._READER_LIBRARY

        direct_chat._READER_STORE = direct_chat.ReaderSessionStore(
            state_path=self._state_path,
            lock_path=self._lock_path,
        )
        direct_chat._READER_LIBRARY = direct_chat.ReaderLibraryIndex(
            library_dir=self._library_dir,
            index_path=self._index_path,
            lock_path=self._index_lock,
            cache_dir=self._cache_dir,
        )

        self._httpd = direct_chat.ThreadingHTTPServer(("127.0.0.1", 0), direct_chat.Handler)
        self._httpd.gateway_token = "test-token"
        self._httpd.gateway_port = 18789
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self.base = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        time.sleep(0.05)

    def tearDown(self) -> None:
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._thread.join(timeout=1.0)
        finally:
            direct_chat._READER_STORE = self._prev_store
            direct_chat._READER_LIBRARY = self._prev_library
            self._tmp.cleanup()

    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(self.base + path, method=method, data=data, headers=headers)
        try:
            with urlopen(req, timeout=5) as resp:
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

    def test_rescan_list_and_start_session_from_book_id(self) -> None:
        book = self._library_dir / "capitulo_uno.txt"
        book.write_text("Linea uno del libro.\n\nLinea dos del libro.", encoding="utf-8")

        code, rescanned = self._request("POST", "/api/reader/rescan", {})
        self.assertEqual(code, 200)
        self.assertTrue(rescanned.get("ok"))
        self.assertGreaterEqual(int(rescanned.get("count", 0)), 1)

        code, books = self._request("GET", "/api/reader/books")
        self.assertEqual(code, 200)
        self.assertTrue(books.get("ok"))
        listed = books.get("books", [])
        self.assertTrue(isinstance(listed, list) and listed)
        first = listed[0]
        self.assertEqual(str(first.get("format", "")), "txt")
        self.assertTrue(str(first.get("book_id", "")))

        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": "book_sess", "book_id": str(first.get("book_id", "")), "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))
        self.assertTrue(started.get("started"))

        code, status = self._request("GET", "/api/reader/session?session_id=book_sess")
        self.assertEqual(code, 200)
        self.assertTrue(status.get("ok"))
        self.assertGreater(int(status.get("total_chunks", 0)), 0)


if __name__ == "__main__":
    unittest.main()
