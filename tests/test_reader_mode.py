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


class TestReaderSessionStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.store = direct_chat.ReaderSessionStore(
            state_path=base / "reading_sessions.json",
            lock_path=base / ".reading_sessions.lock",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cursor_advances_only_on_commit(self) -> None:
        started = self.store.start_session("sess_a", chunks=["uno", "dos"], reset=True)
        self.assertTrue(started.get("ok"))
        self.assertTrue(started.get("started"))

        next_one = self.store.next_chunk("sess_a")
        self.assertTrue(next_one.get("ok"))
        self.assertFalse(next_one.get("replayed"))
        self.assertEqual(int(next_one.get("cursor", -1)), 0)
        chunk = next_one.get("chunk", {})
        self.assertEqual(int(chunk.get("chunk_index", -1)), 0)
        self.assertEqual(str(chunk.get("text", "")), "uno")

        replay = self.store.next_chunk("sess_a")
        self.assertTrue(replay.get("ok"))
        self.assertTrue(replay.get("replayed"))
        self.assertEqual(int(replay.get("cursor", -1)), 0)
        self.assertEqual(int(replay.get("chunk", {}).get("chunk_index", -1)), 0)

        committed = self.store.commit("sess_a", chunk_id=str(replay.get("chunk", {}).get("chunk_id", "")))
        self.assertTrue(committed.get("ok"))
        self.assertTrue(committed.get("committed"))
        self.assertEqual(int(committed.get("cursor", -1)), 1)

        next_two = self.store.next_chunk("sess_a")
        self.assertTrue(next_two.get("ok"))
        self.assertFalse(next_two.get("replayed"))
        self.assertEqual(int(next_two.get("chunk", {}).get("chunk_index", -1)), 1)
        self.assertEqual(str(next_two.get("chunk", {}).get("text", "")), "dos")

    def test_barge_in_does_not_advance_cursor_and_survives_restart(self) -> None:
        self.store.start_session("sess_b", chunks=["alpha", "beta"], reset=True)
        first = self.store.next_chunk("sess_b")
        chunk_id = str(first.get("chunk", {}).get("chunk_id", ""))

        interrupted = self.store.mark_barge_in("sess_b", detail="vad:rms-trigger")
        self.assertTrue(interrupted.get("ok"))
        self.assertTrue(interrupted.get("interrupted"))
        self.assertEqual(int(interrupted.get("barge_in_count", 0)), 1)
        self.assertEqual(int(interrupted.get("cursor", -1)), 0)

        # Simulate restart by opening a new store over the same persisted state file.
        restarted = direct_chat.ReaderSessionStore(
            state_path=self.store.state_path,
            lock_path=self.store.lock_path,
        )
        replay = restarted.next_chunk("sess_b")
        self.assertTrue(replay.get("ok"))
        self.assertTrue(replay.get("replayed"))
        self.assertEqual(int(replay.get("cursor", -1)), 0)
        self.assertEqual(str(replay.get("chunk", {}).get("chunk_id", "")), chunk_id)

        committed = restarted.commit("sess_b", chunk_id=chunk_id)
        self.assertTrue(committed.get("ok"))
        self.assertTrue(committed.get("committed"))
        self.assertEqual(int(committed.get("cursor", -1)), 1)

    def test_commit_mismatch_returns_error(self) -> None:
        self.store.start_session("sess_c", chunks=["hola"], reset=True)
        self.store.next_chunk("sess_c")
        out = self.store.commit("sess_c", chunk_id="chunk_bad")
        self.assertFalse(out.get("ok"))
        self.assertEqual(str(out.get("error", "")), "reader_commit_chunk_mismatch")


class TestReaderHttpEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._state_path = base / "reading_sessions.json"
        self._lock_path = base / ".reading_sessions.lock"
        self._prev_store = direct_chat._READER_STORE
        self._prev_tts_dry_run = os.environ.get("DIRECT_CHAT_TTS_DRY_RUN")
        os.environ["DIRECT_CHAT_TTS_DRY_RUN"] = "1"
        direct_chat._READER_STORE = direct_chat.ReaderSessionStore(
            state_path=self._state_path,
            lock_path=self._lock_path,
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
            if self._prev_tts_dry_run is None:
                os.environ.pop("DIRECT_CHAT_TTS_DRY_RUN", None)
            else:
                os.environ["DIRECT_CHAT_TTS_DRY_RUN"] = self._prev_tts_dry_run
            direct_chat._READER_STORE = self._prev_store
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

    def test_http_flow_replay_after_restart(self) -> None:
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": "http_sess", "chunks": ["uno", "dos"], "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))

        code, first = self._request("GET", "/api/reader/session/next?session_id=http_sess")
        self.assertEqual(code, 200)
        first_chunk = first.get("chunk", {})
        self.assertEqual(int(first_chunk.get("chunk_index", -1)), 0)
        chunk_id = str(first_chunk.get("chunk_id", ""))

        code, barge = self._request(
            "POST",
            "/api/reader/session/barge_in",
            {"session_id": "http_sess", "detail": "speech_detected"},
        )
        self.assertEqual(code, 200)
        self.assertTrue(barge.get("interrupted"))
        self.assertEqual(int(barge.get("barge_in_count", 0)), 1)

        # Simulate process restart by replacing the in-memory store instance.
        direct_chat._READER_STORE = direct_chat.ReaderSessionStore(
            state_path=self._state_path,
            lock_path=self._lock_path,
        )

        code, replay = self._request("GET", "/api/reader/session/next?session_id=http_sess")
        self.assertEqual(code, 200)
        self.assertTrue(replay.get("replayed"))
        self.assertEqual(str(replay.get("chunk", {}).get("chunk_id", "")), chunk_id)

        code, committed = self._request(
            "POST",
            "/api/reader/session/commit",
            {"session_id": "http_sess", "chunk_id": chunk_id},
        )
        self.assertEqual(code, 200)
        self.assertTrue(committed.get("committed"))
        self.assertEqual(int(committed.get("cursor", -1)), 1)

    def test_next_with_speak_and_autocommit_advances_cursor_after_tts_end(self) -> None:
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": "auto_sess", "chunks": ["uno", "dos"], "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))

        code, first = self._request(
            "GET",
            "/api/reader/session/next?session_id=auto_sess&speak=1&autocommit=1",
        )
        self.assertEqual(code, 200)
        self.assertTrue(first.get("ok"))
        self.assertTrue(first.get("speak_started"))
        self.assertTrue(first.get("autocommit_registered"))

        status = {}
        for _ in range(60):
            code, status = self._request("GET", "/api/reader/session?session_id=auto_sess")
            self.assertEqual(code, 200)
            if int(status.get("cursor", -1)) == 1 and status.get("pending") is None:
                break
            time.sleep(0.05)

        self.assertEqual(int(status.get("cursor", -1)), 1)
        self.assertIsNone(status.get("pending"))


if __name__ == "__main__":
    unittest.main()
