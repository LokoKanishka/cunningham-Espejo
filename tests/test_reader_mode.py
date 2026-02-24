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

    def test_continuous_state_turns_off_on_eof(self) -> None:
        started = self.store.start_session("sess_d", chunks=["uno"], reset=True)
        self.assertTrue(started.get("ok"))
        toggled = self.store.set_continuous("sess_d", True, reason="test")
        self.assertTrue(toggled.get("ok"))
        self.assertTrue(toggled.get("continuous_active"))

        nxt = self.store.next_chunk("sess_d")
        chunk = nxt.get("chunk", {})
        committed = self.store.commit(
            "sess_d",
            chunk_id=str(chunk.get("chunk_id", "")),
            chunk_index=int(chunk.get("chunk_index", 0)),
            reason="unit_test",
        )
        self.assertTrue(committed.get("ok"))
        self.assertTrue(committed.get("done"))
        self.assertFalse(committed.get("continuous_active"))
        self.assertEqual(str(committed.get("continuous_reason", "")), "eof")

    def test_barge_in_sets_bookmark_offset(self) -> None:
        txt = "Primera frase para lectura. Segunda frase para corte. Tercera frase para continuar."
        self.store.start_session("sess_e", chunks=[txt], reset=True)
        self.store.next_chunk("sess_e")
        interrupted = self.store.mark_barge_in("sess_e", detail="speech_cut", playback_ms=700.0)
        self.assertTrue(interrupted.get("ok"))
        self.assertTrue(interrupted.get("interrupted"))
        bookmark = interrupted.get("bookmark", {})
        self.assertIsInstance(bookmark, dict)
        self.assertGreaterEqual(int(bookmark.get("offset_chars", -1)), 0)
        self.assertEqual(str(interrupted.get("reader_state", "")), "commenting")

    def test_seek_phrase_and_rewind_sentence(self) -> None:
        txt = "Inicio del texto. Punto de control matriz para retomar. Cierre de ejemplo."
        self.store.start_session("sess_f", chunks=[txt], reset=True)
        self.store.next_chunk("sess_f")
        self.store.mark_barge_in("sess_f", detail="speech_cut", playback_ms=400.0)
        sought = self.store.seek_phrase("sess_f", "matriz")
        self.assertTrue(sought.get("ok"))
        self.assertTrue(sought.get("seeked"))
        chunk = sought.get("chunk", {})
        self.assertTrue(str(chunk.get("text", "")).lower().startswith("matriz"))
        rew = self.store.rewind("sess_f", unit="sentence")
        self.assertTrue(rew.get("ok"))
        self.assertTrue(rew.get("rewound"))
        self.assertEqual(str(rew.get("rewind_unit", "")), "sentence")

    def test_manual_mode_toggle_controls_autopilot(self) -> None:
        self.store.start_session("sess_g", chunks=["uno", "dos"], reset=True)
        man_on = self.store.set_manual_mode("sess_g", True, reason="unit_manual_on")
        self.assertTrue(man_on.get("ok"))
        self.assertTrue(bool(man_on.get("manual_mode", False)))
        self.assertFalse(bool(man_on.get("continuous_enabled", True)))
        cont_on = self.store.set_continuous("sess_g", True, reason="unit_cont_on")
        self.assertTrue(cont_on.get("ok"))
        self.assertTrue(bool(cont_on.get("continuous_enabled", False)))
        self.assertFalse(bool(cont_on.get("manual_mode", True)))


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
        with direct_chat._READER_AUTOCOMMIT_LOCK:
            direct_chat._READER_AUTOCOMMIT_BY_STREAM.clear()
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

    def test_http_barge_in_accepts_playback_offset(self) -> None:
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": "http_barge_offset", "chunks": ["uno dos tres cuatro"], "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))
        self._request("GET", "/api/reader/session/next?session_id=http_barge_offset")
        code, barge = self._request(
            "POST",
            "/api/reader/session/barge_in",
            {"session_id": "http_barge_offset", "detail": "speech_detected", "playback_ms": 500},
        )
        self.assertEqual(code, 200)
        self.assertTrue(barge.get("interrupted"))
        bookmark = barge.get("bookmark", {})
        self.assertIsInstance(bookmark, dict)
        self.assertGreaterEqual(int(bookmark.get("offset_chars", -1)), 0)

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

    def test_non_reader_message_interrupts_continuous(self) -> None:
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": "interrupt_sess", "chunks": ["uno", "dos"], "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))
        direct_chat._READER_STORE.set_continuous("interrupt_sess", True, reason="test_interrupt")  # type: ignore

        code, out = self._request(
            "POST",
            "/api/chat",
            {
                "session_id": "interrupt_sess",
                "message": "voz off",
                "allowed_tools": ["tts"],
                "history": [],
            },
        )
        self.assertEqual(code, 200)
        self.assertIn("desactiv", str(out.get("reply", "")).lower())

        code, st = self._request("GET", "/api/reader/session?session_id=interrupt_sess")
        self.assertEqual(code, 200)
        self.assertFalse(bool(st.get("continuous_active", True)))
        self.assertEqual(str(st.get("continuous_reason", "")), "reader_user_interrupt")

    def test_autocommit_timeout_commits_pending(self) -> None:
        direct_chat._READER_STORE.start_session("timeout_commit", chunks=["uno", "dos"], reset=True)
        out = direct_chat._READER_STORE.next_chunk("timeout_commit")
        chunk = out.get("chunk", {})
        stream_id = 99001
        direct_chat._reader_autocommit_register(
            stream_id=stream_id,
            session_id="timeout_commit",
            chunk_id=str(chunk.get("chunk_id", "")),
            chunk_index=int(chunk.get("chunk_index", 0)),
            text_len=len(str(chunk.get("text", ""))),
            start_offset_chars=0,
        )
        direct_chat._reader_autocommit_finalize(stream_id, False, detail="tts_end_timeout", force_timeout_commit=True)
        st = direct_chat._READER_STORE.get_session("timeout_commit", include_chunks=False)
        self.assertEqual(int(st.get("cursor", -1)), 1)
        self.assertFalse(bool(st.get("has_pending", True)))

    def test_autocommit_interrupt_keeps_pending(self) -> None:
        direct_chat._READER_STORE.start_session("interrupt_keep", chunks=["uno", "dos"], reset=True)
        out = direct_chat._READER_STORE.next_chunk("interrupt_keep")
        chunk = out.get("chunk", {})
        stream_id = 99002
        direct_chat._reader_autocommit_register(
            stream_id=stream_id,
            session_id="interrupt_keep",
            chunk_id=str(chunk.get("chunk_id", "")),
            chunk_index=int(chunk.get("chunk_index", 0)),
            text_len=len(str(chunk.get("text", ""))),
            start_offset_chars=0,
        )
        direct_chat._reader_autocommit_finalize(stream_id, False, detail="playback_interrupted", force_timeout_commit=False)
        st = direct_chat._READER_STORE.get_session("interrupt_keep", include_chunks=False)
        self.assertEqual(int(st.get("cursor", -1)), 0)
        self.assertTrue(bool(st.get("has_pending", False)))

    def test_autocommit_barge_in_triggered_keeps_pending(self) -> None:
        direct_chat._READER_STORE.start_session("interrupt_keep_barge", chunks=["uno", "dos"], reset=True)
        out = direct_chat._READER_STORE.next_chunk("interrupt_keep_barge")
        chunk = out.get("chunk", {})
        stream_id = 99003
        direct_chat._reader_autocommit_register(
            stream_id=stream_id,
            session_id="interrupt_keep_barge",
            chunk_id=str(chunk.get("chunk_id", "")),
            chunk_index=int(chunk.get("chunk_index", 0)),
            text_len=len(str(chunk.get("text", ""))),
            start_offset_chars=0,
        )
        direct_chat._reader_autocommit_finalize(stream_id, False, detail="barge_in_triggered", force_timeout_commit=False)
        st = direct_chat._READER_STORE.get_session("interrupt_keep_barge", include_chunks=False)
        self.assertEqual(int(st.get("cursor", -1)), 0)
        self.assertTrue(bool(st.get("has_pending", False)))

    def test_continuar_unstucks_pending_after_tts_failure(self) -> None:
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": "unstuck_sess", "chunks": ["uno", "dos"], "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))
        direct_chat._READER_STORE.set_continuous("unstuck_sess", True, reason="test_unstuck")  # type: ignore
        self._request("GET", "/api/reader/session/next?session_id=unstuck_sess")
        direct_chat._VOICE_LAST_STATUS = {"ok": False, "detail": "tts_end_timeout", "ts": time.time(), "stream_id": 42}  # type: ignore
        time.sleep(1.6)
        code, out = self._request(
            "POST",
            "/api/chat",
            {
                "session_id": "unstuck_sess",
                "message": "continuar",
                "allowed_tools": [],
                "history": [],
            },
        )
        self.assertEqual(code, 200)
        self.assertIn("bloque 2/2", str(out.get("reply", "")).lower())

    def test_voice_payload_exposes_diagnostics(self) -> None:
        code, out = self._request("GET", "/api/voice")
        self.assertEqual(code, 200)
        self.assertIn("tts_backend", out)
        self.assertIn("tts_health_url", out)
        self.assertIn("tts_health_timeout_sec", out)
        self.assertIn("tts_available", out)

if __name__ == "__main__":
    unittest.main()
