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


class _DummyWorker:
    def __init__(self, running: bool = True, last_error: str = "") -> None:
        self._running = running
        self.last_error = last_error

    def start(self) -> None:
        return

    def stop(self, timeout: float = 0.0) -> None:
        self._running = False
        return

    def is_running(self) -> bool:
        return self._running


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

    def test_seek_phrase_scans_beyond_next_chunk(self) -> None:
        self.store.start_session("sess_f2", chunks=["uno", "dos", "objetivo final aqui"], reset=True)
        self.store.next_chunk("sess_f2")
        sought = self.store.seek_phrase("sess_f2", "objetivo final")
        self.assertTrue(sought.get("ok"))
        self.assertTrue(sought.get("seeked"))
        chunk = sought.get("chunk", {})
        self.assertEqual(int(chunk.get("chunk_index", -1)), 2)
        self.assertIn("objetivo", str(chunk.get("text", "")).lower())

    def test_seek_phrase_wraps_to_previous_chunks(self) -> None:
        self.store.start_session("sess_f3", chunks=["uno", "la herida no es escribe bien", "tres"], reset=True)
        c1 = self.store.next_chunk("sess_f3").get("chunk", {})
        self.store.commit("sess_f3", chunk_id=str(c1.get("chunk_id", "")), chunk_index=int(c1.get("chunk_index", 0)))
        c2 = self.store.next_chunk("sess_f3").get("chunk", {})
        self.store.commit("sess_f3", chunk_id=str(c2.get("chunk_id", "")), chunk_index=int(c2.get("chunk_index", 0)))
        self.store.next_chunk("sess_f3")
        sought = self.store.seek_phrase("sess_f3", "herida no es")
        self.assertTrue(sought.get("ok"))
        self.assertTrue(sought.get("seeked"))
        self.assertTrue(bool(sought.get("seek_wrapped", False)))
        chunk = sought.get("chunk", {})
        self.assertEqual(int(chunk.get("chunk_index", -1)), 1)
        self.assertIn("herida", str(chunk.get("text", "")).lower())

    def test_update_progress_advances_pending_offset(self) -> None:
        self.store.start_session("sess_prog", chunks=["uno dos tres cuatro cinco"], reset=True)
        first = self.store.next_chunk("sess_prog")
        chunk = first.get("chunk", {})
        cid = str(chunk.get("chunk_id", ""))
        out = self.store.update_progress("sess_prog", chunk_id=cid, offset_chars=8, quality="ui_live")
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("progress_updated"))
        chunk_after = out.get("chunk", {})
        self.assertGreaterEqual(int(chunk_after.get("offset_chars", -1)), 8)
        bookmark = out.get("bookmark", {})
        self.assertEqual(str(bookmark.get("quality", "")), "ui_live")

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
        self._voice_state_path = base / "direct_chat_voice.json"
        self._prev_store = direct_chat._READER_STORE
        self._prev_voice_state_path = direct_chat.VOICE_STATE_PATH
        self._prev_tts_dry_run = os.environ.get("DIRECT_CHAT_TTS_DRY_RUN")
        os.environ["DIRECT_CHAT_TTS_DRY_RUN"] = "1"
        direct_chat.VOICE_STATE_PATH = self._voice_state_path
        direct_chat._save_voice_state(direct_chat._default_voice_state())
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
            direct_chat.VOICE_STATE_PATH = self._prev_voice_state_path
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

    def test_http_reader_progress_updates_pending_offset(self) -> None:
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": "http_prog", "chunks": ["uno dos tres cuatro"], "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))
        code, first = self._request("GET", "/api/reader/session/next?session_id=http_prog")
        self.assertEqual(code, 200)
        chunk = first.get("chunk", {})
        cid = str(chunk.get("chunk_id", ""))
        code, out = self._request(
            "POST",
            "/api/reader/progress",
            {"session_id": "http_prog", "chunk_id": cid, "offset_chars": 7, "quality": "ui_live"},
        )
        self.assertEqual(code, 200)
        self.assertTrue(bool(out.get("progress_updated", False)))
        chunk_after = out.get("chunk", {})
        self.assertGreaterEqual(int(chunk_after.get("offset_chars", -1)), 7)

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

    def test_continuar_desde_la_frase_alias_is_parsed(self) -> None:
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": "alias_phrase_sess", "chunks": ["uno", "la herida no es escribe bien", "tres"], "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))
        code, first = self._request("GET", "/api/reader/session/next?session_id=alias_phrase_sess")
        self.assertEqual(code, 200)
        chunk = first.get("chunk", {})
        code, committed = self._request(
            "POST",
            "/api/reader/session/commit",
            {
                "session_id": "alias_phrase_sess",
                "chunk_id": str(chunk.get("chunk_id", "")),
                "chunk_index": int(chunk.get("chunk_index", 0)),
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(committed.get("ok"))
        code, out = self._request(
            "POST",
            "/api/chat",
            {
                "session_id": "alias_phrase_sess",
                "message": "continuar desde la frase la herida no es",
                "allowed_tools": [],
                "history": [],
            },
        )
        self.assertEqual(code, 200)
        self.assertNotIn("no encontr", str(out.get("reply", "")).lower())
        self.assertIn("herida", str(out.get("reply", "")).lower())

    def test_continua_desde_typos_are_parsed(self) -> None:
        variants = [
            'ok continua la lectura desde "la herida no es"',
            'ok contiuna la lectura desde "la herida no es"',
            'ok contionua la lectura desde "la herida no es"',
        ]
        for i, message in enumerate(variants):
            sid = f"alias_typo_{i}"
            code, started = self._request(
                "POST",
                "/api/reader/session/start",
                {"session_id": sid, "chunks": ["uno", "la herida no es escribe bien", "tres"], "reset": True},
            )
            self.assertEqual(code, 200)
            self.assertTrue(started.get("ok"))
            code, first = self._request("GET", f"/api/reader/session/next?session_id={sid}")
            self.assertEqual(code, 200)
            chunk = first.get("chunk", {})
            code, committed = self._request(
                "POST",
                "/api/reader/session/commit",
                {
                    "session_id": sid,
                    "chunk_id": str(chunk.get("chunk_id", "")),
                    "chunk_index": int(chunk.get("chunk_index", 0)),
                },
            )
            self.assertEqual(code, 200)
            self.assertTrue(committed.get("ok"))
            code, out = self._request(
                "POST",
                "/api/chat",
                {
                    "session_id": sid,
                    "message": message,
                    "allowed_tools": [],
                    "history": [],
                },
            )
            self.assertEqual(code, 200)
            self.assertNotIn("no encontr", str(out.get("reply", "")).lower())
            self.assertIn("herida", str(out.get("reply", "")).lower())

    def test_ir_al_parrafo_jumps_to_requested_block(self) -> None:
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {
                "session_id": "jump_paragraph_sess",
                "chunks": ["uno", "dos", "tres"],
                "reset": True,
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))
        code2, out = self._request(
            "POST",
            "/api/chat",
            {
                "session_id": "jump_paragraph_sess",
                "message": "ir al párrafo 3",
                "allowed_tools": [],
                "history": [],
            },
        )
        self.assertEqual(code2, 200)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("bloque 3/3", reply)
        self.assertIn("tres", reply)

    def test_leer_libro_same_book_paused_resumes_next_block(self) -> None:
        session_id = "same_book_resume_sess"
        direct_chat._READER_STORE.start_session(
            session_id,
            chunks=["uno", "dos", "tres"],
            reset=True,
            metadata={"book_id": "book_same_1", "title": "Libro Prueba"},
        )
        first = direct_chat._READER_STORE.next_chunk(session_id)
        first_chunk = first.get("chunk", {})
        direct_chat._READER_STORE.commit(
            session_id,
            chunk_id=str(first_chunk.get("chunk_id", "")),
            chunk_index=int(first_chunk.get("chunk_index", 0)),
            reason="unit_setup_commit",
        )
        direct_chat._READER_STORE.set_continuous(session_id, False, reason="unit_setup_pause")
        direct_chat._READER_STORE.set_reader_state(session_id, "paused", reason="unit_setup_pause")

        prev_list = direct_chat._READER_LIBRARY.list_books
        prev_get = direct_chat._READER_LIBRARY.get_book_text
        direct_chat._READER_LIBRARY.list_books = lambda: {  # type: ignore[assignment]
            "ok": True,
            "books": [{"book_id": "book_same_1", "title": "Libro Prueba", "format": "txt"}],
        }
        direct_chat._READER_LIBRARY.get_book_text = lambda _book_id: {  # type: ignore[assignment]
            "ok": True,
            "text": "uno\ndos\ntres",
            "book": {"book_id": "book_same_1", "title": "Libro Prueba", "format": "txt"},
        }
        self._request(
            "POST",
            "/api/voice",
            {
                "session_id": session_id,
                "reader_owner_token": "resume_token_same_book",
                "voice_owner": "reader",
                "reader_mode_active": True,
            },
        )
        try:
            code, out = self._request(
                "POST",
                "/api/chat",
                {
                    "session_id": session_id,
                    "message": "leer libro 1",
                    "allowed_tools": [],
                    "history": [],
                },
            )
        finally:
            direct_chat._READER_LIBRARY.list_books = prev_list  # type: ignore[assignment]
            direct_chat._READER_LIBRARY.get_book_text = prev_get  # type: ignore[assignment]

        self.assertEqual(code, 200)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("bloque 2/3", reply)
        self.assertNotIn("ya estoy leyendo", reply)

    def test_leer_libro_same_book_with_reader_mode_off_starts_from_block_one(self) -> None:
        session_id = "same_book_off_starts_from_one_sess"
        direct_chat._READER_STORE.start_session(
            session_id,
            chunks=["uno", "dos", "tres"],
            reset=True,
            metadata={"book_id": "book_same_2", "title": "Libro Prueba Off"},
        )
        first = direct_chat._READER_STORE.next_chunk(session_id)
        first_chunk = first.get("chunk", {})
        direct_chat._READER_STORE.commit(
            session_id,
            chunk_id=str(first_chunk.get("chunk_id", "")),
            chunk_index=int(first_chunk.get("chunk_index", 0)),
            reason="unit_setup_commit",
        )
        direct_chat._READER_STORE.set_continuous(session_id, False, reason="unit_setup_pause")
        direct_chat._READER_STORE.set_reader_state(session_id, "paused", reason="unit_setup_pause")

        prev_list = direct_chat._READER_LIBRARY.list_books
        prev_get = direct_chat._READER_LIBRARY.get_book_text
        direct_chat._READER_LIBRARY.list_books = lambda: {  # type: ignore[assignment]
            "ok": True,
            "books": [{"book_id": "book_same_2", "title": "Libro Prueba Off", "format": "txt"}],
        }
        direct_chat._READER_LIBRARY.get_book_text = lambda _book_id: {  # type: ignore[assignment]
            "ok": True,
            "text": "uno\ndos\ntres",
            "book": {"book_id": "book_same_2", "title": "Libro Prueba Off", "format": "txt"},
        }
        self._request(
            "POST",
            "/api/voice",
            {
                "session_id": session_id,
                "reader_owner_token": "off_token_same_book",
                "voice_owner": "reader",
                "reader_mode_active": True,
            },
        )
        self._request(
            "POST",
            "/api/voice",
            {
                "session_id": session_id,
                "reader_owner_token": "off_token_same_book",
                "voice_owner": "chat",
                "reader_mode_active": False,
                "enabled": False,
            },
        )
        try:
            code, out = self._request(
                "POST",
                "/api/chat",
                {
                    "session_id": session_id,
                    "message": "leer libro 1",
                    "allowed_tools": [],
                    "history": [],
                },
            )
        finally:
            direct_chat._READER_LIBRARY.list_books = prev_list  # type: ignore[assignment]
            direct_chat._READER_LIBRARY.get_book_text = prev_get  # type: ignore[assignment]

        self.assertEqual(code, 200)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("bloque 1/", reply)
        self.assertIn("lectura iniciada", reply)
        self.assertNotIn("retomo lectura", reply)

    def test_continuar_desde_can_jump_to_unread_future_block(self) -> None:
        sid = "continue_from_future_block_sess"
        chunks = [f"bloque {i}" for i in range(1, 13)]
        chunks[9] = "target phrase block ten exacta para salto"
        code, started = self._request(
            "POST",
            "/api/reader/session/start",
            {"session_id": sid, "chunks": chunks, "reset": True},
        )
        self.assertEqual(code, 200)
        self.assertTrue(started.get("ok"))
        self._request("GET", f"/api/reader/session/next?session_id={sid}")
        code2, out = self._request(
            "POST",
            "/api/chat",
            {
                "session_id": sid,
                "message": 'continuar desde "target phrase block ten exacta"',
                "allowed_tools": [],
                "history": [],
            },
        )
        self.assertEqual(code2, 200)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("bloque 10/12", reply)
        self.assertIn("target phrase block ten exacta", reply)

    def test_voice_payload_exposes_diagnostics(self) -> None:
        code, out = self._request("GET", "/api/voice")
        self.assertEqual(code, 200)
        self.assertIn("voice_owner", out)
        self.assertIn("reader_mode_active", out)
        self.assertIn("tts_backend", out)
        self.assertIn("tts_health_url", out)
        self.assertIn("tts_health_timeout_sec", out)
        self.assertIn("tts_available", out)
        self.assertIn("stt_no_speech_detected", out)
        self.assertIn("stt_vad_true_ratio", out)

    def test_voice_mode_profile_stable_applies_conservative_flags(self) -> None:
        code, out = self._request(
            "POST",
            "/api/voice",
            {
                "session_id": "voice_mode_sess",
                "voice_mode_profile": "stable",
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(bool(out.get("ok", False)))
        self.assertEqual(str(out.get("voice_mode_profile", "")), "stable")
        self.assertFalse(bool(out.get("stt_chat_enabled", True)))
        self.assertFalse(bool(out.get("stt_barge_any", True)))

        code2, out2 = self._request(
            "POST",
            "/api/voice",
            {
                "session_id": "voice_mode_sess",
                "voice_mode_profile": "experimental",
            },
        )
        self.assertEqual(code2, 200)
        self.assertTrue(bool(out2.get("ok", False)))
        self.assertEqual(str(out2.get("voice_mode_profile", "")), "experimental")
        self.assertTrue(bool(out2.get("stt_chat_enabled", False)))
        self.assertTrue(bool(out2.get("stt_barge_any", False)))

    def test_voice_owner_reader_mode_fields_roundtrip(self) -> None:
        token = "voice_owner_token_roundtrip"
        code, out = self._request(
            "POST",
            "/api/voice",
            {
                "session_id": "voice_owner_sess",
                "reader_owner_token": token,
                "voice_owner": "reader",
                "reader_mode_active": True,
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(bool(out.get("ok", False)))
        self.assertEqual(str(out.get("voice_owner", "")), "reader")
        self.assertTrue(bool(out.get("reader_mode_active", False)))
        self.assertTrue(bool(out.get("reader_owner_token_set", False)))

        code2, out2 = self._request(
            "POST",
            "/api/voice",
            {
                "session_id": "voice_owner_sess",
                "reader_owner_token": token,
                "voice_owner": "chat",
                "reader_mode_active": False,
            },
        )
        self.assertEqual(code2, 200)
        self.assertEqual(str(out2.get("voice_owner", "")), "chat")
        self.assertFalse(bool(out2.get("reader_mode_active", True)))
        self.assertFalse(bool(out2.get("reader_owner_token_set", True)))

    def test_voice_owner_release_with_wrong_token_is_blocked(self) -> None:
        code, out = self._request(
            "POST",
            "/api/voice",
            {
                "session_id": "voice_owner_conflict_sess",
                "reader_owner_token": "token_a",
                "voice_owner": "reader",
                "reader_mode_active": True,
                "enabled": True,
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(bool(out.get("ok", False)))
        self.assertEqual(str(out.get("voice_owner", "")), "reader")

        code2, out2 = self._request(
            "POST",
            "/api/voice",
            {
                "session_id": "voice_owner_conflict_sess",
                "reader_owner_token": "token_b",
                "voice_owner": "chat",
                "reader_mode_active": False,
                "enabled": False,
            },
        )
        self.assertEqual(code2, 200)
        self.assertTrue(bool(out2.get("ownership_conflict", False)))
        self.assertEqual(str(out2.get("voice_owner", "")), "reader")
        self.assertTrue(bool(out2.get("reader_mode_active", False)))

    def test_stt_level_endpoint_exposes_runtime_fields(self) -> None:
        code, out = self._request("GET", "/api/stt/level?session_id=default")
        self.assertEqual(code, 200)
        self.assertTrue(bool(out.get("ok", False)))
        self.assertIn("rms", out)
        self.assertIn("threshold", out)
        self.assertIn("vad_true_ratio", out)
        self.assertIn("last_segment_ms", out)

    def test_stt_poll_owner_mismatch_returns_409(self) -> None:
        mgr = direct_chat._STT_MANAGER
        with mgr._lock:
            prev_enabled = bool(mgr._enabled)
            prev_owner = str(mgr._owner_session_id)
            prev_worker = mgr._worker
            mgr._enabled = True
            mgr._owner_session_id = "owner_session"
            mgr._worker = _DummyWorker(running=True)
        try:
            code, out = self._request("GET", "/api/stt/poll?session_id=other_session")
            self.assertEqual(code, 409)
            self.assertEqual(str(out.get("error", "")), "stt_owner_mismatch")
            self.assertEqual(str(out.get("stt_owner_session_id", "")), "owner_session")
        finally:
            with mgr._lock:
                mgr._enabled = prev_enabled
                mgr._owner_session_id = prev_owner
                mgr._worker = prev_worker

    def test_stt_inject_and_poll_returns_voice_command(self) -> None:
        mgr = direct_chat._STT_MANAGER
        with mgr._lock:
            prev_enabled = bool(mgr._enabled)
            prev_owner = str(mgr._owner_session_id)
            prev_worker = mgr._worker
            mgr._enabled = True
            mgr._owner_session_id = "inject_session"
            mgr._worker = _DummyWorker(running=True)
            mgr._clear_queue_locked()
        try:
            code, out = self._request(
                "POST",
                "/api/stt/inject",
                {"session_id": "inject_session", "cmd": "pausa"},
            )
            self.assertEqual(code, 200)
            self.assertTrue(bool(out.get("ok", False)))
            code, polled = self._request("GET", "/api/stt/poll?session_id=inject_session&limit=2")
            self.assertEqual(code, 200)
            items = polled.get("items", [])
            self.assertIsInstance(items, list)
            self.assertTrue(items)
            first = items[0] if isinstance(items[0], dict) else {}
            self.assertEqual(str(first.get("cmd", "")), "pause")
            self.assertEqual(str(first.get("kind", "")), "voice_cmd")
        finally:
            with mgr._lock:
                mgr._enabled = prev_enabled
                mgr._owner_session_id = prev_owner
                mgr._worker = prev_worker
                mgr._clear_queue_locked()

if __name__ == "__main__":
    unittest.main()
