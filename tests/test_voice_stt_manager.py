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

    def test_voice_command_kind(self) -> None:
        self.assertEqual(direct_chat._voice_command_kind("pausa lectura"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("pauza lectura"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("posa"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("poza"), "pause")
        self.assertEqual(direct_chat._voice_command_kind("continuar"), "continue")
        self.assertEqual(direct_chat._voice_command_kind("repetir"), "repeat")
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
        self.assertEqual(out, 1)
        self.assertEqual(seen, [("sess_a", "hola", 12.5)])

    def test_voice_chat_dedupe_uses_session_ts_text(self) -> None:
        self.assertTrue(direct_chat._voice_chat_should_process("sess_a", "hola", ts=10.1))
        self.assertFalse(direct_chat._voice_chat_should_process("sess_a", "hola", ts=10.1))
        self.assertTrue(direct_chat._voice_chat_should_process("sess_a", "hola", ts=10.2))
        self.assertTrue(direct_chat._voice_chat_should_process("sess_b", "hola", ts=10.1))

    def test_stt_chat_drop_reason_rules(self) -> None:
        self.assertEqual(direct_chat._stt_chat_drop_reason("suscribite", min_words_chat=2), "chat_banned_phrase")
        self.assertEqual(direct_chat._stt_chat_drop_reason("hola", min_words_chat=2), "")
        self.assertEqual(direct_chat._stt_chat_drop_reason("me escuchas", min_words_chat=2), "")
        self.assertEqual(direct_chat._stt_chat_drop_reason("eh", min_words_chat=2), "chat_too_few_words")

    def test_stt_segmentation_profile_chat_defaults_are_dictation_friendly(self) -> None:
        profile = direct_chat._stt_segmentation_profile(True)
        self.assertGreaterEqual(int(profile.get("min_speech_ms", 0) or 0), 250)
        self.assertGreaterEqual(int(profile.get("max_silence_ms", 0) or 0), 600)
        self.assertGreaterEqual(float(profile.get("max_segment_s", 0.0) or 0.0), 3.5)

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

    @patch("openclaw_direct_chat._stop_bargein_monitor")
    @patch.object(direct_chat, "_STT_MANAGER")
    def test_sync_stt_with_voice_disable_stops_barge_monitor(self, mock_manager, mock_stop_barge) -> None:
        direct_chat._sync_stt_with_voice(enabled=False, session_id="")
        mock_stop_barge.assert_called_once()
        mock_manager.disable.assert_called_once()


if __name__ == "__main__":
    unittest.main()
