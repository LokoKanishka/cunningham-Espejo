import os
import sys
import time
import unittest
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
        direct_chat._set_voice_enabled(True, session_id="sess_a")

    def test_stt_manager_poll_requires_owner_and_drains_queue(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._queue.put({"text": "hola", "ts": 1.0})
        mgr._queue.put({"text": "mundo", "ts": 2.0})

        self.assertEqual(mgr.poll("sess_b", limit=5), [])

        items = mgr.poll("sess_a", limit=5)
        self.assertEqual(len(items), 2)
        self.assertEqual(mgr.poll("sess_a", limit=5), [])
        mgr.disable()

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


if __name__ == "__main__":
    unittest.main()
