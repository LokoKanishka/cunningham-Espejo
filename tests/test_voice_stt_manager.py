import os
import io
import sys
import time
import tempfile
import unittest
from pathlib import Path
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
    def setUp(self) -> None:
        with direct_chat._VOICE_CHAT_DEDUPE_LOCK:
            direct_chat._VOICE_CHAT_DEDUPE_BY_SESSION = {}
        with direct_chat._VOICE_CHAT_PENDING_LOCK:
            direct_chat._VOICE_CHAT_PENDING_BY_SESSION = {}
        with direct_chat._UI_SESSION_HINT_LOCK:
            direct_chat._UI_LAST_SESSION_ID = ""
            direct_chat._UI_LAST_SEEN_TS = 0.0
        self._env_backup = {
            "DIRECT_CHAT_STT_BRIDGE_HISTORY_MAX": os.environ.get("DIRECT_CHAT_STT_BRIDGE_HISTORY_MAX"),
            "DIRECT_CHAT_STT_BRIDGE_ALLOW_FIREFOX": os.environ.get("DIRECT_CHAT_STT_BRIDGE_ALLOW_FIREFOX"),
            "DIRECT_CHAT_STT_CAPTURE_AUTOTUNE": os.environ.get("DIRECT_CHAT_STT_CAPTURE_AUTOTUNE"),
        }

    def tearDown(self) -> None:
        for key, val in self._env_backup.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_default_voice_state_enables_stt_chat(self) -> None:
        prev = os.environ.get("DIRECT_CHAT_STT_CHAT_ENABLED")
        try:
            if "DIRECT_CHAT_STT_CHAT_ENABLED" in os.environ:
                del os.environ["DIRECT_CHAT_STT_CHAT_ENABLED"]
            st = direct_chat._default_voice_state()
            self.assertTrue(bool(st.get("stt_chat_enabled")))
        finally:
            if prev is None:
                os.environ.pop("DIRECT_CHAT_STT_CHAT_ENABLED", None)
            else:
                os.environ["DIRECT_CHAT_STT_CHAT_ENABLED"] = prev

    def test_default_voice_state_enables_barge_any(self) -> None:
        prev = os.environ.get("DIRECT_CHAT_STT_BARGE_ANY")
        try:
            os.environ.pop("DIRECT_CHAT_STT_BARGE_ANY", None)
            st = direct_chat._default_voice_state()
            self.assertTrue(bool(st.get("stt_barge_any")))
        finally:
            if prev is None:
                os.environ.pop("DIRECT_CHAT_STT_BARGE_ANY", None)
            else:
                os.environ["DIRECT_CHAT_STT_BARGE_ANY"] = prev

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

    def test_resolve_stt_device_replaces_loopback_with_physical_input(self) -> None:
        mgr = direct_chat.STTManager()
        prev_allow = os.environ.get("DIRECT_CHAT_STT_ALLOW_LOOPBACK_DEVICE")
        try:
            os.environ["DIRECT_CHAT_STT_ALLOW_LOOPBACK_DEVICE"] = "0"
            mgr.list_devices = lambda: [  # type: ignore
                {"index": 14, "name": "pulse", "default": False},
                {"index": 4, "name": "HD Pro Webcam C920: USB Audio (hw:1,0)", "default": True},
                {"index": 8, "name": "USB Audio: - (hw:4,0)", "default": False},
            ]
            out = mgr._resolve_stt_device(14)
            self.assertEqual(out, 4)
        finally:
            if prev_allow is None:
                os.environ.pop("DIRECT_CHAT_STT_ALLOW_LOOPBACK_DEVICE", None)
            else:
                os.environ["DIRECT_CHAT_STT_ALLOW_LOOPBACK_DEVICE"] = prev_allow

    def test_resolve_stt_device_keeps_non_loopback(self) -> None:
        mgr = direct_chat.STTManager()
        mgr.list_devices = lambda: [  # type: ignore
            {"index": 14, "name": "pulse", "default": False},
            {"index": 4, "name": "HD Pro Webcam C920: USB Audio (hw:1,0)", "default": True},
        ]
        out = mgr._resolve_stt_device(4)
        self.assertEqual(out, 4)

    def test_stt_manager_poll_bypasses_tts_guard_for_voice_commands(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._command_only_enabled = lambda: True  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        mgr._queue.put({"text": "hola", "ts": 1.0})
        mgr._queue.put({"text": "pausa", "ts": 2.0})
        mgr._queue.put({"text": "pauza", "ts": 3.0})
        mgr._queue.put({"text": "continuar", "ts": 4.0})
        prev_tts_is_playing = direct_chat._tts_is_playing
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            items = mgr.poll("sess_a", limit=5)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
        commands = [str(i.get("cmd", "")).strip().lower() for i in items]
        self.assertEqual(commands, ["pause", "pause", "continue"])
        self.assertTrue(all(str(i.get("kind", "")).strip().lower() == "voice_cmd" for i in items))
        self.assertTrue(all(str(i.get("source", "")).strip().lower() == "voice_cmd" for i in items))
        mgr.disable()

    def test_stt_manager_barge_any_pauses_on_speech_with_cooldown(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
            mgr._vad_active = True
            mgr._in_speech = True
            mgr._rms_current = 0.08
            mgr._silence_ms = 0
        mgr._barge_any_enabled = lambda: True  # type: ignore
        mgr._barge_any_cooldown_ms = lambda: 1200  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: True  # type: ignore

            items1 = mgr.poll("sess_a", limit=2)
            items2 = mgr.poll("sess_a", limit=2)
            with mgr._lock:
                mgr._last_barge_any_mono = time.monotonic() - 2.0
            items3 = mgr.poll("sess_a", limit=2)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual([str(i.get("cmd", "")).strip().lower() for i in items1], ["pause"])
        self.assertEqual([str(i.get("source", "")).strip().lower() for i in items1], ["voice_any"])
        self.assertEqual(items2, [])
        self.assertEqual([str(i.get("cmd", "")).strip().lower() for i in items3], ["pause"])
        self.assertEqual([str(i.get("source", "")).strip().lower() for i in items3], ["voice_any"])
        mgr.disable()

    def test_stt_manager_barge_any_pauses_outside_reader_when_tts_playing(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
            mgr._vad_active = True
            mgr._in_speech = True
            mgr._rms_current = 0.08
            mgr._silence_ms = 0
        mgr._barge_any_enabled = lambda: True  # type: ignore
        mgr._barge_any_cooldown_ms = lambda: 1200  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: False  # type: ignore
            items = mgr.poll("sess_a", limit=2)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual([str(i.get("cmd", "")).strip().lower() for i in items], ["pause"])
        self.assertEqual([str(i.get("source", "")).strip().lower() for i in items], ["voice_any"])
        mgr.disable()

    def test_stt_manager_barge_any_ignores_low_rms_outside_reader(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
            mgr._vad_active = True
            mgr._in_speech = True
            mgr._rms_current = 0.01
            mgr._silence_ms = 0
        mgr._barge_any_enabled = lambda: True  # type: ignore
        mgr._barge_any_cooldown_ms = lambda: 1200  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: False  # type: ignore
            items = mgr.poll("sess_a", limit=2)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual(items, [])
        mgr.disable()

    def test_stt_manager_barge_any_cooldown_is_silent(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
            mgr._vad_active = True
            mgr._in_speech = True
            mgr._rms_current = 0.08
            mgr._silence_ms = 0
            mgr._last_barge_any_mono = time.monotonic()
        mgr._barge_any_enabled = lambda: True  # type: ignore
        mgr._barge_any_cooldown_ms = lambda: 1200  # type: ignore
        mgr._debug_enabled = lambda: True  # type: ignore
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: True  # type: ignore
            items = mgr.poll("sess_a", limit=3)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual(items, [])
        mgr.disable()

    def test_stt_manager_filters_noise_text(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._command_only_enabled = lambda: False  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        mgr._queue.put({"text": "### 1234 ???", "ts": 1.0})
        mgr._queue.put({"text": "hola cunningham", "ts": 2.0})
        prev_tts_is_playing = direct_chat._tts_is_playing
        try:
            direct_chat._tts_is_playing = lambda: False  # type: ignore
            items = mgr.poll("sess_a", limit=6)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0].get("text", "")).strip().lower(), "hola cunningham")
        mgr.disable()

    def test_stt_manager_chat_mode_allows_non_command_outside_reader(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._command_only_enabled = lambda: True  # type: ignore
        mgr._chat_enabled = lambda: True  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        mgr._queue.put({"text": "hola", "ts": 1.0})
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: False  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: False  # type: ignore
            items = mgr.poll("sess_a", limit=4)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0].get("kind", "")).strip().lower(), "chat_text")
        self.assertEqual(str(items[0].get("source", "")).strip().lower(), "voice_chat")
        self.assertEqual(str(items[0].get("text", "")).strip().lower(), "hola")
        mgr.disable()

    def test_stt_manager_chat_mode_does_not_bypass_reader_tts_guard(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._command_only_enabled = lambda: True  # type: ignore
        mgr._chat_enabled = lambda: True  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        mgr._queue.put({"text": "hola", "ts": 1.0})
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: True  # type: ignore
            items = mgr.poll("sess_a", limit=4)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual(items, [])
        mgr.disable()

    def test_stt_manager_buffers_non_command_during_tts_and_flushes_after(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._chat_enabled = lambda: True  # type: ignore
        mgr._barge_any_enabled = lambda: True  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        mgr._queue.put({"text": "hola cunningham", "ts": 10.0})
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: False  # type: ignore
            first = mgr.poll("sess_a", limit=4)
            self.assertEqual(first, [])
            direct_chat._tts_is_playing = lambda: False  # type: ignore
            second = mgr.poll("sess_a", limit=4)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual(len(second), 1)
        self.assertEqual(str(second[0].get("kind", "")).strip().lower(), "chat_text")
        self.assertEqual(str(second[0].get("text", "")).strip().lower(), "hola cunningham")
        mgr.disable()

    def test_voice_command_kind(self) -> None:
        self.assertEqual(direct_chat._voice_command_kind("pausa lectura"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("pauza lectura"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("posa"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("poza"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("continuar"), "continue")
        self.assertEqual(direct_chat._voice_command_kind("repetir"), "repeat")
        self.assertEqual(direct_chat._voice_command_kind("que me podes leer de atras para adelante"), "")
        self.assertEqual(direct_chat._voice_command_kind("esposa"), "")
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

    def test_stt_manager_status_exposes_emit_and_chat_commit_counters(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._command_only_enabled = lambda: True  # type: ignore
        mgr._chat_enabled = lambda: True  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        mgr._on_worker_telemetry({"kind": "stt_emit", "chars": 4})
        mgr._queue.put({"text": "hola", "ts": 1.0})
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: False  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: False  # type: ignore
            items = mgr.poll("sess_a", limit=4)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0].get("kind", "")).strip().lower(), "chat_text")
        st = mgr.status()
        self.assertEqual(int(st.get("stt_emit_count", 0) or 0), 1)
        self.assertEqual(int(st.get("stt_chat_commit_total", 0) or 0), 1)
        mgr.disable()

    def test_stt_manager_barge_uses_barge_threshold_not_segment_threshold(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
            mgr._vad_active = False
            mgr._in_speech = False
            mgr._rms_current = 0.010
            mgr._silence_ms = 0
        mgr._barge_any_enabled = lambda: True  # type: ignore
        mgr._barge_any_cooldown_ms = lambda: 1200  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        mgr._voice_state = lambda: {  # type: ignore
            "stt_rms_threshold": 0.020,
            "stt_segment_rms_threshold": 0.006,
            "stt_barge_rms_threshold": 0.020,
        }
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: True  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: True  # type: ignore
            items_low = mgr.poll("sess_a", limit=2)
            with mgr._lock:
                mgr._rms_current = 0.030
            items_high = mgr.poll("sess_a", limit=2)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual(items_low, [])
        self.assertEqual([str(i.get("cmd", "")).strip().lower() for i in items_high], ["pause"])
        self.assertEqual([str(i.get("source", "")).strip().lower() for i in items_high], ["voice_any"])
        mgr.disable()

    def test_voice_chat_bridge_process_items_calls_submit_once_for_chat_text(self) -> None:
        seen = []
        prev_submit = direct_chat._voice_chat_submit_backend
        def _fake_submit(sid, text, ts=0.0):
            seen.append((sid, text, ts))
            return True
        try:
            direct_chat._voice_chat_submit_backend = _fake_submit  # type: ignore
            out = direct_chat._voice_chat_bridge_process_items(
                "sess_a",
                [
                    {"kind": "chat_text", "text": "hola", "ts": 12.5},
                    {"kind": "voice_cmd", "cmd": "pause", "text": "pausa", "ts": 12.6},
                ],
            )
        finally:
            direct_chat._voice_chat_submit_backend = prev_submit  # type: ignore
        self.assertEqual(out, 2)
        self.assertEqual(seen, [("sess_a", "hola", 12.5)])

    def test_voice_chat_bridge_process_items_merges_recent_chat_text_fragments(self) -> None:
        seen = []
        prev_submit = direct_chat._voice_chat_submit_backend
        def _fake_submit(sid, text, ts=0.0):
            seen.append((sid, text, ts))
            return True
        try:
            direct_chat._voice_chat_submit_backend = _fake_submit  # type: ignore
            out = direct_chat._voice_chat_bridge_process_items(
                "sess_a",
                [
                    {"kind": "chat_text", "text": "hola uno", "ts": 1.0},
                    {"kind": "chat_text", "text": "hola dos", "ts": 2.0},
                    {"kind": "chat_text", "text": "hola tres", "ts": 3.0},
                ],
            )
        finally:
            direct_chat._voice_chat_submit_backend = prev_submit  # type: ignore
        self.assertEqual(out, 1)
        self.assertEqual(seen, [("sess_a", "hola uno hola dos hola tres", 3.0)])

    def test_voice_chat_bridge_process_items_keeps_short_tail_to_complete_phrase(self) -> None:
        seen = []
        prev_submit = direct_chat._voice_chat_submit_backend

        def _fake_submit(sid, text, ts=0.0):
            seen.append((sid, text, ts))
            return True

        try:
            direct_chat._voice_chat_submit_backend = _fake_submit  # type: ignore
            out = direct_chat._voice_chat_bridge_process_items(
                "sess_a",
                [
                    {"kind": "chat_text", "text": "hoy del conflicto entre iran y estados", "ts": 10.0},
                    {"kind": "chat_text", "text": "unidos", "ts": 10.4},
                ],
            )
        finally:
            direct_chat._voice_chat_submit_backend = prev_submit  # type: ignore
        self.assertEqual(out, 1)
        self.assertEqual(seen, [("sess_a", "hoy del conflicto entre iran y estados unidos", 10.4)])

    def test_voice_chat_bridge_waits_until_silence_before_submit(self) -> None:
        seen = []
        prev_submit = direct_chat._voice_chat_submit_backend
        prev_status = direct_chat._STT_MANAGER.status

        state = {"in_speech": True, "silence_ms": 0}

        def _fake_submit(sid, text, ts=0.0):
            seen.append((sid, text, ts))
            return True

        def _fake_status():
            return {
                "stt_running": True,
                "stt_enabled": True,
                "stt_chat_enabled": True,
                "stt_owner_session_id": "sess_a",
                "stt_in_speech": bool(state["in_speech"]),
                "stt_vad_active": bool(state["in_speech"]),
                "stt_silence_ms": int(state["silence_ms"]),
            }

        prev_settle = os.environ.get("DIRECT_CHAT_STT_BRIDGE_COMMIT_SETTLE_MS")
        prev_sil = os.environ.get("DIRECT_CHAT_STT_BRIDGE_MIN_SILENCE_MS")
        try:
            os.environ["DIRECT_CHAT_STT_BRIDGE_COMMIT_SETTLE_MS"] = "20"
            os.environ["DIRECT_CHAT_STT_BRIDGE_MIN_SILENCE_MS"] = "40"
            direct_chat._voice_chat_submit_backend = _fake_submit  # type: ignore
            direct_chat._STT_MANAGER.status = _fake_status  # type: ignore
            out1 = direct_chat._voice_chat_bridge_process_items(
                "sess_a",
                [{"kind": "chat_text", "text": "hoy del conflicto entre iran y estados", "ts": 1.0}],
            )
            self.assertEqual(out1, 0)
            self.assertEqual(seen, [])
            time.sleep(0.03)
            out2 = direct_chat._voice_chat_bridge_process_items("sess_a", [])
            self.assertEqual(out2, 0)
            self.assertEqual(seen, [])
            state["in_speech"] = False
            state["silence_ms"] = 260
            out3 = direct_chat._voice_chat_bridge_process_items(
                "sess_a",
                [{"kind": "chat_text", "text": "unidos", "ts": 1.2}],
            )
            self.assertEqual(out3, 0)
            time.sleep(0.14)
            out4 = direct_chat._voice_chat_bridge_process_items("sess_a", [])
            self.assertEqual(out4, 1)
        finally:
            direct_chat._voice_chat_submit_backend = prev_submit  # type: ignore
            direct_chat._STT_MANAGER.status = prev_status  # type: ignore
            if prev_settle is None:
                os.environ.pop("DIRECT_CHAT_STT_BRIDGE_COMMIT_SETTLE_MS", None)
            else:
                os.environ["DIRECT_CHAT_STT_BRIDGE_COMMIT_SETTLE_MS"] = prev_settle
            if prev_sil is None:
                os.environ.pop("DIRECT_CHAT_STT_BRIDGE_MIN_SILENCE_MS", None)
            else:
                os.environ["DIRECT_CHAT_STT_BRIDGE_MIN_SILENCE_MS"] = prev_sil
        self.assertEqual(seen, [("sess_a", "hoy del conflicto entre iran y estados unidos", 1.2)])

    def test_voice_chat_bridge_process_items_pauses_tts_for_voice_any_command(self) -> None:
        pauses = []
        adopted = []
        prev_pause = direct_chat._apply_voice_pause_interrupt
        prev_recent_ui = direct_chat._recent_ui_session_id
        prev_claim = direct_chat._STT_MANAGER.claim_owner

        def _fake_pause(sid, source="voice_cmd", keyword=""):
            pauses.append((sid, source, keyword))
            return True

        def _fake_claim(sid):
            adopted.append(sid)
            return None

        try:
            direct_chat._apply_voice_pause_interrupt = _fake_pause  # type: ignore
            direct_chat._recent_ui_session_id = lambda: "ui_sess"  # type: ignore
            direct_chat._STT_MANAGER.claim_owner = _fake_claim  # type: ignore
            out = direct_chat._voice_chat_bridge_process_items(
                "owner_sess",
                [{"kind": "voice_cmd", "cmd": "pause", "text": "hola", "source": "voice_any", "ts": 1.0}],
            )
        finally:
            direct_chat._apply_voice_pause_interrupt = prev_pause  # type: ignore
            direct_chat._recent_ui_session_id = prev_recent_ui  # type: ignore
            direct_chat._STT_MANAGER.claim_owner = prev_claim  # type: ignore
        self.assertEqual(out, 1)
        self.assertEqual(pauses, [("ui_sess", "voice_any", "hola")])
        self.assertEqual(adopted, ["ui_sess"])

    def test_voice_chat_bridge_prefers_recent_ui_session_and_adopts_owner(self) -> None:
        seen = []
        adopted = []
        prev_submit = direct_chat._voice_chat_submit_backend
        prev_claim = direct_chat._STT_MANAGER.claim_owner

        def _fake_submit(sid, text, ts=0.0):
            seen.append((sid, text, ts))
            return True

        def _fake_claim(sid):
            adopted.append(sid)
            return None

        try:
            direct_chat._voice_chat_submit_backend = _fake_submit  # type: ignore
            direct_chat._STT_MANAGER.claim_owner = _fake_claim  # type: ignore
            direct_chat._mark_ui_session_active("ui_sess")
            out = direct_chat._voice_chat_bridge_process_items(
                "owner_sess",
                [{"kind": "chat_text", "text": "hola mundo", "ts": 9.25}],
            )
        finally:
            direct_chat._voice_chat_submit_backend = prev_submit  # type: ignore
            direct_chat._STT_MANAGER.claim_owner = prev_claim  # type: ignore
        self.assertEqual(out, 1)
        self.assertEqual(seen, [("ui_sess", "hola mundo", 9.25)])
        self.assertEqual(adopted, ["ui_sess"])

    def test_voice_chat_bridge_falls_back_owner_when_ui_session_hint_is_stale(self) -> None:
        seen = []
        adopted = []
        prev_submit = direct_chat._voice_chat_submit_backend
        prev_claim = direct_chat._STT_MANAGER.claim_owner

        def _fake_submit(sid, text, ts=0.0):
            seen.append((sid, text, ts))
            return True

        def _fake_claim(sid):
            adopted.append(sid)
            return None

        try:
            direct_chat._voice_chat_submit_backend = _fake_submit  # type: ignore
            direct_chat._STT_MANAGER.claim_owner = _fake_claim  # type: ignore
            direct_chat._mark_ui_session_active("ui_sess")
            with direct_chat._UI_SESSION_HINT_LOCK:
                direct_chat._UI_LAST_SEEN_TS = time.time() - 999.0
            out = direct_chat._voice_chat_bridge_process_items(
                "owner_sess",
                [{"kind": "chat_text", "text": "hola mundo", "ts": 9.25}],
            )
        finally:
            direct_chat._voice_chat_submit_backend = prev_submit  # type: ignore
            direct_chat._STT_MANAGER.claim_owner = prev_claim  # type: ignore
        self.assertEqual(out, 1)
        self.assertEqual(seen, [("owner_sess", "hola mundo", 9.25)])
        self.assertEqual(adopted, [])

    def test_voice_chat_dedupe_uses_session_ts_text(self) -> None:
        self.assertTrue(direct_chat._voice_chat_should_process("sess_a", "hola", ts=10.1))
        self.assertFalse(direct_chat._voice_chat_should_process("sess_a", "hola", ts=10.1))
        self.assertTrue(direct_chat._voice_chat_should_process("sess_a", "hola", ts=10.2))
        self.assertTrue(direct_chat._voice_chat_should_process("sess_b", "hola", ts=10.1))

    def test_voice_chat_model_payload_trims_history_for_bridge(self) -> None:
        prev_load_history = direct_chat._load_history
        prev_model_catalog = direct_chat._model_catalog
        try:
            os.environ["DIRECT_CHAT_STT_BRIDGE_HISTORY_MAX"] = "3"
            direct_chat._load_history = lambda *args, **kwargs: [  # type: ignore
                {"role": "user", "content": f"m{i}"} for i in range(7)
            ]
            direct_chat._model_catalog = lambda *args, **kwargs: {  # type: ignore
                "default_model": "openai-codex/gpt-5.1-codex-mini",
                "by_id": {"openai-codex/gpt-5.1-codex-mini": {"backend": "cloud"}},
            }
            payload = direct_chat._voice_chat_model_payload("sess_a")
        finally:
            direct_chat._load_history = prev_load_history  # type: ignore
            direct_chat._model_catalog = prev_model_catalog  # type: ignore
        hist = payload.get("history", [])
        self.assertEqual(len(hist), 3)
        self.assertEqual([it.get("content") for it in hist], ["m4", "m5", "m6"])

    def test_voice_chat_submit_backend_enables_web_tools_by_default(self) -> None:
        seen_payload = {}
        prev_voice_enabled = direct_chat._voice_enabled
        prev_bridge_enabled = direct_chat._voice_server_chat_bridge_enabled
        prev_model_payload = direct_chat._voice_chat_model_payload
        prev_requests_post = direct_chat.requests.post
        prev_http_port = direct_chat._DIRECT_CHAT_HTTP_PORT
        try:
            os.environ["DIRECT_CHAT_STT_BRIDGE_ALLOW_FIREFOX"] = "0"
            direct_chat._DIRECT_CHAT_HTTP_PORT = 8787
            direct_chat._voice_enabled = lambda: True  # type: ignore
            direct_chat._voice_server_chat_bridge_enabled = lambda: True  # type: ignore
            direct_chat._voice_chat_model_payload = lambda _sid: {  # type: ignore
                "model": "openai-codex/gpt-5.1-codex-mini",
                "model_backend": "cloud",
                "history": [],
            }

            class _Resp:
                status_code = 200

            def _fake_post(url, json=None, timeout=None):  # noqa: A002
                _ = (url, timeout)
                seen_payload.update(json or {})
                return _Resp()

            direct_chat.requests.post = _fake_post  # type: ignore
            ok = direct_chat._voice_chat_submit_backend("sess_a", "hola", ts=1.2)
        finally:
            direct_chat._voice_enabled = prev_voice_enabled  # type: ignore
            direct_chat._voice_server_chat_bridge_enabled = prev_bridge_enabled  # type: ignore
            direct_chat._voice_chat_model_payload = prev_model_payload  # type: ignore
            direct_chat.requests.post = prev_requests_post  # type: ignore
            direct_chat._DIRECT_CHAT_HTTP_PORT = prev_http_port
        self.assertTrue(ok)
        self.assertEqual(seen_payload.get("allowed_tools"), ["tts", "web_search", "web_ask"])

    def test_stt_chat_drop_reason_rules(self) -> None:
        self.assertEqual(direct_chat._stt_chat_drop_reason("suscribite", min_words_chat=2), "chat_banned_phrase")
        self.assertEqual(direct_chat._stt_chat_drop_reason("hola", min_words_chat=2), "")
        self.assertEqual(direct_chat._stt_chat_drop_reason("me escuchas", min_words_chat=2), "")
        self.assertEqual(direct_chat._stt_chat_drop_reason("eh", min_words_chat=2), "")

    def test_stt_voice_text_normalize_common_misrecognitions(self) -> None:
        self.assertEqual(direct_chat._stt_voice_text_normalize("preguntale a Hemini"), "preguntale a gemini")
        self.assertEqual(direct_chat._stt_voice_text_normalize("Puedes preguntarle a Hemini Informa"), "Puedes preguntarle a gemini")
        self.assertEqual(
            direct_chat._stt_voice_text_normalize("hoy del conflicto entre iran y esto"),
            "hoy del conflicto entre iran y eeuu",
        )
        self.assertEqual(direct_chat._stt_voice_text_normalize("siglo de vida de la maria"), "ciclo de vida de la mariposa")
        self.assertEqual(
            direct_chat._stt_voice_text_normalize("de que obra son las noticias"),
            "de que hora son las noticias",
        )

    def test_voice_chat_text_looks_incomplete_for_partial_gemini_request(self) -> None:
        self.assertTrue(direct_chat._voice_chat_text_looks_incomplete("podes preguntarle a gemini"))
        self.assertFalse(direct_chat._voice_chat_text_looks_incomplete("podes preguntarle a gemini sobre iran y eeuu"))

    def test_stt_segmentation_profile_chat_defaults_are_dictation_friendly(self) -> None:
        profile = direct_chat._stt_segmentation_profile(True)
        self.assertGreaterEqual(int(profile.get("min_speech_ms", 0) or 0), 180)
        self.assertGreaterEqual(int(profile.get("max_silence_ms", 0) or 0), 450)
        self.assertGreaterEqual(float(profile.get("max_segment_s", 0.0) or 0.0), 2.6)

    def test_voice_capture_autotune_raises_gain_and_lowers_seg_threshold(self) -> None:
        os.environ["DIRECT_CHAT_STT_CAPTURE_AUTOTUNE"] = "1"
        tuned = direct_chat._autotune_voice_capture_state(
            {
                "stt_chat_enabled": True,
                "stt_preamp_gain": 1.0,
                "stt_agc_enabled": False,
                "stt_agc_target_rms": 0.06,
                "stt_segment_rms_threshold": 0.008,
                "stt_rms_threshold": 0.02,
                "stt_min_chars": 3,
            }
        )
        self.assertGreaterEqual(float(tuned.get("stt_preamp_gain", 0.0) or 0.0), 1.8)
        self.assertTrue(bool(tuned.get("stt_agc_enabled")))
        self.assertGreaterEqual(float(tuned.get("stt_agc_target_rms", 0.0) or 0.0), 0.07)
        self.assertLessEqual(float(tuned.get("stt_segment_rms_threshold", 1.0) or 1.0), 0.0045)
        self.assertLessEqual(float(tuned.get("stt_rms_threshold", 1.0) or 1.0), 0.012)
        self.assertLessEqual(int(tuned.get("stt_min_chars", 99) or 99), 2)

    def test_stt_manager_chat_mode_filters_banned_phrase(self) -> None:
        mgr = direct_chat.STTManager()
        with mgr._lock:
            mgr._enabled = True
            mgr._owner_session_id = "sess_a"
            mgr._worker = _DummyWorker(running=True)
        mgr._command_only_enabled = lambda: True  # type: ignore
        mgr._chat_enabled = lambda: True  # type: ignore
        mgr._debug_enabled = lambda: False  # type: ignore
        mgr._queue.put({"text": "suscribite al canal", "ts": 1.0})
        prev_tts_is_playing = direct_chat._tts_is_playing
        prev_reader_target = direct_chat._reader_voice_any_barge_target_active
        try:
            direct_chat._tts_is_playing = lambda: False  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = lambda _sid: False  # type: ignore
            items = mgr.poll("sess_a", limit=4)
        finally:
            direct_chat._tts_is_playing = prev_tts_is_playing  # type: ignore
            direct_chat._reader_voice_any_barge_target_active = prev_reader_target  # type: ignore
        self.assertEqual(items, [])
        st = mgr.status()
        self.assertEqual(str(st.get("match_reason", "")), "chat_banned_phrase")
        mgr.disable()

    def test_chat_events_poll_returns_incremental_items(self) -> None:
        prev_history_dir = direct_chat.HISTORY_DIR
        try:
            with tempfile.TemporaryDirectory() as td:
                direct_chat.HISTORY_DIR = Path(td)
                direct_chat.HISTORY_DIR.mkdir(parents=True, exist_ok=True)
                direct_chat._chat_events_reset("sess_poll")
                first = direct_chat._chat_events_append("sess_poll", role="user", content="hola", source="stt_voice", ts=1.0)
                second = direct_chat._chat_events_append("sess_poll", role="assistant", content="ok", source="model", ts=1.1)
                all_items = direct_chat._chat_events_poll("sess_poll", after_seq=0, limit=20)
                self.assertEqual(int(all_items.get("seq", 0) or 0), int(second.get("seq", 0) or 0))
                self.assertEqual(len(all_items.get("items", [])), 2)
                inc = direct_chat._chat_events_poll("sess_poll", after_seq=int(first.get("seq", 0) or 0), limit=20)
                self.assertEqual(len(inc.get("items", [])), 1)
                item = inc.get("items", [])[0]
                self.assertEqual(str(item.get("role", "")), "assistant")
                self.assertEqual(str(item.get("content", "")), "ok")
                self.assertEqual(str(item.get("source", "")), "model")
        finally:
            direct_chat.HISTORY_DIR = prev_history_dir

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

    @patch.object(direct_chat, "_STT_MANAGER")
    @patch("openclaw_direct_chat._save_voice_state")
    @patch(
        "openclaw_direct_chat._load_voice_state",
        return_value={
            "enabled": True,
            "speaker": "Ana Florence",
            "speaker_wav": "",
            "stt_rms_threshold": 0.012,
            "stt_segment_rms_threshold": 0.006,
            "stt_barge_rms_threshold": 0.020,
        },
    )
    def test_set_stt_runtime_config_legacy_threshold_sets_segment_and_barge(
        self, _mock_load, _mock_save, mock_manager
    ) -> None:
        out = direct_chat._set_stt_runtime_config(stt_rms_threshold=0.009)
        self.assertAlmostEqual(float(out.get("stt_segment_rms_threshold", 0.0) or 0.0), 0.009, places=4)
        self.assertAlmostEqual(float(out.get("stt_barge_rms_threshold", 0.0) or 0.0), 0.009, places=4)
        self.assertAlmostEqual(float(out.get("stt_rms_threshold", 0.0) or 0.0), 0.009, places=4)
        mock_manager.restart.assert_called_once()

    @patch.object(direct_chat, "_STT_MANAGER")
    @patch("openclaw_direct_chat._save_voice_state")
    @patch(
        "openclaw_direct_chat._load_voice_state",
        return_value={
            "enabled": True,
            "speaker": "Ana Florence",
            "speaker_wav": "",
            "stt_rms_threshold": 0.012,
            "stt_segment_rms_threshold": 0.006,
            "stt_barge_rms_threshold": 0.020,
        },
    )
    def test_set_stt_runtime_config_split_thresholds_are_independent(
        self, _mock_load, _mock_save, mock_manager
    ) -> None:
        out_segment = direct_chat._set_stt_runtime_config(stt_segment_rms_threshold=0.007)
        self.assertAlmostEqual(float(out_segment.get("stt_segment_rms_threshold", 0.0) or 0.0), 0.007, places=4)
        self.assertAlmostEqual(float(out_segment.get("stt_barge_rms_threshold", 0.0) or 0.0), 0.020, places=4)
        self.assertAlmostEqual(float(out_segment.get("stt_rms_threshold", 0.0) or 0.0), 0.012, places=4)
        out_barge = direct_chat._set_stt_runtime_config(stt_barge_rms_threshold=0.018)
        self.assertAlmostEqual(float(out_barge.get("stt_segment_rms_threshold", 0.0) or 0.0), 0.007, places=4)
        self.assertAlmostEqual(float(out_barge.get("stt_barge_rms_threshold", 0.0) or 0.0), 0.018, places=4)
        self.assertAlmostEqual(float(out_barge.get("stt_rms_threshold", 0.0) or 0.0), 0.018, places=4)
        self.assertEqual(mock_manager.restart.call_count, 2)

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

    @patch("openclaw_direct_chat._load_voice_state", return_value={"enabled": False, "stt_chat_enabled": False})
    @patch("openclaw_direct_chat._stop_bargein_monitor")
    @patch.object(direct_chat, "_STT_MANAGER")
    def test_sync_stt_with_voice_disable_stops_barge_monitor(self, mock_manager, mock_stop_barge, _mock_load) -> None:
        direct_chat._sync_stt_with_voice(enabled=False, session_id="")
        mock_stop_barge.assert_called_once()
        mock_manager.disable.assert_called_once()

    @patch("openclaw_direct_chat._load_voice_state", return_value={"enabled": False, "stt_chat_enabled": True})
    @patch.object(direct_chat, "_STT_MANAGER")
    def test_sync_stt_with_voice_keeps_stt_on_when_chat_enabled(self, mock_manager, _mock_load) -> None:
        direct_chat._sync_stt_with_voice(enabled=False, session_id="sess_a")
        mock_manager.enable.assert_called_once_with(session_id="sess_a")
        mock_manager.disable.assert_not_called()


if __name__ == "__main__":
    unittest.main()
