import os
import io
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch


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


class TestVoiceSttManager(unittest.TestCase):
    @patch("openclaw_direct_chat._save_voice_state")
    @patch("openclaw_direct_chat._load_voice_state", return_value={"enabled": False, "speaker": "Ana Florence", "speaker_wav": ""})
    @patch.object(direct_chat, "_STT_MANAGER")
    def test_set_voice_enabled_routes_stt_manager(self, mock_manager, _mock_load, _mock_save) -> None:
        direct_chat._set_voice_enabled(True, session_id="sess_a")
        mock_manager.enable.assert_called_once_with(session_id="sess_a")

        direct_chat._set_voice_enabled(False, session_id="sess_a")
        mock_manager.disable.assert_called_once()

    @patch("openclaw_direct_chat._save_voice_state")
    @patch("openclaw_direct_chat._load_voice_state", return_value={"enabled": False, "speaker": "Ana Florence", "speaker_wav": ""})
    @patch.object(direct_chat, "_STT_MANAGER")
    def test_set_voice_enabled_ignores_stt_start_errors(self, mock_manager, _mock_load, _mock_save) -> None:
        mock_manager.enable.side_effect = RuntimeError("boom")
        # Must not raise: TTS path should remain unaffected even if STT init fails.
        buf = io.StringIO()
        with redirect_stderr(buf), redirect_stdout(buf):
            direct_chat._set_voice_enabled(True, session_id="sess_a")

    def test_stt_manager_poll_requires_owner_and_drains_queue(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._queue.put({"text": "pausa", "ts": 1.0})
        mgr._queue.put({"text": "continuar", "ts": 2.0})

        self.assertEqual(mgr.poll("sess_b", limit=5), [])

        prev_tts_is_playing = direct_chat._tts_is_playing
        direct_chat._tts_is_playing = lambda: False  # type: ignore
        items = mgr.poll("sess_a", limit=5)
        direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
        self.assertEqual(len(items), 2)
        self.assertEqual(str(items[0].get("cmd", "")), "pause")
        self.assertEqual(str(items[1].get("cmd", "")), "continue")
        self.assertEqual(mgr.poll("sess_a", limit=5), [])
        mgr.disable()

    def test_stt_manager_poll_filters_non_voice_commands_while_tts_playing(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._queue.put({"text": "comentario normal", "ts": 1.0})
        mgr._queue.put({"text": "detenete", "ts": 2.0})
        mgr._queue.put({"text": "continuar", "ts": 3.0})
        mgr._queue.put({"text": "repetir", "ts": 4.0})
        prev_tts_is_playing = direct_chat._tts_is_playing
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            items = mgr.poll("sess_a", limit=5)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
        texts = [str(i.get("text", "")).strip().lower() for i in items]
        self.assertEqual(texts, ["detenete", "continuar", "repetir"])
        mgr.disable()

    def test_voice_command_kind(self) -> None:
        self.assertEqual(direct_chat._voice_command_kind("pausa lectura"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("continuar"), "continue")
        self.assertEqual(direct_chat._voice_command_kind("repetir"), "repeat")
        self.assertEqual(direct_chat._voice_command_kind("frase libre"), "")

    def test_tts_is_playing_uses_event_proc_and_guard_window(self) -> None:
        prev_last = direct_chat._TTS_LAST_ACTIVITY_MONO
        prev_proc = direct_chat._TTS_PLAYBACK_PROC
        prev_event = direct_chat._TTS_PLAYING_EVENT.is_set()
        try:
            direct_chat._TTS_PLAYING_EVENT.set()
            self.assertTrue(direct_chat._tts_is_playing())

            direct_chat._TTS_PLAYING_EVENT.clear()
            with direct_chat._TTS_STREAM_LOCK:
                direct_chat._TTS_PLAYBACK_PROC = object()
            self.assertTrue(direct_chat._tts_is_playing())

            with direct_chat._TTS_STREAM_LOCK:
                direct_chat._TTS_PLAYBACK_PROC = None
            direct_chat._TTS_LAST_ACTIVITY_MONO = time.monotonic()
            self.assertTrue(direct_chat._tts_is_playing())

            direct_chat._TTS_LAST_ACTIVITY_MONO = time.monotonic() - (direct_chat._TTS_ECHO_GUARD_SEC + 1.0)
            self.assertFalse(direct_chat._tts_is_playing())
        finally:
            with direct_chat._TTS_STREAM_LOCK:
                direct_chat._TTS_PLAYBACK_PROC = prev_proc
            direct_chat._TTS_LAST_ACTIVITY_MONO = prev_last
            if prev_event:
                direct_chat._TTS_PLAYING_EVENT.set()
            else:
                direct_chat._TTS_PLAYING_EVENT.clear()

    def test_stt_manager_status_reports_runtime(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
            mgr._last_error = ""
        status = mgr.status()
        self.assertTrue(status.get("stt_enabled"))
        self.assertTrue(status.get("stt_running"))
        self.assertEqual(status.get("stt_owner_session_id"), "sess_a")
        mgr.disable()

    @patch("openclaw_direct_chat._set_voice_status")
    @patch("openclaw_direct_chat._stop_playback_process")
    def test_request_tts_stop_sets_event_and_updates_bargein_stats(self, mock_stop_playback, mock_set_voice_status) -> None:
        prev_stop_event = direct_chat._TTS_STOP_EVENT
        prev_stream = direct_chat._TTS_PLAYING_STREAM_ID
        prev_stats = dict(direct_chat._BARGEIN_STATS)
        try:
            direct_chat._TTS_STOP_EVENT = direct_chat.threading.Event()
            direct_chat._TTS_PLAYING_STREAM_ID = 77
            direct_chat._BARGEIN_STATS = {"count": 0, "last_ts": 0.0, "last_keyword": "", "last_detail": "not_started"}
            direct_chat._request_tts_stop(reason="barge_in_triggered", keyword="detenete")
            self.assertTrue(direct_chat._TTS_STOP_EVENT.is_set())
            st = direct_chat._bargein_status()
            self.assertEqual(int(st.get("barge_in_count", 0)), 1)
            self.assertEqual(str(st.get("barge_in_last_keyword", "")), "detenete")
            mock_stop_playback.assert_called_once()
            mock_set_voice_status.assert_called_once()
        finally:
            direct_chat._TTS_STOP_EVENT = prev_stop_event
            direct_chat._TTS_PLAYING_STREAM_ID = prev_stream
            direct_chat._BARGEIN_STATS = prev_stats

    @patch("openclaw_direct_chat._stop_bargein_monitor")
    @patch.object(direct_chat, "_STT_MANAGER")
    def test_sync_stt_with_voice_disable_stops_barge_monitor(self, mock_manager, mock_stop_barge) -> None:
        direct_chat._sync_stt_with_voice(enabled=False, session_id="")
        mock_stop_barge.assert_called_once()
        mock_manager.disable.assert_called_once()


if __name__ == "__main__":
    unittest.main()
