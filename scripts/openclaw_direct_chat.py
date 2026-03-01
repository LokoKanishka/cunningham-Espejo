#!/usr/bin/env python3
import atexit
import argparse
import configparser
import fcntl
import hashlib
import html
import json
import os
import queue
import re
import socket
import sqlite3
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from datetime import datetime, timezone

import requests

from molbot_direct_chat import desktop_ops, web_ask, web_search
from molbot_direct_chat.reader_ui_html import READER_HTML
from molbot_direct_chat.ui_html import HTML as UI_HTML
from molbot_direct_chat.util import extract_url as _extract_url
from molbot_direct_chat.util import normalize_text as _normalize_text
from molbot_direct_chat.util import safe_session_id as _safe_session_id

_VRAM_CACHE = {"ts": 0.0, "data": None}
_MODEL_CATALOG_CACHE = {"ts": 0.0, "data": None}


HISTORY_DIR = Path.home() / ".openclaw" / "direct_chat_histories"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_CONFIG_PATH = Path.home() / ".openclaw" / "direct_chat_browser_profiles.json"
DIRECT_CHAT_ENV_PATH = Path(os.environ.get("OPENCLAW_DIRECT_CHAT_ENV", str(Path.home() / ".openclaw" / "direct_chat.env")))
GUARDRAIL_SCRIPT_PATH = Path(__file__).resolve().parent / "guardrail_check.sh"

SITE_ALIASES = {
    "chatgpt": "https://chatgpt.com/",
    "chat gpt": "https://chatgpt.com/",
    "gemini": "https://gemini.google.com/app",
    "google": "https://www.google.com/",
    "youtube": "https://www.youtube.com/",
    "you tube": "https://www.youtube.com/",
    "wikipedia": "https://es.wikipedia.org/",
    "wiki": "https://es.wikipedia.org/",
    "gmail": "https://mail.google.com/",
    "mail": "https://mail.google.com/",
}

SITE_SEARCH_TEMPLATES = {
    "google": "https://www.google.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "wikipedia": "https://es.wikipedia.org/w/index.php?search={q}",
}

SITE_CANONICAL_TOKENS = {
    # Include common typos so simple "open X" doesn't fall back to the model.
    "chatgpt": ["chatgpt", "chat gpt", "chatgtp", "chat gtp"],
    "gemini": ["gemini", "gemni", "geminy", "gemin"],
    "google": ["google", "googl", "gugel"],
    "youtube": ["youtube", "you tube", "ytube", "yutub", "youtbe", "youtub"],
    "wikipedia": ["wikipedia", "wiki"],
    "gmail": ["gmail", "mail"],
}

# Defaults can be overridden in ~/.openclaw/direct_chat_browser_profiles.json
DEFAULT_BROWSER_PROFILE_CONFIG = {
    "_default": {"browser": "chrome", "profile": "diego"},
    # Keep ChatGPT/Gemini in the same logged-in Chrome profile by default.
    "chatgpt": {"browser": "chrome", "profile": "diego"},
    "gemini": {"browser": "chrome", "profile": "diego"},
    "google": {"browser": "chrome", "profile": "diego"},
    "youtube": {"browser": "chrome", "profile": "diego"},
    "wikipedia": {"browser": "chrome", "profile": "diego"},
    "gmail": {"browser": "chrome", "profile": "diego"},
}
HTML = UI_HTML


# NOTE: UI HTML moved to scripts/molbot_direct_chat/ui_html.py
# Keeping the content embedded here made this file too large to maintain.

BROWSER_WINDOWS_PATH = Path.home() / ".openclaw" / "direct_chat_opened_browser_windows.json"
BROWSER_WINDOWS_LOCK_PATH = Path.home() / ".openclaw" / ".direct_chat_opened_browser_windows.lock"
TRUSTED_DC_ANCHOR_PATH = Path.home() / ".openclaw" / "direct_chat_trusted_anchor.json"
VOICE_STATE_PATH = Path.home() / ".openclaw" / "direct_chat_voice.json"
READER_STATE_PATH = Path(
    os.environ.get("DIRECT_CHAT_READER_STATE_PATH", str(Path.home() / ".openclaw" / "reading_sessions.json"))
)
READER_LOCK_PATH = Path(
    os.environ.get("DIRECT_CHAT_READER_LOCK_PATH", str(Path.home() / ".openclaw" / ".reading_sessions.lock"))
)
READER_LIBRARY_DIR = Path(os.environ.get("LUCY_LIBRARY_DIR", str(Path.home() / "Lucy_Library")))
READER_LIBRARY_INDEX_PATH = Path(
    os.environ.get("DIRECT_CHAT_READER_LIBRARY_INDEX_PATH", str(Path.home() / ".openclaw" / "reader_library_index.json"))
)
READER_LIBRARY_LOCK_PATH = Path(
    os.environ.get("DIRECT_CHAT_READER_LIBRARY_LOCK_PATH", str(Path.home() / ".openclaw" / ".reader_library_index.lock"))
)
READER_CACHE_DIR = Path(
    os.environ.get("DIRECT_CHAT_READER_CACHE_DIR", str(Path.home() / ".openclaw" / "reader_cache"))
)

_VOICE_LOCK = threading.Lock()
_VOICE_LAST_STATUS = {"ok": None, "detail": "not_started", "ts": 0.0, "stream_id": 0}
_TTS_PLAYBACK_PROC = None
_TTS_STREAM_LOCK = threading.Lock()
_TTS_STREAM_ID = 0
_TTS_STOP_EVENT = threading.Event()
_TTS_ACTIVE_QUEUE = None
_TTS_PLAYING_EVENT = threading.Event()
_TTS_PLAYING_STREAM_ID = 0
_TTS_LAST_ACTIVITY_MONO = 0.0
_TTS_ECHO_GUARD_SEC = 0.8
_TTS_STOP_REASON_BY_STREAM: dict[int, str] = {}
_TTS_PLAYBACK_MONO_BY_STREAM: dict[int, float] = {}
_BARGEIN_LOCK = threading.Lock()
_BARGEIN_MONITOR = None
_BARGEIN_STATS = {"count": 0, "last_ts": 0.0, "last_keyword": "", "last_detail": "not_started"}
_READER_AUTOCOMMIT_LOCK = threading.Lock()
_READER_AUTOCOMMIT_BY_STREAM: dict[int, dict] = {}
_TTS_HEALTH_LOCK = threading.Lock()
_TTS_HEALTH_CACHE = {
    "ok": None,
    "detail": "not_checked",
    "checked_ts": 0.0,
    "backend": "alltalk",
    "base_url": "",
    "health_path": "",
    "timeout_s": 0.0,
}
_DIRECT_CHAT_HTTP_HOST = "127.0.0.1"
_DIRECT_CHAT_HTTP_PORT = 0
_VOICE_CHAT_BRIDGE_LOCK = threading.Lock()
_VOICE_CHAT_BRIDGE_THREAD: threading.Thread | None = None
_VOICE_CHAT_BRIDGE_STOP = threading.Event()
_VOICE_CHAT_DEDUPE_LOCK = threading.Lock()
_VOICE_CHAT_DEDUPE_BY_SESSION: dict[str, dict[str, float]] = {}
_VOICE_CHAT_PENDING_LOCK = threading.Lock()
_VOICE_CHAT_PENDING_BY_SESSION: dict[str, dict[str, float | str]] = {}
_CHAT_EVENTS_LOCK = threading.Lock()
_UI_SESSION_HINT_LOCK = threading.Lock()
_UI_LAST_SESSION_ID = ""
_UI_LAST_SEEN_TS = 0.0
_STT_CHAT_BANNED_RE = re.compile(r"\bsuscrib\w*\b|\bsubscribe\b", flags=re.IGNORECASE)
_STT_CHAT_ALLOW_SHORT = {"hola", "ok", "si", "sí", "no", "eh", "ey", "aca", "acá", "dale", "listo", "bueno"}


def _bargein_config() -> dict:
    state = _load_voice_state()
    rms_threshold = _stt_barge_rms_threshold_from_state(state)
    return {
        "enabled": _env_flag("DIRECT_CHAT_BARGEIN_ENABLED", True),
        "vad_interrupt_enabled": _env_flag("DIRECT_CHAT_BARGEIN_VAD_INTERRUPT_ENABLED", False),
        "sample_rate": max(8000, _int_env("DIRECT_CHAT_BARGEIN_SAMPLE_RATE", 16000)),
        "frame_ms": max(10, min(30, _int_env("DIRECT_CHAT_BARGEIN_FRAME_MS", 30))),
        "vad_mode": max(0, min(3, _int_env("DIRECT_CHAT_BARGEIN_VAD_MODE", 1))),
        "min_voice_frames": max(2, _int_env("DIRECT_CHAT_BARGEIN_MIN_VOICE_FRAMES", 4)),
        "rms_threshold": max(0.001, float(rms_threshold)),
        "cooldown_sec": max(0.2, float(os.environ.get("DIRECT_CHAT_BARGEIN_COOLDOWN_SEC", "1.5"))),
    }


def _tts_touch() -> None:
    global _TTS_LAST_ACTIVITY_MONO
    _TTS_LAST_ACTIVITY_MONO = time.monotonic()


def _tts_is_playing() -> bool:
    if _TTS_PLAYING_EVENT.is_set():
        return True
    with _TTS_STREAM_LOCK:
        if _TTS_PLAYBACK_PROC is not None:
            return True
    return (time.monotonic() - _TTS_LAST_ACTIVITY_MONO) < _TTS_ECHO_GUARD_SEC


def _tts_playback_state() -> dict:
    now_mono = time.monotonic()
    with _TTS_STREAM_LOCK:
        stream_id = int(_TTS_PLAYING_STREAM_ID or 0)
        started_mono = float(_TTS_PLAYBACK_MONO_BY_STREAM.get(stream_id, 0.0) or 0.0) if stream_id > 0 else 0.0
    elapsed_ms = 0
    if stream_id > 0 and started_mono > 0.0:
        elapsed_ms = int(max(0.0, (now_mono - started_mono) * 1000.0))
    return {
        "tts_playing_stream_id": int(stream_id),
        "tts_playback_elapsed_ms": int(elapsed_ms),
    }


def _bargein_status() -> dict:
    cfg = _bargein_config()
    with _BARGEIN_LOCK:
        return {
            "barge_in_mode": "speech",
            "barge_in_count": int(_BARGEIN_STATS.get("count", 0) or 0),
            "barge_in_last_ts": float(_BARGEIN_STATS.get("last_ts", 0.0) or 0.0),
            "barge_in_last_keyword": str(_BARGEIN_STATS.get("last_keyword", "")),
            "barge_in_last_detail": str(_BARGEIN_STATS.get("last_detail", "")),
            "barge_in_config": cfg,
        }


def _bargein_mark(detail: str, keyword: str = "") -> None:
    with _BARGEIN_LOCK:
        _BARGEIN_STATS["last_ts"] = time.time()
        _BARGEIN_STATS["last_detail"] = str(detail)
        if keyword:
            _BARGEIN_STATS["last_keyword"] = str(keyword)
        if str(detail).startswith("triggered"):
            _BARGEIN_STATS["count"] = int(_BARGEIN_STATS.get("count", 0) or 0) + 1


def _request_tts_stop(
    reason: str = "barge_in",
    keyword: str = "",
    detail: str = "",
    session_id: str = "",
    offset_hint: int | None = None,
    playback_ms: float | None = None,
) -> None:
    interrupt_reason = str(reason or "").strip() or "reader_user_interrupt"
    if interrupt_reason == "barge_in":
        interrupt_reason = "barge_in_triggered"
    _bargein_mark(detail or "triggered", keyword=keyword)
    _tts_touch()
    stream_id = 0
    with _TTS_STREAM_LOCK:
        stream_id = int(_TTS_PLAYING_STREAM_ID or 0)
        if stream_id > 0:
            _TTS_STOP_REASON_BY_STREAM[int(stream_id)] = interrupt_reason
        _TTS_STOP_EVENT.set()
    _reader_mark_barge_in_from_stream(
        stream_id=stream_id,
        reason=interrupt_reason,
        keyword=keyword,
        detail=detail or "triggered",
        session_id=session_id,
        offset_hint=offset_hint,
        playback_ms=playback_ms,
    )
    _stop_playback_process()
    _set_voice_status(stream_id, False, interrupt_reason)


def _reader_autocommit_register(
    stream_id: int,
    session_id: str,
    chunk_id: str,
    chunk_index: int,
    text_len: int = 0,
    start_offset_chars: int = 0,
) -> None:
    sid = _safe_session_id(session_id)
    cid = str(chunk_id or "").strip()
    if stream_id <= 0 or not sid or not cid:
        return
    with _READER_AUTOCOMMIT_LOCK:
        _READER_AUTOCOMMIT_BY_STREAM[int(stream_id)] = {
            "session_id": sid,
            "chunk_id": cid,
            "chunk_index": int(chunk_index),
            "created_mono": time.monotonic(),
            "text_len": max(0, int(text_len)),
            "start_offset_chars": max(0, int(start_offset_chars)),
        }
    max_wait = _reader_tts_end_max_wait_sec(text_len=max(0, int(text_len)))
    th = threading.Thread(target=_reader_autocommit_timeout_worker, args=(int(stream_id), float(max_wait)), daemon=True)
    th.start()


def _reader_tts_end_max_wait_sec(text_len: int = 0) -> float:
    min_wait = max(0.5, float(os.environ.get("DIRECT_CHAT_TTS_END_MIN_WAIT_SEC", "20")))
    base = max(min_wait, float(os.environ.get("DIRECT_CHAT_TTS_END_MAX_WAIT_SEC", "90")))
    cps = max(4.0, float(os.environ.get("DIRECT_CHAT_TTS_EST_CHARS_PER_SEC", "16")))
    buffer_sec = max(2.0, float(os.environ.get("DIRECT_CHAT_TTS_END_BUFFER_SEC", "10")))
    dynamic = max(min_wait, (max(0, int(text_len)) / cps) + buffer_sec)
    return min(300.0, max(base, dynamic))


def _is_user_tts_interrupt_detail(detail: str) -> bool:
    d = str(detail or "").strip().lower()
    if not d:
        return False
    return any(
        k in d
        for k in (
            "reader_user_barge_in",
            "reader_user_interrupt",
            "typed_interrupt",
            "voice_command",
            "barge_in_triggered",
            "barge_in",
            "playback_interrupted",
        )
    )


def _reader_should_commit_on_tts_failure(detail: str) -> bool:
    # User-initiated stops preserve pending chunk for explicit resume.
    if _is_user_tts_interrupt_detail(detail):
        return False
    return True


def _reader_commit_from_autocommit(pending: dict, reason: str) -> None:
    try:
        _READER_STORE.commit(
            str(pending.get("session_id", "default")),
            chunk_id=str(pending.get("chunk_id", "")),
            chunk_index=int(pending.get("chunk_index", 0)),
            reason=str(reason or "tts_end_autocommit")[:120],
        )
    except Exception:
        return


def _reader_autocommit_timeout_worker(stream_id: int, max_wait_sec: float) -> None:
    wait_s = max(0.1, float(max_wait_sec))
    time.sleep(wait_s)
    _reader_autocommit_finalize(
        int(stream_id),
        ok=False,
        detail="tts_end_timeout",
        force_timeout_commit=True,
    )


def _reader_autocommit_peek(stream_id: int) -> dict | None:
    if stream_id <= 0:
        return None
    with _READER_AUTOCOMMIT_LOCK:
        pending = _READER_AUTOCOMMIT_BY_STREAM.get(int(stream_id))
        return dict(pending) if isinstance(pending, dict) else None


def _reader_mark_barge_in_from_stream(
    stream_id: int,
    reason: str,
    detail: str,
    keyword: str = "",
    session_id: str = "",
    offset_hint: int | None = None,
    playback_ms: float | None = None,
) -> None:
    sid = _safe_session_id(session_id) if session_id else ""
    pending = _reader_autocommit_peek(stream_id)
    if (not sid) and isinstance(pending, dict):
        sid = _safe_session_id(str(pending.get("session_id", "")))
    if not sid:
        return
    pm = playback_ms
    if pm is None and stream_id > 0:
        try:
            with _TTS_STREAM_LOCK:
                started_mono = float(_TTS_PLAYBACK_MONO_BY_STREAM.get(int(stream_id), 0.0) or 0.0)
            if started_mono > 0.0:
                pm = max(0.0, (time.monotonic() - started_mono) * 1000.0)
        except Exception:
            pm = None
    if pm is None and isinstance(pending, dict):
        created_mono = float(pending.get("created_mono", 0.0) or 0.0)
        if created_mono > 0.0:
            pm = max(0.0, (time.monotonic() - created_mono) * 1000.0)
    try:
        _READER_STORE.mark_barge_in(
            sid,
            detail=str(detail or reason),
            keyword=keyword,
            offset_hint=offset_hint,
            playback_ms=pm,
        )
    except Exception:
        return


def _reader_autocommit_finalize(
    stream_id: int,
    ok: bool | None,
    detail: str = "",
    force_timeout_commit: bool = False,
) -> None:
    if stream_id <= 0 or ok is None:
        return
    with _READER_AUTOCOMMIT_LOCK:
        pending = _READER_AUTOCOMMIT_BY_STREAM.pop(int(stream_id), None)
    if not pending:
        return
    if ok is True:
        _reader_commit_from_autocommit(pending, reason="tts_end_autocommit")
        return
    if force_timeout_commit:
        _reader_commit_from_autocommit(pending, reason="tts_end_timeout")
        return
    if _reader_should_commit_on_tts_failure(detail):
        _reader_commit_from_autocommit(pending, reason=f"tts_end_failed:{str(detail or 'unknown')[:80]}")


class _BargeInMonitor:
    def __init__(self, stream_id: int, stop_event: threading.Event):
        self.stream_id = int(stream_id)
        self.stop_event = stop_event
        self._stop = threading.Event()
        self._th = None

    @staticmethod
    def _enabled() -> bool:
        cfg = _bargein_config()
        if not bool(cfg.get("enabled", True)):
            return False
        if not bool(cfg.get("vad_interrupt_enabled", False)):
            return False
        state = _load_voice_state()
        if bool(state.get("stt_command_only", True)):
            return False
        return True

    @staticmethod
    def _keywords() -> list[str]:
        raw = str(os.environ.get("DIRECT_CHAT_BARGEIN_KEYWORDS", "detenete,detente,para,pará,stop")).strip()
        parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
        return parts or ["detenete"]

    def start(self) -> None:
        if not self._enabled():
            _bargein_mark("disabled")
            return
        if self._th and self._th.is_alive():
            return
        self._stop.clear()
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()

    def stop(self) -> None:
        self._stop.set()
        th = self._th
        if th:
            th.join(timeout=1.0)

    def _run(self) -> None:
        try:
            import numpy as np  # type: ignore
            import sounddevice as sd  # type: ignore
            import webrtcvad  # type: ignore
        except Exception as e:
            _bargein_mark(f"deps_unavailable:{e}")
            return

        cfg = _bargein_config()
        sample_rate = int(cfg["sample_rate"])
        frame_ms = int(cfg["frame_ms"])
        frame_samples = int(sample_rate * frame_ms / 1000)
        vad_mode = int(cfg["vad_mode"])
        min_frames = int(cfg["min_voice_frames"])
        rms_threshold = float(cfg["rms_threshold"])
        cooldown_sec = float(cfg["cooldown_sec"])
        device = str(os.environ.get("DIRECT_CHAT_BARGEIN_DEVICE", "")).strip() or None
        keywords = self._keywords()
        last_trigger_mono = 0.0
        consecutive = 0

        vad = webrtcvad.Vad(vad_mode)
        try:
            stream = sd.RawInputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocksize=frame_samples,
                device=device,
            )
        except Exception as e:
            _bargein_mark(f"stream_open_failed:{e}")
            return

        try:
            with stream:
                _bargein_mark(
                    f"monitor_started:vad={vad_mode};rms={rms_threshold:.3f};min_frames={min_frames};cooldown={cooldown_sec:.2f}"
                )
                while (not self._stop.is_set()) and (not self.stop_event.is_set()):
                    if self.stream_id != _TTS_PLAYING_STREAM_ID:
                        break
                    if not _tts_is_playing():
                        consecutive = 0
                        time.sleep(0.03)
                        continue
                    try:
                        data, overflowed = stream.read(frame_samples)
                        if overflowed:
                            pass
                    except Exception as e:
                        _bargein_mark(f"stream_read_failed:{e}")
                        break
                    if not data:
                        continue
                    try:
                        is_speech = bool(vad.is_speech(data, sample_rate))
                    except Exception:
                        is_speech = False
                    pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    if getattr(pcm, "size", 0) == 0:
                        continue
                    rms = float(np.sqrt(np.mean((pcm / 32768.0) ** 2)))
                    if is_speech and rms >= rms_threshold:
                        consecutive += 1
                    else:
                        consecutive = max(0, consecutive - 1)
                    if consecutive < min_frames:
                        continue
                    now = time.monotonic()
                    if (now - last_trigger_mono) < cooldown_sec:
                        continue
                    last_trigger_mono = now
                    keyword = keywords[0]
                    _request_tts_stop(
                        reason="barge_in_triggered",
                        keyword=keyword,
                        detail=(
                            f"triggered:vad={int(is_speech)};rms={rms:.3f};threshold={rms_threshold:.3f};"
                            f"frames={consecutive};min_frames={min_frames};cooldown={cooldown_sec:.2f}"
                        ),
                    )
                    break
        finally:
            _bargein_mark("monitor_stopped")


def _start_bargein_monitor(stream_id: int, stop_event: threading.Event) -> None:
    global _BARGEIN_MONITOR
    with _BARGEIN_LOCK:
        prev = _BARGEIN_MONITOR
        mon = _BARGEIN_MONITOR = _BargeInMonitor(stream_id=stream_id, stop_event=stop_event)
    if prev is not None:
        try:
            prev.stop()
        except Exception:
            pass
    mon.start()


def _stop_bargein_monitor() -> None:
    global _BARGEIN_MONITOR
    with _BARGEIN_LOCK:
        mon = _BARGEIN_MONITOR
        _BARGEIN_MONITOR = None
    if mon is None:
        return
    try:
        mon.stop()
    except Exception:
        return


def _load_local_env_file(path: Path) -> None:
    try:
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if "=" not in raw:
                continue
            k, v = raw.split("=", 1)
            key = k.strip()
            if not key:
                continue
            val = v.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = val
    except Exception:
        return


_load_local_env_file(DIRECT_CHAT_ENV_PATH)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "si", "sí")


def _clamp_float(raw, *, default: float, min_value: float) -> float:
    try:
        return max(float(min_value), float(raw))
    except Exception:
        return max(float(min_value), float(default))


def _stt_legacy_rms_threshold_from_state(state: dict | None = None) -> float:
    src = state if isinstance(state, dict) else {}
    env_default = _clamp_float(
        os.environ.get("DIRECT_CHAT_BARGEIN_RMS_THRESHOLD", "0.012"),
        default=0.012,
        min_value=0.001,
    )
    return _clamp_float(src.get("stt_rms_threshold", env_default), default=env_default, min_value=0.001)


def _stt_segment_rms_threshold_from_state(state: dict | None = None) -> float:
    src = state if isinstance(state, dict) else {}
    legacy = _stt_legacy_rms_threshold_from_state(src)
    if "stt_segment_rms_threshold" not in src:
        return max(0.0005, float(legacy))
    env_default = _clamp_float(
        os.environ.get("DIRECT_CHAT_STT_SEGMENT_RMS_THRESHOLD", "0.002"),
        default=0.002,
        min_value=0.0005,
    )
    return _clamp_float(src.get("stt_segment_rms_threshold", env_default), default=env_default, min_value=0.0005)


def _stt_barge_rms_threshold_from_state(state: dict | None = None) -> float:
    src = state if isinstance(state, dict) else {}
    legacy = _stt_legacy_rms_threshold_from_state(src)
    if "stt_barge_rms_threshold" not in src:
        return max(0.001, float(legacy))
    env_default = _clamp_float(
        os.environ.get("DIRECT_CHAT_STT_BARGE_RMS_THRESHOLD", str(legacy)),
        default=legacy,
        min_value=0.001,
    )
    return _clamp_float(src.get("stt_barge_rms_threshold", env_default), default=env_default, min_value=0.001)


def _default_voice_state() -> dict:
    legacy_threshold = _stt_legacy_rms_threshold_from_state({})
    state = {
        "enabled": _env_flag("DIRECT_CHAT_TTS_ENABLED_DEFAULT", True),
        "voice_owner": "chat",
        "reader_mode_active": False,
        "reader_owner_token": "",
        "speaker": str(os.environ.get("DIRECT_CHAT_TTS_SPEAKER", "Ana Florence")).strip() or "Ana Florence",
        "speaker_wav": str(os.environ.get("DIRECT_CHAT_TTS_SPEAKER_WAV", "")).strip(),
        "stt_device": str(os.environ.get("DIRECT_CHAT_STT_DEVICE", "")).strip(),
        "stt_min_chars": max(1, _int_env("DIRECT_CHAT_STT_MIN_CHARS", 2)),
        "stt_command_only": _env_flag("DIRECT_CHAT_STT_COMMAND_ONLY", True),
        "stt_chat_enabled": _env_flag("DIRECT_CHAT_STT_CHAT_ENABLED", True),
        "stt_debug": _env_flag("DIRECT_CHAT_STT_DEBUG", False),
        "stt_no_audio_timeout_sec": max(1.0, float(os.environ.get("DIRECT_CHAT_STT_NO_AUDIO_TIMEOUT_SEC", "3.0"))),
        # Legacy single threshold (kept for backward compatibility).
        "stt_rms_threshold": float(legacy_threshold),
        # New split thresholds.
        "stt_segment_rms_threshold": _clamp_float(
            os.environ.get("DIRECT_CHAT_STT_SEGMENT_RMS_THRESHOLD", "0.0015"),
            default=0.0015,
            min_value=0.0005,
        ),
        "stt_barge_rms_threshold": _clamp_float(
            os.environ.get("DIRECT_CHAT_STT_BARGE_RMS_THRESHOLD", str(legacy_threshold)),
            default=legacy_threshold,
            min_value=0.001,
        ),
        "stt_barge_any": _env_flag("DIRECT_CHAT_STT_BARGE_ANY", True),
        "stt_barge_any_cooldown_ms": max(300, _int_env("DIRECT_CHAT_STT_BARGE_ANY_COOLDOWN_MS", 1200)),
        "stt_preamp_gain": max(0.05, float(os.environ.get("DIRECT_CHAT_STT_PREAMP_GAIN", "1.8") or 1.8)),
        "stt_agc_enabled": _env_flag("DIRECT_CHAT_STT_AGC_ENABLED", True),
        "stt_agc_target_rms": max(0.01, min(0.30, float(os.environ.get("DIRECT_CHAT_STT_AGC_TARGET_RMS", "0.08") or 0.08))),
    }
    profile = _normalize_voice_mode_profile(os.environ.get("DIRECT_CHAT_VOICE_MODE_PROFILE", "experimental"))
    _apply_voice_mode_profile(state, profile)
    state["voice_mode_profile"] = profile
    return state


def _normalize_voice_owner(raw: object) -> str:
    txt = str(raw or "").strip().lower()
    if txt in ("reader", "none"):
        return txt
    return "chat"


def _normalize_voice_mode_profile(raw: object) -> str:
    txt = str(raw or "").strip().lower()
    return "stable" if txt == "stable" else "experimental"


def _apply_voice_mode_profile(state: dict, profile: str) -> None:
    if not isinstance(state, dict):
        return
    prof = _normalize_voice_mode_profile(profile)
    if prof == "stable":
        # Stable profile minimizes realtime coupling between STT, barge-in and chat bridge.
        state["stt_chat_enabled"] = False
        state["stt_barge_any"] = False
        state["stt_barge_any_cooldown_ms"] = max(1200, int(state.get("stt_barge_any_cooldown_ms", 1800) or 1800))
        state["stt_command_only"] = True
        state["stt_min_chars"] = max(2, int(state.get("stt_min_chars", 2) or 2))
    else:
        state["stt_chat_enabled"] = True
        state["stt_barge_any"] = True
        state["stt_barge_any_cooldown_ms"] = max(300, int(state.get("stt_barge_any_cooldown_ms", 1200) or 1200))
        state["stt_command_only"] = True
        state["stt_min_chars"] = max(1, int(state.get("stt_min_chars", 2) or 2))
    state["voice_mode_profile"] = prof


def _voice_mode_profile_from_state(state: dict) -> str:
    if not isinstance(state, dict):
        return "experimental"
    explicit = _normalize_voice_mode_profile(state.get("voice_mode_profile", ""))
    if str(state.get("voice_mode_profile", "")).strip():
        return explicit
    if (not bool(state.get("stt_chat_enabled", True))) and (not bool(state.get("stt_barge_any", True))):
        return "stable"
    return "experimental"


def _autotune_voice_capture_state(state: dict) -> dict:
    if not isinstance(state, dict):
        return {}
    if not _env_flag("DIRECT_CHAT_STT_CAPTURE_AUTOTUNE", True):
        return state
    if not bool(state.get("stt_chat_enabled", True)):
        return state
    try:
        state["stt_preamp_gain"] = max(1.8, min(3.0, float(state.get("stt_preamp_gain", 1.8) or 1.8)))
    except Exception:
        state["stt_preamp_gain"] = 1.8
    state["stt_agc_enabled"] = True
    try:
        state["stt_agc_target_rms"] = max(0.07, min(0.14, float(state.get("stt_agc_target_rms", 0.08) or 0.08)))
    except Exception:
        state["stt_agc_target_rms"] = 0.08
    try:
        seg_thr = max(0.0008, min(0.0045, float(state.get("stt_segment_rms_threshold", 0.002) or 0.002)))
    except Exception:
        seg_thr = 0.002
    state["stt_segment_rms_threshold"] = float(seg_thr)
    try:
        legacy_thr = max(0.001, min(0.012, float(state.get("stt_rms_threshold", 0.012) or 0.012)))
    except Exception:
        legacy_thr = 0.012
    state["stt_rms_threshold"] = float(legacy_thr)
    try:
        state["stt_min_chars"] = max(1, min(2, int(state.get("stt_min_chars", 2) or 2)))
    except Exception:
        state["stt_min_chars"] = 2
    state["stt_barge_any"] = True
    return state


def _load_voice_state() -> dict:
    state = _default_voice_state()
    try:
        if VOICE_STATE_PATH.exists():
            raw = json.loads(VOICE_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state["enabled"] = bool(raw.get("enabled", state["enabled"]))
                speaker = str(raw.get("speaker", "")).strip()
                if speaker:
                    state["speaker"] = speaker
                speaker_wav = str(raw.get("speaker_wav", "")).strip()
                if speaker_wav:
                    state["speaker_wav"] = speaker_wav
                state["stt_device"] = str(raw.get("stt_device", state.get("stt_device", ""))).strip()
                try:
                    state["stt_min_chars"] = max(1, int(raw.get("stt_min_chars", state.get("stt_min_chars", 3))))
                except Exception:
                    state["stt_min_chars"] = max(1, int(state.get("stt_min_chars", 3)))
                if "stt_command_only" in raw:
                    state["stt_command_only"] = bool(raw.get("stt_command_only"))
                if "stt_chat_enabled" in raw:
                    state["stt_chat_enabled"] = bool(raw.get("stt_chat_enabled"))
                if "stt_debug" in raw:
                    state["stt_debug"] = bool(raw.get("stt_debug"))
                try:
                    state["stt_no_audio_timeout_sec"] = max(
                        1.0, float(raw.get("stt_no_audio_timeout_sec", state.get("stt_no_audio_timeout_sec", 3.0)))
                    )
                except Exception:
                    state["stt_no_audio_timeout_sec"] = max(1.0, float(state.get("stt_no_audio_timeout_sec", 3.0)))
                try:
                    state["stt_rms_threshold"] = max(
                        0.001, float(raw.get("stt_rms_threshold", state.get("stt_rms_threshold", 0.012)))
                    )
                except Exception:
                    state["stt_rms_threshold"] = max(0.001, float(state.get("stt_rms_threshold", 0.012)))
                try:
                    if "stt_segment_rms_threshold" in raw:
                        state["stt_segment_rms_threshold"] = max(
                            0.0005,
                            float(raw.get("stt_segment_rms_threshold", state.get("stt_segment_rms_threshold", 0.002))),
                        )
                    else:
                        state["stt_segment_rms_threshold"] = max(0.0005, float(state.get("stt_rms_threshold", 0.002)))
                except Exception:
                    state["stt_segment_rms_threshold"] = max(0.0005, float(state.get("stt_rms_threshold", 0.002)))
                try:
                    if "stt_barge_rms_threshold" in raw:
                        state["stt_barge_rms_threshold"] = max(
                            0.001,
                            float(raw.get("stt_barge_rms_threshold", state.get("stt_barge_rms_threshold", 0.012))),
                        )
                    else:
                        state["stt_barge_rms_threshold"] = max(0.001, float(state.get("stt_rms_threshold", 0.012)))
                except Exception:
                    state["stt_barge_rms_threshold"] = max(0.001, float(state.get("stt_rms_threshold", 0.012)))
                if "stt_barge_any" in raw:
                    state["stt_barge_any"] = bool(raw.get("stt_barge_any"))
                try:
                    state["stt_barge_any_cooldown_ms"] = max(
                        300, int(raw.get("stt_barge_any_cooldown_ms", state.get("stt_barge_any_cooldown_ms", 1200)))
                    )
                except Exception:
                    state["stt_barge_any_cooldown_ms"] = max(300, int(state.get("stt_barge_any_cooldown_ms", 1200)))
                try:
                    state["stt_preamp_gain"] = max(0.05, float(raw.get("stt_preamp_gain", state.get("stt_preamp_gain", 1.0))))
                except Exception:
                    state["stt_preamp_gain"] = max(0.05, float(state.get("stt_preamp_gain", 1.0)))
                if "stt_agc_enabled" in raw:
                    state["stt_agc_enabled"] = bool(raw.get("stt_agc_enabled"))
                try:
                    state["stt_agc_target_rms"] = max(
                        0.01,
                        min(0.30, float(raw.get("stt_agc_target_rms", state.get("stt_agc_target_rms", 0.06)))),
                    )
                except Exception:
                    state["stt_agc_target_rms"] = max(0.01, min(0.30, float(state.get("stt_agc_target_rms", 0.06))))
                if "voice_owner" in raw:
                    state["voice_owner"] = _normalize_voice_owner(raw.get("voice_owner"))
                if "reader_mode_active" in raw:
                    state["reader_mode_active"] = bool(raw.get("reader_mode_active"))
                if "reader_owner_token" in raw:
                    state["reader_owner_token"] = str(raw.get("reader_owner_token", "")).strip()[:120]
                if "voice_mode_profile" in raw:
                    _apply_voice_mode_profile(state, str(raw.get("voice_mode_profile", "")))
    except Exception:
        pass
    state = _autotune_voice_capture_state(state)
    # Safety pass for older persisted states.
    state["stt_rms_threshold"] = _stt_legacy_rms_threshold_from_state(state)
    state["stt_segment_rms_threshold"] = _stt_segment_rms_threshold_from_state(state)
    state["stt_barge_rms_threshold"] = _stt_barge_rms_threshold_from_state(state)
    state["voice_owner"] = _normalize_voice_owner(state.get("voice_owner", "chat"))
    state["reader_mode_active"] = bool(state.get("reader_mode_active", False))
    state["reader_owner_token"] = str(state.get("reader_owner_token", "")).strip()[:120]
    state["voice_mode_profile"] = _voice_mode_profile_from_state(state)
    return state


def _save_voice_state(state: dict) -> None:
    try:
        VOICE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        VOICE_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _set_voice_enabled(enabled: bool, session_id: str = "") -> None:
    with _VOICE_LOCK:
        state = _load_voice_state()
        state["enabled"] = bool(enabled)
        _save_voice_state(state)
    should_run = bool(state.get("enabled", False) or state.get("stt_chat_enabled", False))
    _sync_stt_with_voice(enabled=bool(enabled), session_id=session_id if should_run else "")


def _voice_enabled() -> bool:
    return bool(_load_voice_state().get("enabled", False))


def _int_env(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _float_env(name: str, default: float) -> float:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _ui_session_hint_ttl_sec() -> float:
    return max(5.0, _float_env("DIRECT_CHAT_STT_UI_SESSION_HINT_TTL_SEC", 120.0))


def _mark_ui_session_active(session_id: str) -> None:
    sid = _safe_session_id(session_id or "default")
    if not sid:
        sid = "default"
    now = time.time()
    global _UI_LAST_SESSION_ID, _UI_LAST_SEEN_TS
    with _UI_SESSION_HINT_LOCK:
        _UI_LAST_SESSION_ID = sid
        _UI_LAST_SEEN_TS = now


def _ui_session_snapshot() -> tuple[str, float]:
    with _UI_SESSION_HINT_LOCK:
        sid = str(_UI_LAST_SESSION_ID or "")
        seen_ts = float(_UI_LAST_SEEN_TS or 0.0)
    if seen_ts <= 0.0:
        return sid, -1.0
    return sid, max(0.0, time.time() - seen_ts)


def _recent_ui_session_id(max_age_sec: float | None = None) -> str:
    sid, age = _ui_session_snapshot()
    if not sid or sid == "default":
        return ""
    ttl = float(max_age_sec) if isinstance(max_age_sec, (int, float)) and float(max_age_sec) > 0 else _ui_session_hint_ttl_sec()
    if age < 0.0 or age > ttl:
        return ""
    return sid


def _stt_chat_drop_reason(text: str, min_words_chat: int = 2) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return "chat_empty_text"
    if _STT_CHAT_BANNED_RE.search(normalized):
        return "chat_banned_phrase"
    tokens = [tok for tok in re.findall(r"[a-z0-9áéíóúñü]+", normalized, flags=re.IGNORECASE) if tok]
    if not tokens:
        return "chat_empty_text"
    if len(tokens) >= max(1, int(min_words_chat)):
        return ""
    if normalized in _STT_CHAT_ALLOW_SHORT:
        return ""
    return "chat_too_few_words"


def _stt_voice_text_normalize(text: str) -> str:
    out = str(text or "").strip()
    if not out:
        return ""
    # Common near-miss for "Gemini" in noisy STT outputs.
    out = re.sub(r"\b(?:hemini|jemini|gemni|geminy|gemin)\b", "gemini", out, flags=re.IGNORECASE)
    out = re.sub(r"\bgemini\s+informa\b", "gemini", out, flags=re.IGNORECASE)
    out = re.sub(r"\biran\s+y\s+esto(?:s)?\b", "iran y eeuu", out, flags=re.IGNORECASE)
    out = re.sub(r"\bsiglo\s+de\s+vida\b", "ciclo de vida", out, flags=re.IGNORECASE)
    if re.search(r"\bciclo\s+de\s+vida\b", out, flags=re.IGNORECASE):
        out = re.sub(r"\bde\s+la\s+maria\b", "de la mariposa", out, flags=re.IGNORECASE)
    # Contextual near-miss: "de que obra son ..." -> "de que hora son ..."
    out = re.sub(r"\bde\s+que\s+obra\s+(son|es)\b", r"de que hora \1", out, flags=re.IGNORECASE)
    out = re.sub(r"\bque\s+obra\s+(son|es)\b", r"que hora \1", out, flags=re.IGNORECASE)
    out = re.sub(r"\bobra\s+(son|es)\b", r"hora \1", out, flags=re.IGNORECASE)
    return out.strip()


def _stt_segmentation_profile(chat_enabled: bool) -> dict:
    if bool(chat_enabled):
        # Chat profile tuned for lower end-to-end latency while keeping basic stability.
        min_ms = max(120, _int_env("DIRECT_CHAT_STT_CHAT_MIN_SEGMENT_MS", 140))
        return {
            "min_speech_ms": int(min_ms),
            "chat_min_speech_ms": int(min_ms),
            "max_silence_ms": int(max(220, _int_env("DIRECT_CHAT_STT_CHAT_MAX_SILENCE_MS", 420))),
            "max_segment_s": float(max(1.8, _float_env("DIRECT_CHAT_STT_CHAT_MAX_SEGMENT_SEC", 3.2))),
        }
    return {
        "min_speech_ms": int(max(100, _int_env("DIRECT_CHAT_STT_MIN_SPEECH_MS", 180))),
        "chat_min_speech_ms": int(max(100, _int_env("DIRECT_CHAT_STT_CHAT_MIN_SPEECH_MS", 140))),
        "max_silence_ms": int(max(140, _int_env("DIRECT_CHAT_STT_MAX_SILENCE_MS", 280))),
        "max_segment_s": float(max(1.2, _float_env("DIRECT_CHAT_STT_MAX_SEGMENT_SEC", 1.8))),
    }


def _voice_command_kind(text: str) -> str:
    n = _normalize_text(text)
    if not n:
        return ""
    compact = re.sub(r"\s+", " ", n).strip()
    if compact:
        compact = re.sub(r"(.)\1{2,}", r"\1\1", compact)
    if not compact:
        return ""

    prefix = r"(?:\b(?:bueno|ok|dale|che|hola|luci|por favor|porfa|eh|ey)\b[\s,]*){0,3}"

    def _matches(pattern: str) -> bool:
        return bool(re.search(rf"^{prefix}(?:{pattern})\b", compact, flags=re.IGNORECASE))

    if _matches(r"(detenete|detente|pausa(?:\s+lectura)?|pauza|posa|poza|pausar\s+lectura|detener\s+lectura|parar\s+lectura|basta|stop(?:\s+lectura)?)"):
        return "pause"
    if _matches(r"(continuar|segui|seguir(?:\s+leyendo)?|continue|resume|reanuda(?:r)?)"):
        return "continue"
    if _matches(r"(repetir|repeti|repeat)"):
        return "repeat"

    # Fallback for clipped short utterances.
    tokens = [tok for tok in re.findall(r"[a-z0-9]+", compact) if tok]
    if len(tokens) <= 3:
        joined = " ".join(tokens)
        if joined in (
            "detenete",
            "detente",
            "pausa",
            "pauza",
            "posa",
            "poza",
            "stop",
            "basta",
            "pausa lectura",
            "detener lectura",
            "parar lectura",
        ):
            return "pause"
        if joined in ("continuar", "segui", "seguir", "continue", "resume", "reanudar"):
            return "continue"
        if joined in ("repetir", "repeti", "repeat"):
            return "repeat"
    return ""


def _is_probable_stt_noise(text: str, cmd: str = "") -> bool:
    if str(cmd or "").strip():
        return False
    n = _normalize_text(text)
    if not n:
        return True
    letters = sum(1 for ch in n if ch.isalpha())
    digits = sum(1 for ch in n if ch.isdigit())
    symbols = sum(1 for ch in n if (not ch.isalnum()) and (not ch.isspace()))
    if letters <= 0:
        return True
    if letters <= 2 and (digits + symbols) >= (letters + 2):
        return True
    compact_tokens = [re.sub(r"[^a-z0-9]+", "", tok.lower()) for tok in n.split()]
    compact_tokens = [tok for tok in compact_tokens if tok]
    if not compact_tokens:
        return True
    one_char_tokens = sum(1 for tok in compact_tokens if len(tok) <= 1)
    if len(compact_tokens) >= 3 and one_char_tokens >= len(compact_tokens):
        return True
    if symbols >= 4 and symbols > letters:
        return True
    return False


def _is_barge_in_phrase(text: str) -> bool:
    return _voice_command_kind(text) == "pause"


def _is_voice_control_phrase(text: str) -> bool:
    return bool(_voice_command_kind(text))


class STTManager:
    _RETRY_DELAYS_SEC = (2.0, 5.0, 10.0)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._worker = None
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=max(1, self._env_int("DIRECT_CHAT_STT_QUEUE_SIZE", 64)))
        self._enabled = False
        self._owner_session_id = ""
        self._last_error = ""
        self._retry_idx = 0
        self._next_retry_mono = 0.0
        self._enabled_since_mono = 0.0
        self._frames_seen = 0
        self._last_audio_ts = 0.0
        self._rms_current = 0.0
        self._vad_active = False
        self._in_speech = False
        self._vad_frames = 0
        self._vad_true_frames = 0
        self._last_segment_ms = 0
        self._silence_ms = 0
        self._effective_seg_thr = 0.0
        self._effective_seg_thr_off = 0.0
        self._effective_min_segment_ms = 0
        self._speech_hangover_ms = 0
        self._device_label = ""
        self._drop_reason = ""
        self._items_total = 0
        self._items_dropped = 0
        self._items_dropped_audio = 0
        self._items_dropped_text = 0
        self._drop_reason_counts: dict[str, int] = {}
        self._stt_emit_count = 0
        self._voice_text_committed = 0
        self._stt_chat_commit_total = 0
        self._last_item_ts = 0.0
        self._last_raw_text = ""
        self._last_norm_text = ""
        self._last_matched_cmd = ""
        self._last_match_reason = ""
        self._last_match_ts = 0.0
        self._last_barge_any_mono = 0.0
        self._pending_chat_after_tts: dict | None = None

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = str(os.environ.get(name, "")).strip()
        if not raw:
            return int(default)
        try:
            return int(raw)
        except Exception:
            return int(default)

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        raw = str(os.environ.get(name, "")).strip()
        if not raw:
            return float(default)
        try:
            return float(raw)
        except Exception:
            return float(default)

    def _log(self, msg: str) -> None:
        try:
            print(msg, file=sys.stderr)
        except Exception:
            return

    def _clear_queue_locked(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            except Exception:
                return

    def _should_listen(self) -> bool:
        with self._lock:
            enabled = bool(self._enabled)
        if not enabled:
            return False
        if _tts_is_playing():
            return _env_flag("DIRECT_CHAT_STT_ALLOW_DURING_TTS", True)
        return True

    @staticmethod
    def _parse_device(raw) -> int | str | None:
        s = str(raw or "").strip()
        if not s:
            return None
        if re.fullmatch(r"-?\d+", s):
            try:
                return int(s)
            except Exception:
                return s
        return s

    def _voice_state(self) -> dict:
        try:
            out = _load_voice_state()
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}

    def _selected_stt_device(self):
        state = self._voice_state()
        raw = str(state.get("stt_device", "")).strip()
        if not raw:
            raw = str(os.environ.get("DIRECT_CHAT_STT_DEVICE", "")).strip()
        return self._parse_device(raw)

    @staticmethod
    def _is_likely_loopback_device_name(name: str) -> bool:
        n = str(name or "").strip().lower()
        if not n:
            return False
        if n in ("pulse", "default", "default input", "default device"):
            return True
        markers = (
            "monitor",
            "loopback",
            "stereo mix",
            "what u hear",
            "wave out",
            "output",
        )
        return any(m in n for m in markers)

    def _resolve_stt_device(self, configured_device):
        if _env_flag("DIRECT_CHAT_STT_ALLOW_LOOPBACK_DEVICE", False):
            return configured_device
        devices = self.list_devices()
        if not isinstance(devices, list) or not devices:
            return configured_device

        selected = None
        if configured_device is not None:
            for d in devices:
                if not isinstance(d, dict):
                    continue
                idx = d.get("index")
                name = str(d.get("name", "")).strip()
                if isinstance(configured_device, int):
                    if idx == configured_device:
                        selected = d
                        break
                else:
                    if str(configured_device).strip().lower() == name.lower():
                        selected = d
                        break

        if selected is None:
            return configured_device

        sel_name = str(selected.get("name", ""))
        if not self._is_likely_loopback_device_name(sel_name):
            return configured_device

        non_loopback = [
            d
            for d in devices
            if isinstance(d, dict) and not self._is_likely_loopback_device_name(str(d.get("name", "")))
        ]
        if not non_loopback:
            return configured_device

        preferred = None
        for d in non_loopback:
            if bool(d.get("default", False)):
                preferred = d
                break
        if preferred is None:
            preferred = non_loopback[0]
        replacement = preferred.get("index")
        if isinstance(replacement, int):
            self._log(
                f"[stt] device_loopback_guard: configured={configured_device}({sel_name}) -> fallback={replacement}({preferred.get('name', '')})"
            )
            return replacement
        return configured_device

    def _command_only_enabled(self) -> bool:
        state = self._voice_state()
        if "stt_command_only" in state:
            return bool(state.get("stt_command_only"))
        return _env_flag("DIRECT_CHAT_STT_COMMAND_ONLY", True)

    def _chat_enabled(self) -> bool:
        state = self._voice_state()
        if "stt_chat_enabled" in state:
            return bool(state.get("stt_chat_enabled"))
        return _env_flag("DIRECT_CHAT_STT_CHAT_ENABLED", True)

    def _debug_enabled(self) -> bool:
        state = self._voice_state()
        if "stt_debug" in state:
            return bool(state.get("stt_debug"))
        return _env_flag("DIRECT_CHAT_STT_DEBUG", False)

    def _barge_any_enabled(self) -> bool:
        state = self._voice_state()
        if "stt_barge_any" in state:
            return bool(state.get("stt_barge_any"))
        return _env_flag("DIRECT_CHAT_STT_BARGE_ANY", False)

    def _barge_any_cooldown_ms(self) -> int:
        state = self._voice_state()
        try:
            return max(300, int(state.get("stt_barge_any_cooldown_ms", 1200)))
        except Exception:
            return 1200

    def _no_audio_timeout_sec(self) -> float:
        state = self._voice_state()
        try:
            return max(1.0, float(state.get("stt_no_audio_timeout_sec", 3.0)))
        except Exception:
            return 3.0

    def _on_worker_telemetry(self, event: dict) -> None:
        if not isinstance(event, dict):
            return
        with self._lock:
            kind = str(event.get("kind", "")).strip().lower()
            if "frames_seen" in event:
                try:
                    self._frames_seen = max(self._frames_seen, int(event.get("frames_seen", self._frames_seen)))
                except Exception:
                    pass
            if "last_audio_ts" in event:
                try:
                    self._last_audio_ts = max(self._last_audio_ts, float(event.get("last_audio_ts", 0.0) or 0.0))
                except Exception:
                    pass
            if "rms_current" in event:
                try:
                    self._rms_current = max(0.0, float(event.get("rms_current", 0.0) or 0.0))
                except Exception:
                    pass
            if "vad_active" in event:
                self._vad_active = bool(event.get("vad_active"))
            if "in_speech" in event:
                self._in_speech = bool(event.get("in_speech"))
            if "vad_frames" in event:
                try:
                    self._vad_frames = max(self._vad_frames, int(event.get("vad_frames", self._vad_frames)))
                except Exception:
                    pass
            if "vad_true_frames" in event:
                try:
                    self._vad_true_frames = max(
                        self._vad_true_frames, int(event.get("vad_true_frames", self._vad_true_frames))
                    )
                except Exception:
                    pass
            if "last_segment_ms" in event:
                try:
                    self._last_segment_ms = max(self._last_segment_ms, int(event.get("last_segment_ms", 0) or 0))
                except Exception:
                    pass
            if "silence_ms" in event:
                try:
                    self._silence_ms = max(0, int(event.get("silence_ms", 0) or 0))
                except Exception:
                    pass
            if "effective_seg_thr" in event:
                try:
                    self._effective_seg_thr = max(0.0, float(event.get("effective_seg_thr", 0.0) or 0.0))
                except Exception:
                    pass
            elif "segment_threshold" in event:
                try:
                    self._effective_seg_thr = max(0.0, float(event.get("segment_threshold", 0.0) or 0.0))
                except Exception:
                    pass
            if "segment_thr_off" in event:
                try:
                    self._effective_seg_thr_off = max(0.0, float(event.get("segment_thr_off", 0.0) or 0.0))
                except Exception:
                    pass
            if "min_segment_ms" in event:
                try:
                    self._effective_min_segment_ms = max(0, int(event.get("min_segment_ms", 0) or 0))
                except Exception:
                    pass
            if "speech_hangover_ms" in event:
                try:
                    self._speech_hangover_ms = max(0, int(event.get("speech_hangover_ms", 0) or 0))
                except Exception:
                    pass
            if "device" in event:
                self._device_label = str(event.get("device", "")).strip()
            if kind == "stt_drop":
                reason = str(event.get("reason", "drop_unknown"))[:120]
                self._register_drop_locked(reason)
            elif kind == "stt_error":
                detail = str(event.get("detail", "")).strip()
                self._register_drop_locked("stt_error")
                if detail:
                    self._last_error = detail[:240]
                    self._drop_reason = self._last_error
            elif kind == "stt_emit":
                self._drop_reason = ""
                self._stt_emit_count += 1

    def _register_drop_locked(self, reason: str) -> None:
        self._items_dropped += 1
        r = str(reason or "drop_unknown")[:120]
        self._drop_reason = r
        self._drop_reason_counts[r] = int(self._drop_reason_counts.get(r, 0) or 0) + 1
        if any(k in r for k in ("text_", "command_", "tts_guard_", "empty_text")):
            self._items_dropped_text += 1
        else:
            self._items_dropped_audio += 1

    def _reset_diag_locked(self) -> None:
        self._frames_seen = 0
        self._last_audio_ts = 0.0
        self._rms_current = 0.0
        self._vad_active = False
        self._in_speech = False
        self._vad_frames = 0
        self._vad_true_frames = 0
        self._last_segment_ms = 0
        self._silence_ms = 0
        self._effective_seg_thr = 0.0
        self._effective_seg_thr_off = 0.0
        self._effective_min_segment_ms = 0
        self._speech_hangover_ms = 0
        self._device_label = ""
        self._drop_reason = ""
        self._items_total = 0
        self._items_dropped = 0
        self._items_dropped_audio = 0
        self._items_dropped_text = 0
        self._drop_reason_counts = {}
        self._stt_emit_count = 0
        self._voice_text_committed = 0
        self._stt_chat_commit_total = 0
        self._last_item_ts = 0.0
        self._last_raw_text = ""
        self._last_norm_text = ""
        self._last_matched_cmd = ""
        self._last_match_reason = ""
        self._last_match_ts = 0.0
        self._last_barge_any_mono = 0.0
        self._pending_chat_after_tts = None

    def _build_worker_locked(self):
        from molbot_direct_chat import stt_local

        state = self._voice_state()
        min_chars_default = self._env_int("DIRECT_CHAT_STT_MIN_CHARS", 3)
        try:
            min_chars = max(1, int(state.get("stt_min_chars", min_chars_default)))
        except Exception:
            min_chars = max(1, int(min_chars_default))
        segment_rms_threshold = _stt_segment_rms_threshold_from_state(state)
        selected_device = self._resolve_stt_device(self._selected_stt_device())
        chat_mode_enabled = bool(self._chat_enabled())
        seg_profile = _stt_segmentation_profile(chat_mode_enabled)
        try:
            preamp_gain = max(0.05, float(state.get("stt_preamp_gain", os.environ.get("DIRECT_CHAT_STT_PREAMP_GAIN", "1.0"))))
        except Exception:
            preamp_gain = 1.0
        agc_enabled = bool(state.get("stt_agc_enabled", _env_flag("DIRECT_CHAT_STT_AGC_ENABLED", False)))
        try:
            agc_target_rms = max(0.01, min(0.30, float(state.get("stt_agc_target_rms", os.environ.get("DIRECT_CHAT_STT_AGC_TARGET_RMS", "0.06")))))
        except Exception:
            agc_target_rms = 0.06
        cfg = stt_local.STTConfig(
            sample_rate=max(8000, self._env_int("DIRECT_CHAT_STT_SAMPLE_RATE", 16000)),
            channels=max(1, self._env_int("DIRECT_CHAT_STT_CHANNELS", 1)),
            device=selected_device,
            frame_ms=max(10, min(30, self._env_int("DIRECT_CHAT_STT_FRAME_MS", 20))),
            vad_mode=max(0, min(3, self._env_int("DIRECT_CHAT_STT_VAD_MODE", 1))),
            min_speech_ms=int(seg_profile.get("min_speech_ms", 220)),
            chat_min_speech_ms=int(seg_profile.get("chat_min_speech_ms", 180)),
            max_silence_ms=int(seg_profile.get("max_silence_ms", 350)),
            max_segment_s=float(seg_profile.get("max_segment_s", 1.8)),
            start_preroll_ms=max(0, min(1000, self._env_int("DIRECT_CHAT_STT_START_PREROLL_MS", 260))),
            rms_speech_threshold=max(0.0005, float(segment_rms_threshold)),
            rms_min_frames=max(1, self._env_int("DIRECT_CHAT_STT_RMS_MIN_FRAMES", 2)),
            segment_hysteresis_off_ratio=max(
                0.10,
                min(0.95, self._env_float("DIRECT_CHAT_STT_SEGMENT_HYSTERESIS_OFF_RATIO", 0.65)),
            ),
            segment_hangover_ms=max(0, self._env_int("DIRECT_CHAT_STT_SEGMENT_HANGOVER_MS", 140)),
            chat_mode=chat_mode_enabled,
            preamp_gain=float(preamp_gain),
            agc_enabled=bool(agc_enabled),
            agc_target_rms=float(agc_target_rms),
            agc_max_gain=max(1.0, self._env_float("DIRECT_CHAT_STT_AGC_MAX_GAIN", 6.0)),
            agc_attack=max(0.01, min(1.0, self._env_float("DIRECT_CHAT_STT_AGC_ATTACK", 0.35))),
            agc_release=max(0.01, min(1.0, self._env_float("DIRECT_CHAT_STT_AGC_RELEASE", 0.08))),
            language=str(os.environ.get("DIRECT_CHAT_STT_LANGUAGE", "es")).strip() or "es",
            model=str(os.environ.get("DIRECT_CHAT_STT_MODEL", "small")).strip() or "small",
            fw_device=str(os.environ.get("DIRECT_CHAT_STT_FW_DEVICE", "cpu")).strip() or "cpu",
            fw_compute_type=str(os.environ.get("DIRECT_CHAT_STT_FW_COMPUTE_TYPE", "int8")).strip() or "int8",
            initial_prompt=str(os.environ.get("DIRECT_CHAT_STT_INITIAL_PROMPT", "")).strip(),
            min_chars=min_chars,
        )
        return stt_local.STTWorker(
            cfg,
            self._queue,
            should_listen=self._should_listen,
            logger=self._log,
            telemetry=self._on_worker_telemetry,
        )

    def _schedule_retry_locked(self, now_mono: float) -> None:
        idx = min(self._retry_idx, len(self._RETRY_DELAYS_SEC) - 1)
        delay = float(self._RETRY_DELAYS_SEC[idx])
        self._retry_idx += 1
        self._next_retry_mono = now_mono + max(0.2, delay)

    def _sync_worker_locked(self, now_mono: float) -> None:
        if self._worker is not None and not self._worker.is_running():
            last_error = str(getattr(self._worker, "last_error", "")).strip()
            if last_error:
                self._last_error = last_error
            self._worker = None

        if not self._enabled:
            return
        if self._worker is not None and self._worker.is_running():
            return
        if now_mono < self._next_retry_mono:
            return

        try:
            worker = self._build_worker_locked()
        except Exception as e:
            self._last_error = f"stt_init_failed:{e}"
            self._schedule_retry_locked(now_mono)
            self._log(f"[stt] {self._last_error}")
            return

        worker.start()
        if worker.is_running():
            self._worker = worker
            self._last_error = ""
            self._retry_idx = 0
            self._next_retry_mono = 0.0
            return

        self._last_error = str(getattr(worker, "last_error", "")).strip() or "stt_start_failed"
        self._worker = None
        self._schedule_retry_locked(now_mono)
        self._log(f"[stt] {self._last_error}")

    def enable(self, session_id: str = "") -> None:
        sid = _safe_session_id(session_id) if session_id else ""
        with self._lock:
            was_enabled = bool(self._enabled)
            self._enabled = True
            if self._enabled_since_mono <= 0.0:
                self._enabled_since_mono = time.monotonic()
            if not was_enabled:
                self._reset_diag_locked()
                self._enabled_since_mono = time.monotonic()
            if sid and sid != "default" and sid != self._owner_session_id:
                self._owner_session_id = sid
                self._clear_queue_locked()
            self._sync_worker_locked(time.monotonic())

    def claim_owner(self, session_id: str) -> None:
        sid = _safe_session_id(session_id)
        if not sid or sid == "default":
            return
        with self._lock:
            if sid != self._owner_session_id:
                self._owner_session_id = sid
                self._clear_queue_locked()
            if self._enabled:
                self._sync_worker_locked(time.monotonic())

    def disable(self) -> None:
        worker = None
        with self._lock:
            self._enabled = False
            self._owner_session_id = ""
            worker = self._worker
            self._worker = None
            self._retry_idx = 0
            self._next_retry_mono = 0.0
            self._enabled_since_mono = 0.0
            self._reset_diag_locked()
            self._clear_queue_locked()
        if worker is not None:
            try:
                worker.stop(timeout=2.0)
            except Exception:
                pass

    def restart(self) -> None:
        worker = None
        with self._lock:
            worker = self._worker
            self._worker = None
            self._retry_idx = 0
            self._next_retry_mono = 0.0
            self._reset_diag_locked()
        if worker is not None:
            try:
                worker.stop(timeout=2.0)
            except Exception:
                pass
        with self._lock:
            if self._enabled:
                self._enabled_since_mono = time.monotonic()
                self._sync_worker_locked(time.monotonic())

    def inject(self, session_id: str, text: str = "", cmd: str = "") -> dict:
        sid = _safe_session_id(session_id)
        voice_cmd = str(cmd or "").strip().lower()
        raw_text = str(text or "").strip()
        if voice_cmd and (not raw_text):
            if voice_cmd in ("pause", "pausa", "stop", "detenete", "detente"):
                raw_text = "pausa"
            elif voice_cmd in ("continue", "continuar", "segui", "seguir"):
                raw_text = "continuar"
            elif voice_cmd in ("repeat", "repetir", "repeti"):
                raw_text = "repetir"
            else:
                raw_text = voice_cmd
        if not raw_text:
            return {"ok": False, "error": "stt_inject_empty_text"}
        with self._lock:
            self._sync_worker_locked(time.monotonic())
            if not self._enabled:
                return {"ok": False, "error": "stt_disabled"}
            if sid and sid != "default" and not self._owner_session_id:
                self._owner_session_id = sid
            if self._owner_session_id and sid and sid != self._owner_session_id:
                return {"ok": False, "error": "stt_owner_mismatch", "stt_owner_session_id": str(self._owner_session_id)}
            payload = {"text": raw_text, "ts": time.time(), "injected": True}
            try:
                self._queue.put_nowait(payload)
            except Exception:
                self._register_drop_locked("inject_queue_full")
                return {"ok": False, "error": "stt_queue_full"}
        return {"ok": True, "item": payload}

    def list_devices(self) -> list[dict]:
        try:
            from molbot_direct_chat import stt_local

            out = stt_local.list_input_devices()
            return out if isinstance(out, list) else []
        except Exception as e:
            self._log(f"[stt] list_devices_failed:{e}")
            return []

    def poll(self, session_id: str, limit: int = 3) -> list[dict]:
        sid = _safe_session_id(session_id)
        if limit <= 0:
            limit = 1
        limit = min(limit, 12)

        with self._lock:
            self._sync_worker_locked(time.monotonic())
            if not self._enabled:
                return []
            if sid and sid != "default" and not self._owner_session_id:
                self._owner_session_id = sid
                self._clear_queue_locked()
            if sid != self._owner_session_id:
                return []

        out: list[dict] = []
        tts_playing = _tts_is_playing()
        command_only = self._command_only_enabled()
        chat_enabled = self._chat_enabled()
        chat_min_words = max(1, _int_env("DIRECT_CHAT_STT_CHAT_MIN_WORDS", 2))
        debug_enabled = self._debug_enabled()
        reader_active = bool(_reader_voice_any_barge_target_active(sid))
        barge_any_enabled = self._barge_any_enabled()
        if (not tts_playing) and chat_enabled:
            with self._lock:
                pending_after_tts = dict(self._pending_chat_after_tts) if isinstance(self._pending_chat_after_tts, dict) else None
                self._pending_chat_after_tts = None
            if pending_after_tts:
                text_p = str(pending_after_tts.get("text", "")).strip()
                if text_p and (not _stt_chat_drop_reason(text_p, min_words_chat=chat_min_words)):
                    ts_p = float(pending_after_tts.get("ts", time.time()) or time.time())
                    norm_p = str(pending_after_tts.get("norm", _normalize_text(text_p)))
                    out.append({"text": text_p, "norm": norm_p, "ts": ts_p, "kind": "chat_text", "source": "voice_chat"})
                    with self._lock:
                        self._items_total += 1
                        self._voice_text_committed += 1
                        self._stt_chat_commit_total += 1
                        self._last_item_ts = max(self._last_item_ts, ts_p)
                        self._last_match_reason = "voice_chat_text_flushed"
        # Allow any-speech barge while *any* TTS is playing, not only Reader mode.
        barge_target_active = bool(barge_any_enabled and tts_playing)
        if not barge_target_active:
            with self._lock:
                self._last_barge_any_mono = 0.0
        if barge_target_active:
            now_mono = time.monotonic()
            now_ts = time.time()
            with self._lock:
                cooldown_ms = self._barge_any_cooldown_ms()
                last_barge = float(self._last_barge_any_mono)
                if last_barge > (now_mono + 0.250):
                    # Defensive reset in case of mixed clocks or stale state.
                    last_barge = 0.0
                    self._last_barge_any_mono = 0.0
                elapsed_ms = int(max(0.0, (now_mono - last_barge) * 1000.0))
                barge_state = self._voice_state()
                rms_threshold = _stt_barge_rms_threshold_from_state(barge_state)
                try:
                    rms_threshold_f = max(0.001, float(rms_threshold))
                except Exception:
                    rms_threshold_f = 0.012
                speech_detected = bool(self._vad_active or self._in_speech)
                if speech_detected:
                    if reader_active:
                        min_rms = max(0.001, rms_threshold_f)
                    else:
                        # Outside Reader mode, require stronger signal to avoid
                        # self-interruptions from room noise / speaker bleed.
                        min_rms = max(0.03, rms_threshold_f * 1.6)
                    speech_detected = bool(float(self._rms_current) >= min_rms)
                if (not speech_detected) and (float(self._rms_current) >= max(0.001, rms_threshold_f * 0.85)):
                    speech_detected = bool(int(self._silence_ms) <= 450)
                cooldown_ready = bool(last_barge <= 0.0 or elapsed_ms >= cooldown_ms)
                if speech_detected and cooldown_ready:
                    self._last_barge_any_mono = now_mono
                    self._last_match_reason = "voice_any_barge"
                    self._last_matched_cmd = "pause"
                    self._last_match_ts = now_ts
                    out.append(
                        {
                            "text": "voz detectada",
                            "ts": now_ts,
                            "kind": "voice_cmd",
                            "cmd": "pause",
                            "source": "voice_any",
                        }
                    )
                    self._items_total += 1
                    self._last_item_ts = max(self._last_item_ts, now_ts)
        for _ in range(limit):
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                if not text:
                    with self._lock:
                        self._register_drop_locked("empty_text")
                    continue
                cmd = _voice_command_kind(text)
                ts = float(item.get("ts", time.time()))
                norm_text = _normalize_text(text)
                with self._lock:
                    self._last_raw_text = text[:240]
                    self._last_norm_text = norm_text[:240]
                    self._last_matched_cmd = cmd
                    self._last_match_ts = ts
                if _is_probable_stt_noise(text, cmd=cmd):
                    with self._lock:
                        self._last_match_reason = "text_noise_filtered"
                    if debug_enabled:
                        out.append(
                            {
                                "kind": "stt_debug",
                                "text": text,
                                "norm": norm_text,
                                "reason": "text_noise_filtered",
                                "ts": ts,
                            }
                        )
                    with self._lock:
                        self._register_drop_locked("text_noise_filtered")
                    continue
                # Voice commands must bypass TTS/non-command guards so barge-in
                # works while the reader is speaking.
                if cmd:
                    with self._lock:
                        self._last_match_reason = "matched_command"
                    event = {"text": text, "ts": ts, "kind": "voice_cmd", "cmd": cmd, "source": "voice_cmd"}
                    out.append(event)
                    with self._lock:
                        self._items_total += 1
                        self._last_item_ts = max(self._last_item_ts, ts)
                    continue
                if tts_playing and (not cmd):
                    if chat_enabled:
                        drop_reason = _stt_chat_drop_reason(text, min_words_chat=chat_min_words)
                        if not drop_reason:
                            with self._lock:
                                self._pending_chat_after_tts = {
                                    "text": text[:320],
                                    "norm": norm_text[:320],
                                    "ts": ts,
                                }
                                self._last_match_reason = "tts_guard_buffered"
                            if debug_enabled:
                                out.append(
                                    {
                                        "kind": "stt_debug",
                                        "text": text,
                                        "norm": norm_text,
                                        "reason": "tts_guard_buffered",
                                        "ts": ts,
                                    }
                                )
                            continue
                    with self._lock:
                        self._last_match_reason = "tts_guard_non_command"
                    if debug_enabled:
                        out.append(
                            {
                                "kind": "stt_debug",
                                "text": text,
                                "norm": norm_text,
                                "reason": "tts_guard_non_command",
                                "ts": ts,
                            }
                        )
                    with self._lock:
                        self._register_drop_locked("tts_guard_non_command")
                    continue
                voice_chat_passthrough = bool(chat_enabled and (not tts_playing) and (not reader_active))
                if voice_chat_passthrough and (not cmd):
                    drop_reason = _stt_chat_drop_reason(text, min_words_chat=chat_min_words)
                    if drop_reason:
                        with self._lock:
                            self._last_match_reason = str(drop_reason)
                            self._register_drop_locked(str(drop_reason))
                        continue
                    with self._lock:
                        self._last_match_reason = "voice_chat_text"
                    event = {"text": text, "norm": norm_text, "ts": ts, "kind": "chat_text", "source": "voice_chat"}
                    out.append(event)
                    with self._lock:
                        self._items_total += 1
                        self._voice_text_committed += 1
                        self._stt_chat_commit_total += 1
                        self._last_item_ts = max(self._last_item_ts, ts)
                    continue
                if command_only and (not cmd):
                    with self._lock:
                        self._last_match_reason = "command_only_non_command"
                    if debug_enabled:
                        out.append(
                            {
                                "kind": "stt_debug",
                                "text": text,
                                "norm": norm_text,
                                "reason": "command_only_non_command",
                                "ts": ts,
                            }
                        )
                    with self._lock:
                        self._register_drop_locked("command_only_non_command")
                    continue
                with self._lock:
                    self._last_match_reason = "accepted_text"
                if (not cmd):
                    drop_reason = _stt_chat_drop_reason(text, min_words_chat=chat_min_words)
                    if drop_reason:
                        with self._lock:
                            self._last_match_reason = str(drop_reason)
                            self._register_drop_locked(str(drop_reason))
                        continue
                event = {"text": text, "ts": ts}
                out.append(event)
                with self._lock:
                    self._items_total += 1
                    self._last_item_ts = max(self._last_item_ts, ts)
        return out

    def status(self) -> dict:
        with self._lock:
            now = time.monotonic()
            running = bool(self._worker is not None and self._worker.is_running())
            retry_in = 0.0
            if self._next_retry_mono > now:
                retry_in = max(0.0, self._next_retry_mono - now)
            no_audio_timeout = self._no_audio_timeout_sec()
            enabled_age = max(0.0, now - float(self._enabled_since_mono or 0.0)) if self._enabled_since_mono > 0.0 else 0.0
            no_audio_input = bool(self._enabled and running and enabled_age >= no_audio_timeout and int(self._frames_seen) <= 0)
            no_speech_detected = bool(
                self._enabled
                and running
                and enabled_age >= no_audio_timeout
                and int(self._frames_seen) > 0
                and int(self._vad_true_frames) <= 0
            )
            vad_true_ratio = (float(self._vad_true_frames) / float(self._frames_seen)) if self._frames_seen > 0 else 0.0
            state = self._voice_state()
            stt_segment_rms_threshold = _stt_segment_rms_threshold_from_state(state)
            stt_barge_rms_threshold = _stt_barge_rms_threshold_from_state(state)
            stt_legacy_rms_threshold = _stt_legacy_rms_threshold_from_state(state)
            try:
                stt_preamp_gain = max(0.05, float(state.get("stt_preamp_gain", 1.0)))
            except Exception:
                stt_preamp_gain = 1.0
            stt_agc_enabled = bool(state.get("stt_agc_enabled", False))
            try:
                stt_agc_target_rms = max(0.01, min(0.30, float(state.get("stt_agc_target_rms", 0.06))))
            except Exception:
                stt_agc_target_rms = 0.06
            effective_seg_thr = float(self._effective_seg_thr or stt_segment_rms_threshold)
            if effective_seg_thr <= 0.0:
                effective_seg_thr = float(stt_segment_rms_threshold)
            effective_seg_thr_off = float(self._effective_seg_thr_off or 0.0)
            if effective_seg_thr_off <= 0.0:
                effective_seg_thr_off = max(0.0003, effective_seg_thr * 0.65)
            effective_min_seg_ms = int(self._effective_min_segment_ms or 0)
            if effective_min_seg_ms <= 0:
                effective_min_seg_ms = max(120, self._env_int("DIRECT_CHAT_STT_MIN_SPEECH_MS", 220))
                if bool(self._chat_enabled()):
                    effective_min_seg_ms = min(
                        effective_min_seg_ms,
                        max(120, self._env_int("DIRECT_CHAT_STT_CHAT_MIN_SPEECH_MS", 180)),
                    )
            drop_reason_counts_sorted = dict(
                sorted(self._drop_reason_counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))[:8]
            )
            return {
                "stt_enabled": bool(self._enabled),
                "stt_running": running,
                "stt_owner_session_id": str(self._owner_session_id),
                "stt_last_error": str(self._last_error),
                "stt_retry_in_sec": round(retry_in, 3),
                "stt_device_name": str(self._device_label),
                "stt_frames_seen": int(self._frames_seen),
                "stt_last_audio_ts": float(self._last_audio_ts or 0.0),
                "stt_rms_current": float(self._rms_current or 0.0),
                "stt_vad_active": bool(self._vad_active),
                "stt_in_speech": bool(self._in_speech),
                "stt_vad_frames": int(self._vad_frames),
                "stt_vad_true_frames": int(self._vad_true_frames),
                "stt_vad_true_ratio": float(vad_true_ratio),
                "stt_last_segment_ms": int(self._last_segment_ms),
                "stt_silence_ms": int(self._silence_ms),
                "stt_drop_reason": str(self._drop_reason),
                "items_total": int(self._items_total),
                "items_dropped": int(self._items_dropped),
                "items_dropped_audio": int(self._items_dropped_audio),
                "items_dropped_text": int(self._items_dropped_text),
                "stt_emit_count": int(self._stt_emit_count),
                "voice_text_committed": int(self._voice_text_committed),
                "stt_chat_commit_total": int(self._stt_chat_commit_total),
                "drop_reason_counts": drop_reason_counts_sorted,
                "last_item_ts": float(self._last_item_ts or 0.0),
                "last_raw_text": str(self._last_raw_text),
                "last_norm_text": str(self._last_norm_text),
                "matched_cmd": str(self._last_matched_cmd),
                "match_reason": str(self._last_match_reason),
                "match_ts": float(self._last_match_ts or 0.0),
                "stt_no_audio_input": bool(no_audio_input),
                "stt_no_speech_detected": bool(no_speech_detected),
                "stt_no_audio_timeout_sec": float(no_audio_timeout),
                "stt_rms_threshold": float(stt_legacy_rms_threshold),
                "stt_segment_rms_threshold": float(stt_segment_rms_threshold),
                "stt_barge_rms_threshold": float(stt_barge_rms_threshold),
                "stt_effective_seg_thr": float(effective_seg_thr),
                "stt_effective_seg_thr_off": float(effective_seg_thr_off),
                "stt_effective_min_segment_ms": int(effective_min_seg_ms),
                "stt_speech_hangover_ms": int(self._speech_hangover_ms),
                "stt_command_only": bool(self._command_only_enabled()),
                "stt_chat_enabled": bool(self._chat_enabled()),
                "stt_debug": bool(self._debug_enabled()),
                "stt_barge_any": bool(self._barge_any_enabled()),
                "stt_barge_any_cooldown_ms": int(self._barge_any_cooldown_ms()),
                "stt_preamp_gain": float(stt_preamp_gain),
                "stt_agc_enabled": bool(stt_agc_enabled),
                "stt_agc_target_rms": float(stt_agc_target_rms),
                "stt_server_chat_bridge_enabled": bool(_voice_server_chat_bridge_enabled() and _DIRECT_CHAT_HTTP_PORT > 0),
            }

    def shutdown(self) -> None:
        self.disable()


_STT_MANAGER = STTManager()
atexit.register(_STT_MANAGER.shutdown)


def _voice_server_chat_bridge_enabled() -> bool:
    return _env_flag("DIRECT_CHAT_STT_SERVER_CHAT_BRIDGE", True)


def _voice_chat_dedupe_key(text: str, ts: float = 0.0) -> str:
    norm = _normalize_text(text)
    if not norm:
        norm = str(text or "").strip().lower()
    ts_ms = int(round(float(ts or 0.0) * 1000.0)) if float(ts or 0.0) > 0.0 else 0
    base = f"{ts_ms}|{norm}" if ts_ms > 0 else norm
    digest = hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{ts_ms}:{digest}" if ts_ms > 0 else digest


def _voice_chat_should_process(session_id: str, text: str, ts: float = 0.0) -> bool:
    sid = _safe_session_id(session_id or "default")
    key = _voice_chat_dedupe_key(text, ts)
    now_mono = time.monotonic()
    ttl_sec = max(20.0, float(_int_env("DIRECT_CHAT_STT_SERVER_CHAT_DEDUPE_TTL_SEC", 90)))
    with _VOICE_CHAT_DEDUPE_LOCK:
        bucket = _VOICE_CHAT_DEDUPE_BY_SESSION.get(sid, {})
        if not isinstance(bucket, dict):
            bucket = {}
        fresh = {k: float(v) for k, v in bucket.items() if (now_mono - float(v)) <= ttl_sec}
        if key in fresh:
            _VOICE_CHAT_DEDUPE_BY_SESSION[sid] = fresh
            return False
        fresh[key] = now_mono
        if len(fresh) > 96:
            ordered = sorted(fresh.items(), key=lambda kv: kv[1], reverse=True)[:96]
            fresh = dict(ordered)
        _VOICE_CHAT_DEDUPE_BY_SESSION[sid] = fresh
    return True


def _voice_chat_model_payload(session_id: str) -> dict:
    sid = _safe_session_id(session_id or "default")
    catalog = _model_catalog()
    model_id = str(catalog.get("default_model", "openai-codex/gpt-5.1-codex-mini")).strip() or "openai-codex/gpt-5.1-codex-mini"
    model_override = str(os.environ.get("DIRECT_CHAT_STT_BRIDGE_MODEL", "")).strip()
    if model_override:
        model_id = model_override
    backend = "cloud"
    by_id = catalog.get("by_id", {})
    if isinstance(by_id, dict):
        meta = by_id.get(model_id)
        if isinstance(meta, dict):
            b = str(meta.get("backend", "cloud")).strip().lower()
            if b in ("cloud", "local"):
                backend = b
    backend_override = str(os.environ.get("DIRECT_CHAT_STT_BRIDGE_BACKEND", "")).strip().lower()
    if backend_override in ("cloud", "local"):
        backend = backend_override
    history = _load_history(sid, model=model_id, backend=backend)
    hist_limit = max(0, _int_env("DIRECT_CHAT_STT_BRIDGE_HISTORY_MAX", 24))
    if isinstance(history, list) and hist_limit > 0:
        history = history[-hist_limit:]
    elif hist_limit <= 0:
        history = []
    return {
        "session_id": sid,
        "model": model_id,
        "model_backend": backend,
        "history": history if isinstance(history, list) else [],
    }


def _voice_chat_submit_backend(session_id: str, text: str, ts: float = 0.0) -> bool:
    sid = _safe_session_id(session_id or "default")
    clean = str(text or "").strip()
    if not clean:
        return False
    if (not _voice_enabled()) or (not _voice_server_chat_bridge_enabled()):
        return False
    if _DIRECT_CHAT_HTTP_PORT <= 0:
        return False
    model_payload = _voice_chat_model_payload(sid)
    allow_firefox = _env_flag("DIRECT_CHAT_STT_BRIDGE_ALLOW_FIREFOX", False)
    bridge_tools = ["tts"]
    if _env_flag("DIRECT_CHAT_STT_BRIDGE_ALLOW_WEB_SEARCH", True):
        bridge_tools.append("web_search")
    if _env_flag("DIRECT_CHAT_STT_BRIDGE_ALLOW_WEB_ASK", True):
        bridge_tools.append("web_ask")
    if _env_flag("DIRECT_CHAT_STT_BRIDGE_ALLOW_DESKTOP", False):
        bridge_tools.append("desktop")
    if allow_firefox:
        bridge_tools.append("firefox")
    payload = {
        "message": clean,
        "session_id": sid,
        "model": str(model_payload.get("model", "openai-codex/gpt-5.1-codex-mini")),
        "model_backend": str(model_payload.get("model_backend", "cloud")),
        "history": model_payload.get("history", []),
        "mode": "operativo",
        "allowed_tools": bridge_tools,
        "attachments": [],
        "source": "voice_server_bridge",
        "voice_item_ts": float(ts or 0.0),
    }
    url = f"http://{_DIRECT_CHAT_HTTP_HOST}:{int(_DIRECT_CHAT_HTTP_PORT)}/api/chat"
    try:
        resp = requests.post(url, json=payload, timeout=max(8.0, float(_int_env("DIRECT_CHAT_STT_SERVER_CHAT_TIMEOUT_SEC", 120))))
    except Exception:
        return False
    return bool(resp.status_code < 400)


def _voice_chat_merge_text(prev_text: str, new_text: str) -> str:
    prev = str(prev_text or "").strip()
    new = str(new_text or "").strip()
    if not prev:
        return new
    if not new:
        return prev
    prev_l = prev.lower()
    new_l = new.lower()
    if prev_l == new_l or prev_l.endswith(new_l):
        return prev
    if new_l.startswith(prev_l):
        return new
    if new_l in prev_l:
        return prev
    return f"{prev} {new}".strip()


def _voice_chat_pending_put(session_id: str, text: str, ts: float = 0.0) -> None:
    sid = _safe_session_id(session_id or "default")
    clean = str(text or "").strip()
    if not clean:
        return
    now_mono = time.monotonic()
    try:
        ts_val = float(ts or 0.0)
    except Exception:
        ts_val = 0.0
    with _VOICE_CHAT_PENDING_LOCK:
        prev = _VOICE_CHAT_PENDING_BY_SESSION.get(sid, {})
        prev_text = str(prev.get("text", "")).strip() if isinstance(prev, dict) else ""
        merged = _voice_chat_merge_text(prev_text, clean)
        prev_ts = float(prev.get("ts", 0.0) or 0.0) if isinstance(prev, dict) else 0.0
        _VOICE_CHAT_PENDING_BY_SESSION[sid] = {
            "text": merged[:900],
            "ts": max(prev_ts, ts_val),
            "updated_mono": now_mono,
        }


def _voice_chat_pending_get(session_id: str) -> dict | None:
    sid = _safe_session_id(session_id or "default")
    with _VOICE_CHAT_PENDING_LOCK:
        cur = _VOICE_CHAT_PENDING_BY_SESSION.get(sid)
        if not isinstance(cur, dict):
            return None
        return dict(cur)


def _voice_chat_pending_clear(session_id: str) -> None:
    sid = _safe_session_id(session_id or "default")
    with _VOICE_CHAT_PENDING_LOCK:
        _VOICE_CHAT_PENDING_BY_SESSION.pop(sid, None)


def _voice_chat_text_looks_incomplete(text: str) -> bool:
    n = _normalize_text(text)
    if not n:
        return True
    if n.endswith((" de", " del", " en", " y", " o", " que", " la", " el", " los", " las", " un", " una", " para", " por", " con", " entre", " sobre", " a")):
        return True
    if re.search(r"\bpregunt\w*\s+(?:a\s+)?gemini\b", n, flags=re.IGNORECASE) and not re.search(
        r"\b(que|qué|sobre|acerca|si|cu[aá]l|cu[aá]ndo|donde|dónde|hora|noticias)\b",
        n,
        flags=re.IGNORECASE,
    ):
        return True
    return False


def _voice_chat_pending_ready(session_id: str, pending: dict) -> bool:
    sid = _safe_session_id(session_id or "default")
    if not isinstance(pending, dict):
        return False
    now_mono = time.monotonic()
    settle_ms = max(80, _int_env("DIRECT_CHAT_STT_BRIDGE_COMMIT_SETTLE_MS", 420))
    min_silence_ms = max(140, _int_env("DIRECT_CHAT_STT_BRIDGE_MIN_SILENCE_MS", 320))
    max_wait_ms = max(settle_ms, _int_env("DIRECT_CHAT_STT_BRIDGE_MAX_WAIT_MS", 2600))
    updated_mono = float(pending.get("updated_mono", now_mono) or now_mono)
    elapsed_ms = int(max(0.0, (now_mono - updated_mono) * 1000.0))
    pending_text = str(pending.get("text", "")).strip()
    incomplete = _voice_chat_text_looks_incomplete(pending_text)
    st = _STT_MANAGER.status()
    if not bool(st.get("stt_running", False)):
        return True
    if elapsed_ms >= max_wait_ms + (1600 if incomplete else 0):
        return True
    if elapsed_ms < settle_ms:
        return False
    owner = str(st.get("stt_owner_session_id", "") or "").strip()
    if owner and owner != sid:
        return False
    if bool(st.get("stt_in_speech", False)) or bool(st.get("stt_vad_active", False)):
        return False
    try:
        silence_ms = int(st.get("stt_silence_ms", 0) or 0)
    except Exception:
        silence_ms = 0
    return silence_ms >= min_silence_ms


def _apply_voice_pause_interrupt(session_id: str, source: str = "voice_cmd", keyword: str = "") -> bool:
    sid = _safe_session_id(session_id or "default")
    src = str(source or "").strip().lower()
    key = str(keyword or "").strip()[:80]
    if not key:
        key = "voz" if src in ("voice_any", "stt_any") else "detenete"
    reader_active = bool(_reader_voice_any_barge_target_active(sid))
    if reader_active:
        _READER_STORE.set_continuous(sid, False, reason="reader_user_paused")
        _READER_STORE.set_reader_state(sid, "paused", reason="reader_user_paused")
    if _tts_is_playing():
        reason = "barge_in_triggered" if src in ("voice_any", "stt_any") else "reader_user_interrupt"
        _request_tts_stop(
            reason=reason,
            keyword=key,
            detail=f"triggered:{src or 'voice_cmd'}",
            session_id=sid,
        )
        return True
    return bool(reader_active)


def _voice_chat_bridge_process_items(session_id: str, items: list[dict]) -> int:
    sid = _safe_session_id(session_id or "default")
    if not isinstance(items, list):
        items = []
    processed = 0
    chat_min_words = max(1, _int_env("DIRECT_CHAT_STT_CHAT_MIN_WORDS", 2))
    merged_window_sec = max(0.4, _float_env("DIRECT_CHAT_STT_BRIDGE_MERGE_WINDOW_SEC", 2.4))
    chat_chunks: list[tuple[str, float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip().lower()
        if kind == "voice_cmd":
            cmd = str(item.get("cmd", "")).strip().lower()
            text = str(item.get("text", "")).strip()
            if not cmd and text:
                cmd = _voice_command_kind(text)
            if cmd != "pause":
                continue
            target_sid = _recent_ui_session_id() or sid
            source = str(item.get("source", "voice_cmd")).strip().lower() or "voice_cmd"
            if _apply_voice_pause_interrupt(target_sid, source=source, keyword=text):
                if target_sid != sid and target_sid and target_sid != "default":
                    try:
                        _STT_MANAGER.claim_owner(target_sid)
                        sid = target_sid
                    except Exception:
                        pass
                processed += 1
            continue
        if kind != "chat_text":
            continue
        text = _stt_voice_text_normalize(str(item.get("text", "")).strip())
        if not text:
            continue
        drop_reason = _stt_chat_drop_reason(text, min_words_chat=chat_min_words)
        # Keep ultra-short fragments to merge with adjacent dictation chunks
        # from the same phrase (for example "estados" + "unidos").
        if drop_reason and drop_reason != "chat_too_few_words":
            continue
        try:
            ts = float(item.get("ts", 0.0) or 0.0)
        except Exception:
            ts = 0.0
        chat_chunks.append((text, ts))
    if chat_chunks:
        max_ts = max((float(ts or 0.0) for _text, ts in chat_chunks), default=0.0)
        if max_ts > 0.0:
            chunks = [(t, ts) for t, ts in chat_chunks if float(ts or 0.0) <= 0.0 or (max_ts - float(ts or 0.0)) <= merged_window_sec]
        else:
            chunks = list(chat_chunks)
        chunks = chunks[-6:]
        merged_parts: list[str] = []
        for chunk_text, _chunk_ts in chunks:
            part = str(chunk_text or "").strip()
            if not part:
                continue
            if not merged_parts:
                merged_parts.append(part)
                continue
            prev = str(merged_parts[-1])
            prev_l = prev.lower()
            part_l = part.lower()
            if part_l == prev_l or prev_l.endswith(part_l):
                continue
            if part_l.startswith(prev_l):
                merged_parts[-1] = part
                continue
            merged_parts.append(part)
        latest_chat_text = " ".join(merged_parts).strip()
        latest_chat_ts = max((float(ts or 0.0) for _t, ts in chunks), default=0.0)
        if latest_chat_text:
            _voice_chat_pending_put(sid, latest_chat_text, ts=latest_chat_ts)
    else:
        latest_chat_text = ""
        latest_chat_ts = 0.0
    pending = _voice_chat_pending_get(sid)
    pending_text = _stt_voice_text_normalize(str(pending.get("text", "")).strip()) if isinstance(pending, dict) else ""
    pending_ts = float(pending.get("ts", 0.0) or 0.0) if isinstance(pending, dict) else 0.0
    if pending_text and _stt_chat_drop_reason(pending_text, min_words_chat=chat_min_words):
        _voice_chat_pending_clear(sid)
        pending_text = ""
    if pending_text and _voice_chat_pending_ready(sid, pending or {}):
        target_sid = _recent_ui_session_id() or sid
        if _voice_chat_submit_backend(target_sid, pending_text, ts=pending_ts):
            _voice_chat_pending_clear(sid)
            if target_sid != sid and target_sid and target_sid != "default":
                try:
                    _STT_MANAGER.claim_owner(target_sid)
                    sid = target_sid
                except Exception:
                    pass
            processed += 1
    return processed


def _voice_chat_bridge_loop() -> None:
    while not _VOICE_CHAT_BRIDGE_STOP.is_set():
        try:
            if (not _voice_enabled()) or (not _voice_server_chat_bridge_enabled()) or _DIRECT_CHAT_HTTP_PORT <= 0:
                _VOICE_CHAT_BRIDGE_STOP.wait(0.35)
                continue
            st = _STT_MANAGER.status()
            sid = _safe_session_id(str(st.get("stt_owner_session_id", "default") or "default"))
            if not sid:
                sid = "default"
            if not bool(st.get("stt_enabled", False)) or not bool(st.get("stt_chat_enabled", False)):
                with _VOICE_CHAT_PENDING_LOCK:
                    _VOICE_CHAT_PENDING_BY_SESSION.clear()
                _VOICE_CHAT_BRIDGE_STOP.wait(0.35)
                continue
            batch_limit = max(1, min(24, _int_env("DIRECT_CHAT_STT_BRIDGE_POLL_LIMIT", 12)))
            items = _STT_MANAGER.poll(session_id=sid, limit=batch_limit)
            _voice_chat_bridge_process_items(sid, items)
        except Exception:
            pass
        _VOICE_CHAT_BRIDGE_STOP.wait(0.22)


def _start_voice_chat_bridge() -> None:
    if (not _voice_server_chat_bridge_enabled()) or _DIRECT_CHAT_HTTP_PORT <= 0:
        return
    with _VOICE_CHAT_BRIDGE_LOCK:
        global _VOICE_CHAT_BRIDGE_THREAD
        th = _VOICE_CHAT_BRIDGE_THREAD
        if th is not None and th.is_alive():
            return
        _VOICE_CHAT_BRIDGE_STOP.clear()
        _VOICE_CHAT_BRIDGE_THREAD = threading.Thread(target=_voice_chat_bridge_loop, daemon=True, name="voice-chat-bridge")
        _VOICE_CHAT_BRIDGE_THREAD.start()


def _stop_voice_chat_bridge() -> None:
    global _VOICE_CHAT_BRIDGE_THREAD
    with _VOICE_CHAT_BRIDGE_LOCK:
        _VOICE_CHAT_BRIDGE_STOP.set()
        th = _VOICE_CHAT_BRIDGE_THREAD
        _VOICE_CHAT_BRIDGE_THREAD = None
    if th is not None:
        try:
            th.join(timeout=1.5)
        except Exception:
            pass


atexit.register(_stop_voice_chat_bridge)


def _sync_stt_with_voice(enabled: bool, session_id: str = "") -> None:
    try:
        state = _load_voice_state()
        should_run = bool(bool(enabled) or bool(state.get("stt_chat_enabled", False)))
        if should_run:
            _STT_MANAGER.enable(session_id=session_id)
            _start_voice_chat_bridge()
            return
        _stop_bargein_monitor()
        _stop_voice_chat_bridge()
        _STT_MANAGER.disable()
    except Exception as e:
        print(f"[stt] sync_failed:{e}", file=sys.stderr)


def _stt_list_input_devices() -> list[dict]:
    try:
        return _STT_MANAGER.list_devices()
    except Exception:
        return []


def _set_stt_runtime_config(
    *,
    stt_device: str | None = None,
    stt_command_only: bool | None = None,
    stt_chat_enabled: bool | None = None,
    stt_debug: bool | None = None,
    stt_min_chars: int | None = None,
    stt_no_audio_timeout_sec: float | None = None,
    stt_rms_threshold: float | None = None,
    stt_segment_rms_threshold: float | None = None,
    stt_barge_rms_threshold: float | None = None,
    stt_barge_any: bool | None = None,
    stt_barge_any_cooldown_ms: int | None = None,
    stt_preamp_gain: float | None = None,
    stt_agc_enabled: bool | None = None,
    stt_agc_target_rms: float | None = None,
) -> dict:
    with _VOICE_LOCK:
        state = _load_voice_state()
        if stt_device is not None:
            state["stt_device"] = str(stt_device).strip()
        if stt_command_only is not None:
            state["stt_command_only"] = bool(stt_command_only)
        if stt_chat_enabled is not None:
            state["stt_chat_enabled"] = bool(stt_chat_enabled)
        if stt_debug is not None:
            state["stt_debug"] = bool(stt_debug)
        if stt_min_chars is not None:
            state["stt_min_chars"] = max(1, int(stt_min_chars))
        if stt_no_audio_timeout_sec is not None:
            state["stt_no_audio_timeout_sec"] = max(1.0, float(stt_no_audio_timeout_sec))
        if stt_rms_threshold is not None:
            # Backward-compatible command: set both thresholds with the same value.
            thr = max(0.001, float(stt_rms_threshold))
            state["stt_rms_threshold"] = thr
            state["stt_segment_rms_threshold"] = max(0.0005, thr)
            state["stt_barge_rms_threshold"] = max(0.001, thr)
        if stt_segment_rms_threshold is not None:
            state["stt_segment_rms_threshold"] = max(0.0005, float(stt_segment_rms_threshold))
        if stt_barge_rms_threshold is not None:
            barge_thr = max(0.001, float(stt_barge_rms_threshold))
            state["stt_barge_rms_threshold"] = barge_thr
            # Keep legacy field aligned with barge threshold for older clients.
            state["stt_rms_threshold"] = barge_thr
        if stt_barge_any is not None:
            state["stt_barge_any"] = bool(stt_barge_any)
        if stt_barge_any_cooldown_ms is not None:
            state["stt_barge_any_cooldown_ms"] = max(300, int(stt_barge_any_cooldown_ms))
        if stt_preamp_gain is not None:
            state["stt_preamp_gain"] = max(0.05, float(stt_preamp_gain))
        if stt_agc_enabled is not None:
            state["stt_agc_enabled"] = bool(stt_agc_enabled)
        if stt_agc_target_rms is not None:
            state["stt_agc_target_rms"] = max(0.01, min(0.30, float(stt_agc_target_rms)))
        state["stt_rms_threshold"] = _stt_legacy_rms_threshold_from_state(state)
        state["stt_segment_rms_threshold"] = _stt_segment_rms_threshold_from_state(state)
        state["stt_barge_rms_threshold"] = _stt_barge_rms_threshold_from_state(state)
        _save_voice_state(state)
    os.environ["DIRECT_CHAT_STT_DEVICE"] = str(state.get("stt_device", "")).strip()
    try:
        should_run = bool(state.get("enabled", False) or state.get("stt_chat_enabled", False))
        owner = str(_STT_MANAGER.status().get("stt_owner_session_id", "")).strip()
        sid = _safe_session_id(owner or "")
        if should_run:
            _sync_stt_with_voice(enabled=bool(state.get("enabled", False)), session_id=(sid if sid != "default" else ""))
            _STT_MANAGER.restart()
        else:
            _sync_stt_with_voice(enabled=False, session_id="")
    except Exception:
        pass
    return state


def _reader_voice_any_barge_target_active(session_id: str) -> bool:
    sid = _safe_session_id(session_id)
    if not sid:
        return False
    try:
        st = _READER_STORE.get_session(sid, include_chunks=False)
    except Exception:
        return False
    if not bool(st.get("ok", False)):
        return False
    reader_state = str(st.get("reader_state", "") or "").strip().lower()
    try:
        continuous = bool(_READER_STORE.is_continuous(sid))
    except Exception:
        continuous = False
    return bool(continuous or reader_state == "reading")


def _alltalk_base_url() -> str:
    return str(os.environ.get("DIRECT_CHAT_ALLTALK_URL", "http://127.0.0.1:7851")).strip().rstrip("/")


def _alltalk_health_timeout_sec(default: float = 1.5) -> float:
    raw = str(os.environ.get("DIRECT_CHAT_ALLTALK_HEALTH_TIMEOUT_SEC", str(default))).strip()
    try:
        return max(0.2, float(raw))
    except Exception:
        return max(0.2, float(default))


def _alltalk_health_path() -> str:
    path = str(os.environ.get("DIRECT_CHAT_ALLTALK_HEALTH_PATH", "/ready")).strip()
    if not path.startswith("/"):
        path = "/" + path
    return path


def _alltalk_health_paths() -> list[str]:
    raw = str(os.environ.get("DIRECT_CHAT_ALLTALK_HEALTH_PATHS", "")).strip()
    items = [p.strip() for p in raw.split(",") if p.strip()]
    if not items:
        items = [_alltalk_health_path(), "/health", "/ready", "/api/health", "/"]
    out: list[str] = []
    for item in items:
        p = item if item.startswith("/") else f"/{item}"
        if p not in out:
            out.append(p)
    return out


def _alltalk_tts_path() -> str:
    path = str(os.environ.get("DIRECT_CHAT_ALLTALK_TTS_PATH", "/api/tts-generate")).strip()
    if not path.startswith("/"):
        path = "/" + path
    return path


def _alltalk_tts_timeout_sec(default: float = 15.0) -> float:
    raw = str(os.environ.get("DIRECT_CHAT_ALLTALK_TIMEOUT_SEC", str(default))).strip()
    try:
        return max(1.0, float(raw))
    except Exception:
        return max(1.0, float(default))


def _alltalk_health_probe(timeout_s: float | None = None) -> dict:
    timeout = _alltalk_health_timeout_sec(default=float(timeout_s or 1.5))
    base_url = _alltalk_base_url()
    paths = _alltalk_health_paths()
    last_err = "health_error:unknown"
    used_path = paths[0] if paths else _alltalk_health_path()
    for health_path in paths:
        req = Request(url=base_url + health_path, method="GET")
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                status = int(getattr(resp, "status", 200))
            if status != 200:
                last_err = f"health_http_{status}@{health_path}"
                used_path = health_path
                continue
            marker = "ok"
            try:
                data = json.loads(body or "{}")
                marker = str(data.get("status") or data.get("message") or "ok")
            except Exception:
                marker = "ok"
            return {
                "ok": True,
                "detail": marker,
                "checked_ts": time.time(),
                "backend": "alltalk",
                "base_url": base_url,
                "health_path": health_path,
                "timeout_s": float(timeout),
            }
        except HTTPError as e:
            last_err = f"health_http_error:{e.code}@{health_path}"
            used_path = health_path
            continue
        except URLError as e:
            last_err = f"health_url_error:{e.reason}@{health_path}"
            used_path = health_path
            continue
        except Exception as e:
            last_err = f"health_error:{e}@{health_path}"
            used_path = health_path
            continue
    return {
        "ok": False,
        "detail": last_err,
        "checked_ts": time.time(),
        "backend": "alltalk",
        "base_url": base_url,
        "health_path": used_path,
        "timeout_s": float(timeout),
    }


def _alltalk_health_cached(force: bool = False, timeout_s: float | None = None) -> dict:
    timeout = _alltalk_health_timeout_sec(default=float(timeout_s or 1.5))
    ok_ttl = max(0.1, float(os.environ.get("DIRECT_CHAT_TTS_HEALTH_CACHE_OK_SEC", "2.0")))
    fail_ttl = max(0.1, float(os.environ.get("DIRECT_CHAT_TTS_HEALTH_CACHE_FAIL_SEC", "0.8")))
    now = time.time()
    with _TTS_HEALTH_LOCK:
        cached = dict(_TTS_HEALTH_CACHE)
        age = max(0.0, now - float(cached.get("checked_ts", 0.0) or 0.0))
        cached_ok = cached.get("ok")
        cached_timeout = float(cached.get("timeout_s", 0.0) or 0.0)
        if (not force) and cached_ok is not None and abs(cached_timeout - timeout) < 0.001:
            ttl = ok_ttl if bool(cached_ok) else fail_ttl
            if age <= ttl:
                return cached

    fresh = _alltalk_health_probe(timeout_s=timeout)
    with _TTS_HEALTH_LOCK:
        _TTS_HEALTH_CACHE.update(fresh)
        return dict(_TTS_HEALTH_CACHE)


def _alltalk_health(timeout_s: float = 0.5) -> tuple[bool, str]:
    data = _alltalk_health_cached(force=False, timeout_s=timeout_s)
    return bool(data.get("ok", False)), str(data.get("detail", "health_unknown"))


def _tts_fallback_order() -> list[str]:
    raw = str(os.environ.get("DIRECT_CHAT_TTS_FALLBACK_ORDER", "espeak-ng,espeak,pico2wave")).strip()
    items = [x.strip() for x in raw.split(",") if x.strip()]
    out: list[str] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _tts_fallback_available_tools() -> list[str]:
    tools: list[str] = []
    for name in _tts_fallback_order():
        if shutil.which(name):
            tools.append(name)
    return tools


def _tts_speak_local_fallback(text: str) -> tuple[Path | None, str]:
    if not _env_flag("DIRECT_CHAT_TTS_FALLBACK_ENABLED", True):
        return None, "fallback_disabled"
    msg = str(text or "").strip()
    if not msg:
        return None, "fallback_empty_text"
    tools = _tts_fallback_available_tools()
    if not tools:
        return None, "fallback_no_local_engine"
    voice = str(os.environ.get("DIRECT_CHAT_TTS_FALLBACK_VOICE", "es")).strip() or "es"
    timeout_s = max(1.0, float(os.environ.get("DIRECT_CHAT_TTS_FALLBACK_TIMEOUT_SEC", "8")))
    out = Path("/tmp") / f"openclaw_tts_fallback_{int(time.time() * 1000)}.wav"
    errs: list[str] = []
    for tool in tools:
        if tool in ("espeak", "espeak-ng"):
            cmd = [tool, "-v", voice, "-w", str(out), msg]
        elif tool == "pico2wave":
            cmd = [tool, "-w", str(out), msg]
        else:
            errs.append(f"{tool}:unsupported")
            continue
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            if proc.returncode == 0 and out.exists() and out.stat().st_size > 64:
                return out, f"ok_fallback_{tool}"
            err = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
            errs.append(f"{tool}:rc{proc.returncode}:{err[:120]}")
        except Exception as e:
            errs.append(f"{tool}:{e}")
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass
    detail = ";".join(errs)[:280] if errs else "fallback_failed"
    return None, f"fallback_failed:{detail}"


def _voice_diagnostics(detail: str = "") -> str:
    health = _alltalk_health_cached(force=False)
    backend = str(health.get("backend", "alltalk") or "alltalk")
    base_url = str(health.get("base_url", _alltalk_base_url()) or _alltalk_base_url())
    health_path = str(health.get("health_path", _alltalk_health_path()) or _alltalk_health_path())
    timeout_s = float(health.get("timeout_s", _alltalk_health_timeout_sec()) or _alltalk_health_timeout_sec())
    hdetail = str(health.get("detail", "")).strip()
    fallback_tools = ",".join(_tts_fallback_available_tools()) or "none"
    extra = str(detail or hdetail or "unknown").strip()
    return (
        f"backend={backend} url={base_url} health={health_path} timeout={timeout_s:.2f}s "
        f"detail={extra} fallback={fallback_tools}"
    )


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "]",
    flags=re.UNICODE,
)


def _clean_for_tts(text: str) -> str:
    msg = html.unescape(str(text or ""))
    if not msg.strip():
        return ""
    msg = msg.replace("\r\n", "\n").replace("\r", "\n")
    msg = re.sub(r"```[\s\S]*?```", " ", msg)
    msg = re.sub(r"`([^`]*)`", r"\1", msg)
    msg = re.sub(r"\[([^\]]+)\]\((?:https?://|www\.)[^\)]+\)", r"\1", msg)
    msg = re.sub(r"(https?://\S+|www\.\S+)", " ", msg)
    msg = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", msg)
    msg = re.sub(r"#(?=\w)", "", msg)
    msg = re.sub(r"(?m)^\s*>\s?", "", msg)
    msg = re.sub(r"[*_~]+", "", msg)
    msg = _EMOJI_RE.sub(" ", msg)

    lines = []
    saw_blank = False
    for raw in msg.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            if lines and not saw_blank:
                lines.append("")
            saw_blank = True
            continue
        lines.append(line)
        saw_blank = False
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def _split_hard_limit(text: str, max_len: int) -> list[str]:
    out: list[str] = []
    rest = str(text or "").strip()
    while rest:
        if len(rest) <= max_len:
            out.append(rest)
            break
        cut = rest.rfind(" ", 0, max_len + 1)
        if cut < int(max_len * 0.5):
            cut = max_len
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return out


def _chunk_text_for_tts(text: str, max_len: int = 250) -> list[str]:
    cleaned = _clean_for_tts(text)
    if not cleaned:
        return []
    max_len = max(80, int(max_len))
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    if not paragraphs:
        paragraphs = [cleaned]

    chunks: list[str] = []
    for para in paragraphs:
        current = ""
        sentence_parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
        if not sentence_parts:
            sentence_parts = [para]

        for sentence in sentence_parts:
            comma_parts = [sentence]
            if len(sentence) > max_len:
                comma_parts = [p.strip() for p in re.split(r"(?<=,)\s+", sentence) if p.strip()]
                if not comma_parts:
                    comma_parts = [sentence]

            for part in comma_parts:
                if len(part) > max_len:
                    for hard in _split_hard_limit(part, max_len):
                        if current:
                            chunks.append(current)
                            current = ""
                        chunks.append(hard)
                    continue
                if not current:
                    current = part
                elif len(current) + 1 + len(part) <= max_len:
                    current = f"{current} {part}"
                else:
                    chunks.append(current)
                    current = part

        if current:
            chunks.append(current)
    return chunks


def _set_voice_status(stream_id: int, ok: bool | None, detail: str) -> None:
    global _VOICE_LAST_STATUS
    _reader_autocommit_finalize(stream_id, ok, detail=str(detail or ""))
    with _TTS_STREAM_LOCK:
        if stream_id != _TTS_STREAM_ID:
            return
    _VOICE_LAST_STATUS = {"ok": ok, "detail": str(detail), "ts": time.time(), "stream_id": int(stream_id)}


def _stop_playback_process() -> None:
    global _TTS_PLAYBACK_PROC
    with _TTS_STREAM_LOCK:
        proc = _TTS_PLAYBACK_PROC
        _TTS_PLAYBACK_PROC = None
    _tts_touch()
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except Exception:
                proc.kill()
    except Exception:
        return


def _pop_tts_stop_reason(stream_id: int, default: str = "playback_interrupted") -> str:
    if stream_id <= 0:
        return str(default or "playback_interrupted")
    with _TTS_STREAM_LOCK:
        reason = str(_TTS_STOP_REASON_BY_STREAM.pop(int(stream_id), "")).strip()
    return reason or str(default or "playback_interrupted")


def _start_new_tts_stream() -> tuple[int, threading.Event]:
    global _TTS_STREAM_ID, _TTS_STOP_EVENT, _TTS_ACTIVE_QUEUE
    prev_stream_id = 0
    with _TTS_STREAM_LOCK:
        prev_event = _TTS_STOP_EVENT
        prev_queue = _TTS_ACTIVE_QUEUE
        prev_stream_id = int(_TTS_STREAM_ID or 0)
        _TTS_STREAM_ID += 1
        stream_id = _TTS_STREAM_ID
        stop_event = threading.Event()
        _TTS_STOP_EVENT = stop_event
        _TTS_ACTIVE_QUEUE = None

    if prev_stream_id > 0:
        with _TTS_STREAM_LOCK:
            _TTS_STOP_REASON_BY_STREAM[int(prev_stream_id)] = "stream_replaced"
            _TTS_PLAYBACK_MONO_BY_STREAM.pop(int(prev_stream_id), None)

    prev_event.set()
    _stop_playback_process()

    if prev_queue is not None:
        try:
            while True:
                item = prev_queue.get_nowait()
                if isinstance(item, Path):
                    try:
                        item.unlink(missing_ok=True)
                    except Exception:
                        pass
        except queue.Empty:
            pass
        try:
            prev_queue.put_nowait(None)
        except Exception:
            pass
    return stream_id, stop_event


def _set_tts_queue(stream_id: int, tts_queue: queue.Queue | None) -> None:
    global _TTS_ACTIVE_QUEUE
    with _TTS_STREAM_LOCK:
        if stream_id == _TTS_STREAM_ID:
            _TTS_ACTIVE_QUEUE = tts_queue


def _mark_tts_stream_playback_start(stream_id: int) -> None:
    if int(stream_id or 0) <= 0:
        return
    now_mono = time.monotonic()
    with _TTS_STREAM_LOCK:
        _TTS_PLAYBACK_MONO_BY_STREAM[int(stream_id)] = float(now_mono)


def _clear_tts_stream_playback_start(stream_id: int) -> None:
    if int(stream_id or 0) <= 0:
        return
    with _TTS_STREAM_LOCK:
        _TTS_PLAYBACK_MONO_BY_STREAM.pop(int(stream_id), None)


def _play_audio_blocking(path: Path, stop_event: threading.Event) -> tuple[bool, str]:
    global _TTS_PLAYBACK_PROC
    if _env_flag("DIRECT_CHAT_TTS_DRY_RUN", False):
        if stop_event.is_set():
            return False, "playback_interrupted"
        _tts_touch()
        time.sleep(0.01)
        if stop_event.is_set():
            return False, "playback_interrupted"
        return True, "ok_player_dry_run"
    paplay = shutil.which("paplay")
    ffplay = shutil.which("ffplay")
    if paplay:
        cmd = [paplay, str(path)]
        player = "paplay"
    elif ffplay:
        cmd = [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        player = "ffplay"
    else:
        return False, "no_audio_player"

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return False, f"player_spawn_failed:{e}"

    try:
        with _TTS_STREAM_LOCK:
            if stop_event.is_set():
                try:
                    proc.terminate()
                except Exception:
                    pass
                return False, "playback_interrupted"
            _TTS_PLAYBACK_PROC = proc
            _tts_touch()

        while True:
            rc = proc.poll()
            if rc is not None:
                if rc == 0:
                    return True, f"ok_player_{player}"
                return False, f"player_exit_{rc}:{player}"
            if stop_event.is_set():
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                return False, "playback_interrupted"
            time.sleep(0.05)
    except Exception as e:
        return False, f"player_runtime_failed:{e}"
    finally:
        with _TTS_STREAM_LOCK:
            if _TTS_PLAYBACK_PROC is proc:
                _TTS_PLAYBACK_PROC = None
        _tts_touch()


def _tts_speak_alltalk(text: str, state: dict) -> tuple[Path | None, str]:
    msg = str(text or "").strip()
    if not msg:
        return None, "empty_text"
    if _env_flag("DIRECT_CHAT_ALLTALK_SKIP_WHEN_UNHEALTHY", True):
        h = _alltalk_health_cached(force=False, timeout_s=_alltalk_health_timeout_sec())
        if not bool(h.get("ok", False)):
            return None, f"alltalk_unhealthy:{_voice_diagnostics(str(h.get('detail', 'health_failed')))}"

    def _alltalk_character_voice() -> str:
        explicit = str(os.environ.get("DIRECT_CHAT_ALLTALK_CHARACTER_VOICE", "")).strip()
        if explicit:
            return explicit
        speaker_wav = str(state.get("speaker_wav", "")).strip()
        if speaker_wav:
            return Path(speaker_wav).name
        speaker = str(state.get("speaker", "")).strip()
        if speaker and speaker.lower().endswith(".wav"):
            return speaker
        return str(os.environ.get("DIRECT_CHAT_ALLTALK_DEFAULT_VOICE", "female_01.wav")).strip() or "female_01.wav"

    def _save_tmp_wav(content: bytes) -> Path:
        out = Path("/tmp") / f"openclaw_alltalk_{int(time.time() * 1000)}.wav"
        out.write_bytes(content)
        return out

    default_voice = str(os.environ.get("DIRECT_CHAT_ALLTALK_DEFAULT_VOICE", "female_01.wav")).strip() or "female_01.wav"
    primary_voice = _alltalk_character_voice()
    narrator_voice = str(os.environ.get("DIRECT_CHAT_ALLTALK_NARRATOR_VOICE", "")).strip()
    base_payload = {
        "text_input": msg,
        "language": str(os.environ.get("DIRECT_CHAT_ALLTALK_LANGUAGE", "es")).strip() or "es",
        "text_filtering": str(os.environ.get("DIRECT_CHAT_ALLTALK_TEXT_FILTERING", "standard")).strip() or "standard",
        "narrator_enabled": str(_env_flag("DIRECT_CHAT_ALLTALK_NARRATOR_ENABLED", False)).lower(),
        "text_not_inside": str(os.environ.get("DIRECT_CHAT_ALLTALK_TEXT_NOT_INSIDE", "character")).strip() or "character",
        "output_file_name": str(os.environ.get("DIRECT_CHAT_ALLTALK_OUTPUT_NAME", "openclaw_direct_chat")).strip()
        or "openclaw_direct_chat",
        "output_file_timestamp": str(_env_flag("DIRECT_CHAT_ALLTALK_OUTPUT_TIMESTAMP", True)).lower(),
        "autoplay": "false",
        "autoplay_volume": str(os.environ.get("DIRECT_CHAT_ALLTALK_AUTOPLAY_VOLUME", "1.0")).strip() or "1.0",
    }
    timeout_s = _alltalk_tts_timeout_sec(default=15.0)
    base_url = _alltalk_base_url() + "/"
    req_url = _alltalk_base_url() + _alltalk_tts_path()

    voices_to_try = [primary_voice]
    if default_voice and default_voice not in voices_to_try:
        voices_to_try.append(default_voice)

    try:
        last_http_detail = ""
        for idx, voice_name in enumerate(voices_to_try):
            payload = dict(base_payload)
            payload["character_voice_gen"] = voice_name
            payload["narrator_voice_gen"] = narrator_voice or voice_name
            payload = {k: v for k, v in payload.items() if str(v).strip()}

            resp = requests.post(req_url, data=payload, timeout=max(2.0, timeout_s))
            if resp.status_code >= 400:
                detail = (resp.text or "")[:220].replace("\n", " ")
                last_http_detail = f"alltalk_http_error:{resp.status_code}:{detail}"
                print(f"[voice] AllTalk HTTP {resp.status_code} (voice={voice_name}): {detail}", file=sys.stderr)
                if idx + 1 < len(voices_to_try):
                    continue
                return None, last_http_detail

            ctype = str(resp.headers.get("Content-Type", "")).lower()
            if "application/json" in ctype:
                info = resp.json() if resp.content else {}
                if not isinstance(info, dict):
                    if idx + 1 < len(voices_to_try):
                        continue
                    return None, "alltalk_invalid_json"
                out_url = str(info.get("output_file_url") or info.get("output_cache_url") or "").strip()
                if not out_url:
                    if idx + 1 < len(voices_to_try):
                        continue
                    return None, f"alltalk_no_output_url:{info.get('status', 'unknown')}"
                download_url = urllib.parse.urljoin(base_url, out_url)
                audio_resp = requests.get(download_url, timeout=max(2.0, timeout_s))
                audio_resp.raise_for_status()
                audio_bytes = audio_resp.content
            else:
                audio_bytes = resp.content

            if not audio_bytes:
                if idx + 1 < len(voices_to_try):
                    continue
                return None, "alltalk_empty_audio"
            return _save_tmp_wav(audio_bytes), f"ok_voice_{voice_name}"

        if last_http_detail:
            return None, last_http_detail
        return None, "alltalk_retry_exhausted"
    except requests.exceptions.RequestException as e:
        print(f"[voice] AllTalk request failed: {e}", file=sys.stderr)
        return None, f"alltalk_request_failed:{e}"
    except json.JSONDecodeError as e:
        print(f"[voice] AllTalk JSON decode failed: {e}", file=sys.stderr)
        return None, f"alltalk_json_decode_failed:{e}"
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="ignore")[:220]
        except Exception:
            detail = ""
        return None, f"alltalk_http_error:{e.code}:{detail}"
    except URLError as e:
        return None, f"alltalk_url_error:{e.reason}"
    except Exception as e:
        return None, f"alltalk_request_error:{e}"


def _speak_reply_async(text: str) -> int:
    stream_id, stop_event = _start_new_tts_stream()
    _set_voice_status(stream_id, None, "queued")

    chunks = _chunk_text_for_tts(text, max_len=_int_env("DIRECT_CHAT_TTS_CHUNK_MAX_LEN", 250))
    if not chunks:
        _set_voice_status(stream_id, False, "empty_text")
        return stream_id

    if _env_flag("DIRECT_CHAT_TTS_DRY_RUN", False):
        def _run_dry() -> None:
            global _TTS_PLAYING_STREAM_ID
            with _TTS_STREAM_LOCK:
                if stream_id != _TTS_STREAM_ID:
                    return
                _TTS_PLAYING_STREAM_ID = stream_id
                _TTS_PLAYING_EVENT.set()
            _tts_touch()
            interrupted = False
            try:
                for _ in chunks:
                    if stop_event.is_set():
                        interrupted = True
                        break
                    _tts_touch()
                    time.sleep(0.01)
            finally:
                with _TTS_STREAM_LOCK:
                    if _TTS_PLAYING_STREAM_ID == stream_id:
                        _TTS_PLAYING_STREAM_ID = 0
                        _TTS_PLAYING_EVENT.clear()
                _tts_touch()
            if interrupted:
                _set_voice_status(stream_id, False, _pop_tts_stop_reason(stream_id))
                return
            _set_voice_status(stream_id, True, "ok_player_dry_run")

        try:
            th = threading.Thread(target=_run_dry, daemon=True)
            th.start()
        except Exception:
            _set_voice_status(stream_id, False, "tts_thread_start_failed")
        return stream_id

    def _run() -> None:
        global _TTS_PLAYING_STREAM_ID
        with _TTS_STREAM_LOCK:
            if stream_id != _TTS_STREAM_ID:
                return
            _TTS_PLAYING_STREAM_ID = stream_id
            _TTS_PLAYING_EVENT.set()
        _tts_touch()
        _start_bargein_monitor(stream_id, stop_event)

        state = _load_voice_state()
        tts_queue: queue.Queue[Path | None] = queue.Queue(maxsize=max(1, _int_env("DIRECT_CHAT_TTS_QUEUE_SIZE", 3)))
        _set_tts_queue(stream_id, tts_queue)

        producer_error = {"detail": ""}

        def _producer() -> None:
            try:
                for chunk in chunks:
                    if stop_event.is_set():
                        return
                    wav_path, detail = _tts_speak_alltalk(chunk, state)
                    if wav_path is None:
                        fb_path, fb_detail = _tts_speak_local_fallback(chunk)
                        if fb_path is None:
                            producer_error["detail"] = f"{detail}|{fb_detail}"
                            return
                        wav_path, detail = fb_path, fb_detail
                    while not stop_event.is_set():
                        try:
                            tts_queue.put(wav_path, timeout=0.2)
                            break
                        except queue.Full:
                            continue
            finally:
                while True:
                    try:
                        tts_queue.put(None, timeout=0.2)
                        return
                    except queue.Full:
                        if stop_event.is_set():
                            try:
                                stale = tts_queue.get_nowait()
                                if isinstance(stale, Path):
                                    try:
                                        stale.unlink(missing_ok=True)
                                    except Exception:
                                        pass
                            except queue.Empty:
                                pass

        producer_thread = threading.Thread(target=_producer, daemon=True)
        producer_thread.start()

        played_any = False
        last_detail = "ok_stream"
        interrupted = False
        playback_started = False

        try:
            while True:
                try:
                    item = tts_queue.get(timeout=0.2)
                except queue.Empty:
                    if producer_thread.is_alive():
                        continue
                    if stop_event.is_set():
                        interrupted = True
                        break
                    if producer_error["detail"]:
                        break
                    continue

                if item is None:
                    if stop_event.is_set():
                        interrupted = True
                    break

                if not playback_started:
                    playback_started = True
                    _mark_tts_stream_playback_start(stream_id)
                ok, detail = _play_audio_blocking(item, stop_event)
                try:
                    item.unlink(missing_ok=True)
                except Exception:
                    pass

                if not ok:
                    if detail == "playback_interrupted":
                        interrupted = True
                        break
                    producer_error["detail"] = producer_error["detail"] or detail
                    break

                played_any = True
                last_detail = detail
        finally:
            producer_thread.join(timeout=1.0)
            _set_tts_queue(stream_id, None)
            _stop_bargein_monitor()
            _clear_tts_stream_playback_start(stream_id)
            with _TTS_STREAM_LOCK:
                if _TTS_PLAYING_STREAM_ID == stream_id:
                    _TTS_PLAYING_STREAM_ID = 0
                    _TTS_PLAYING_EVENT.clear()
            _tts_touch()

        if interrupted:
            _set_voice_status(stream_id, False, _pop_tts_stop_reason(stream_id))
            return
        if stop_event.is_set():
            _set_voice_status(stream_id, False, _pop_tts_stop_reason(stream_id))
            return
        if producer_error["detail"]:
            _set_voice_status(stream_id, False, producer_error["detail"])
            return
        if played_any:
            _set_voice_status(stream_id, True, last_detail)
            return
        _set_voice_status(stream_id, False, "tts_no_audio")

    try:
        th = threading.Thread(target=_run, daemon=True)
        th.start()
    except Exception:
        _set_voice_status(stream_id, False, "tts_thread_start_failed")
    return stream_id


def _maybe_speak_reply(reply: str, allowed_tools: set[str]) -> None:
    if "tts" not in allowed_tools:
        return
    if not _voice_enabled():
        return
    _speak_reply_async(reply)


def _wmctrl_list() -> dict[str, str]:
    if not shutil.which("wmctrl"):
        return {}
    try:
        proc = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=3)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        win_id = parts[0].strip()
        title = parts[3].strip()
        if win_id and title:
            out[win_id] = title
    return out


def _wmctrl_desktop_ids() -> set[int]:
    if not shutil.which("wmctrl"):
        return set()
    try:
        proc = subprocess.run(["wmctrl", "-d"], capture_output=True, text=True, timeout=3)
    except Exception:
        return set()
    ids: set[int] = set()
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            ids.add(int(parts[0]))
        except Exception:
            continue
    return ids


def _wmctrl_active_desktop() -> int | None:
    if not shutil.which("wmctrl"):
        return None
    try:
        proc = subprocess.run(["wmctrl", "-d"], capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "*":
            try:
                return int(parts[0])
            except Exception:
                return None
    return None


def _wmctrl_current_desktop() -> int | None:
    return _wmctrl_active_desktop()


def _pid_cmd_args(pid_raw: str) -> list[str]:
    try:
        pid = int(str(pid_raw).strip())
    except Exception:
        return []
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except Exception:
        return []
    return [p.decode("utf-8", errors="ignore").strip() for p in raw.split(b"\x00") if p]


def _profile_directory_from_args(args: list[str]) -> str:
    for i, arg in enumerate(args):
        if arg.startswith("--profile-directory="):
            return arg.split("=", 1)[1].strip().strip("'\"")
        if arg == "--profile-directory" and (i + 1) < len(args):
            return args[i + 1].strip().strip("'\"")
    merged = " ".join(args)
    m = re.search(r"--profile-directory=(.+?)(?:\s--|$)", merged)
    if m:
        return m.group(1).strip().strip("'\"")
    m = re.search(r"--profile-directory\s+(.+?)(?:\s--|$)", merged)
    if m:
        return m.group(1).strip().strip("'\"")
    return ""


def _pid_profile_directory(pid_raw: str) -> str:
    args = _pid_cmd_args(pid_raw)
    if not args:
        return ""
    return _profile_directory_from_args(args)


def _window_matches_profile(pid_raw: str, expected_profile: str | None) -> bool:
    expected = str(expected_profile or "").strip().lower()
    if not expected:
        return True
    got = _pid_profile_directory(pid_raw).strip().lower()
    return bool(got) and got == expected


def _xdotool_command(args: list[str], timeout: float = 3.0) -> tuple[int, str]:
    if not shutil.which("xdotool"):
        return 127, ""
    try:
        proc = subprocess.run(
            ["xdotool", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except Exception:
        return 1, ""


def _xdotool_window_geometry(win_id: str) -> tuple[int, int, int, int] | None:
    rc, out = _xdotool_command(["getwindowgeometry", "--shell", win_id], timeout=2.0)
    if rc != 0 or not out:
        return None
    vals: dict[str, int] = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().upper()
        v = v.strip()
        if k in ("X", "Y", "WIDTH", "HEIGHT"):
            try:
                vals[k] = int(v)
            except Exception:
                return None
    if all(k in vals for k in ("X", "Y", "WIDTH", "HEIGHT")):
        return vals["X"], vals["Y"], vals["WIDTH"], vals["HEIGHT"]
    return None


def _xdotool_active_window() -> str:
    rc, out = _xdotool_command(["getactivewindow"], timeout=1.5)
    if rc != 0 or not out:
        return ""
    wid = out.strip().lower()
    if wid.startswith("0x"):
        return wid
    try:
        return f"0x{int(wid):08x}"
    except Exception:
        return ""


def _wmctrl_window_desktop(win_id: str) -> int | None:
    if not shutil.which("wmctrl"):
        return None
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            wid, desk_raw, _pid, _host, _title = parts
            if wid.strip().lower() != win_id.strip().lower():
                continue
            try:
                return int(desk_raw)
            except Exception:
                return None
    except Exception:
        return None
    return None


def _wait_window_title_contains(win_id: str, terms: list[str], timeout_s: float = 8.0) -> tuple[bool, str]:
    deadline = time.time() + max(0.5, timeout_s)
    last = ""
    needles = [str(t).lower().strip() for t in terms if str(t).strip()]
    while time.time() < deadline:
        title = str(_wmctrl_list().get(win_id, "")).lower().strip()
        if title:
            last = title
        if title and any(n in title for n in needles):
            return True, title
        time.sleep(0.2)
    return False, last


def _site_title_looks_loaded(site_key: str | None, url: str, title: str) -> bool:
    sk = str(site_key or "").strip().lower()
    t = str(title or "").lower().strip()
    if not t:
        return False
    if any(tok in t for tok in ("about:blank", "new tab")):
        return False
    if sk == "youtube":
        if "youtube" not in t:
            return False
        # Provisional title while the page did not really render yet.
        if ("youtube.com/watch" in t or "youtube.com/results" in t) and (" - youtube" not in t):
            return False
        return True
    return True


def _find_new_profiled_chrome_window(
    before_ids: set[str], expected_profile: str | None, max_desktops: int = 16, timeout_s: float = 10.0
) -> tuple[str, int | None]:
    deadline = time.time() + max(0.8, timeout_s)
    while time.time() < deadline:
        for desk_idx in range(max_desktops):
            for wid, pid_raw, title in _wmctrl_windows_for_desktop(desk_idx):
                if wid in before_ids:
                    continue
                t = str(title).lower()
                if not any(tok in t for tok in ("chrome", "google", "gemini", "about:blank")):
                    continue
                if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
                    continue
                return wid, desk_idx
        time.sleep(0.12)
    return "", None


def _preferred_workspace_and_anchor(expected_profile: str | None = None) -> tuple[int | None, str]:
    active = _xdotool_active_window()
    if active:
        wins = _wmctrl_list()
        title = str(wins.get(active, "")).lower().strip()
        if "molbot direct chat" in title:
            desk = _wmctrl_window_desktop(active)
            if desk is not None:
                # Validate profile ownership when possible.
                if expected_profile:
                    for wid, pid_raw, _t in _wmctrl_windows_for_desktop(desk):
                        if wid.lower() == active.lower() and _window_matches_profile(pid_raw, expected_profile):
                            return desk, active
                else:
                    return desk, active

    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, ""
    return desk, ""


def _wmctrl_windows_for_desktop(desktop_idx: int) -> list[tuple[str, str, str]]:
    if not shutil.which("wmctrl"):
        return []
    out: list[tuple[str, str, str]] = []
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            wid, desk_raw, pid_raw, _host, title = parts
            try:
                desk = int(desk_raw)
            except Exception:
                continue
            if desk != desktop_idx:
                continue
            out.append((wid, pid_raw, title))
    except Exception:
        return []
    return out


def _open_gemini_in_current_workspace_via_ui(
    expected_profile: str | None = None, session_id: str | None = None
) -> tuple[bool, str]:
    # Workspace-safe open path using visible UI interactions only.
    workspace, _preferred_anchor = _preferred_workspace_and_anchor(expected_profile)
    if workspace is None:
        return False, "workspace_not_detected"

    wins = _wmctrl_windows_for_desktop(workspace)
    before_ids = {wid for wid, _, _ in wins}
    trusted_anchor, trusted_status = _trusted_or_autodetected_dc_anchor(expected_profile=expected_profile)
    anchor = trusted_anchor or ""
    if not anchor:
        return False, f"trusted_anchor_required ({trusted_status})"

    _xdotool_command(["windowactivate", anchor], timeout=2.5)
    time.sleep(0.22)
    _xdotool_command(["key", "--window", anchor, "ctrl+n"], timeout=2.0)

    target = ""
    for _ in range(80):
        now = _wmctrl_windows_for_desktop(workspace)
        for wid, pid_raw, title in now:
            if wid not in before_ids and ("chrome" in title.lower() or "google" in title.lower()):
                if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
                    continue
                target = wid
                break
        if target:
            break
        time.sleep(0.1)
    if not target:
        return False, "new_window_not_detected_from_anchor"

    _xdotool_command(["windowactivate", target], timeout=2.5)
    time.sleep(0.18)
    # Keep trained flow (Google -> Gemini), but verify Gemini actually loaded.
    for url in ("https://www.google.com/", "https://gemini.google.com/app"):
        _xdotool_command(["key", "--window", target, "ctrl+l"], timeout=2.0)
        time.sleep(0.08)
        _xdotool_command(
            ["type", "--delay", "18", "--clearmodifiers", "--window", target, url],
            timeout=8.0,
        )
        time.sleep(0.08)
        _xdotool_command(["key", "--window", target, "Return"], timeout=2.0)
        time.sleep(0.6)
        if "google.com" in url:
            _wait_window_title_contains(target, ["google"], timeout_s=4.0)
        if "gemini.google.com" in url:
            ok_title, _t = _wait_window_title_contains(target, ["gemini"], timeout_s=6.0)
            if not ok_title:
                cur_title = str(_wmctrl_list().get(target, ""))
                return False, f"gemini_not_loaded title={cur_title}"

    needs_login, snap = _gemini_window_requires_login(target)
    if needs_login:
        _wmctrl_close_window(target)
        return False, f"login_required workspace={workspace} target={target} snap={snap}"

    if session_id:
        title = _wmctrl_list().get(target, "")
        _record_browser_windows(
            session_id,
            [
                {
                    "win_id": target,
                    "title": title,
                    "url": "https://gemini.google.com/app",
                    "site_key": "gemini",
                    "ts": time.time(),
                }
            ],
        )
    return True, f"ui_open workspace={workspace} target={target}"


def _wmctrl_close_window(win_id: str) -> bool:
    if not shutil.which("wmctrl"):
        return False
    try:
        subprocess.run(
            ["wmctrl", "-ic", win_id],
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _gemini_window_requires_login(win_id: str) -> tuple[bool, str]:
    import_bin = shutil.which("import")
    if not import_bin:
        return False, ""
    snap_dir = Path.home() / ".openclaw" / "logs" / "gemini_write_screens"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = snap_dir / f"gemini_open_state_{int(time.time() * 1000)}.png"
    try:
        subprocess.run(
            [import_bin, "-window", win_id, str(snap)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
    except Exception:
        return False, ""
    needs_login = _ocr_contains_any(snap, ["iniciar sesión", "iniciar sesion", "sign in"])
    return needs_login, str(snap)


def _wmctrl_current_desktop_site_windows(
    site_key: str, expected_profile: str | None = None, desktop_idx: int | None = None
) -> list[tuple[str, str]]:
    if not shutil.which("wmctrl"):
        return []
    desk = desktop_idx if desktop_idx is not None else _wmctrl_current_desktop()
    if desk is None:
        return []
    token = "gemini" if site_key == "gemini" else ("chatgpt" if site_key == "chatgpt" else site_key)
    out: list[tuple[str, str]] = []
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            win_id, desktop_raw, pid_raw, _host, title = parts
            try:
                desktop_i = int(desktop_raw)
            except Exception:
                continue
            title_n = title.lower().strip()
            if desktop_i != desk:
                continue
            if token not in title_n:
                continue
            if "molbot direct chat" in title_n:
                continue
            if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
                continue
            out.append((win_id, title))
    except Exception:
        return []
    return out


def _wmctrl_window_pid(win_id: str) -> str | None:
    if not shutil.which("wmctrl"):
        return None
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 3:
                continue
            wid, _desktop_raw, pid_raw = parts[:3]
            if wid.lower().strip() == str(win_id).lower().strip():
                return pid_raw
    except Exception:
        return None
    return None


def _close_recent_site_window_fallback(site_key: str, expected_profile: str | None = None) -> tuple[bool, str]:
    prof = expected_profile if expected_profile is not None else _expected_profile_directory_for_site(site_key)
    wins = _wmctrl_current_desktop_site_windows(site_key, expected_profile=prof)
    if not wins:
        return False, "no_window_found_current_workspace"
    # wmctrl ordering is stable enough for "last listed" as a practical fallback.
    win_id, title = wins[-1]
    if _wmctrl_close_window(win_id):
        return True, title
    return False, "wmctrl_close_failed"


def _close_known_site_windows_in_current_workspace(max_windows: int = 12) -> tuple[int, list[str]]:
    closed = 0
    details: list[str] = []
    site_order = ("youtube", "chatgpt", "gemini", "wikipedia", "gmail")
    for _ in range(max(1, max_windows)):
        did_close = False
        for site_key in site_order:
            ok, detail = _close_recent_site_window_fallback(
                site_key, expected_profile=_expected_profile_directory_for_site(site_key)
            )
            if ok:
                closed += 1
                details.append(f"{site_key}:{detail[:90]}")
                did_close = True
                break
        if not did_close:
            break
    return closed, details


def _extract_youtube_transport_request(message: str) -> tuple[str, bool] | None:
    normalized = _normalize_text(message or "")
    if not any(t in normalized for t in SITE_CANONICAL_TOKENS.get("youtube", [])):
        return None
    # Keep search/open flows on the dedicated deterministic path.
    if any(t in normalized for t in ("busc", "search", "investig", "abr", "open", "primer video")):
        return None

    wants_pause = any(
        t in normalized
        for t in (
            "paus",
            "pause",
            "deten",
            "detener",
            "stop",
            "fren",
            "parar",
            "para el video",
            "detene",
        )
    )
    wants_play = any(
        t in normalized
        for t in (
            "reanuda",
            "reanudar",
            "resume",
            "continu",
            "seguir",
            "segui",
            "play",
            "reproduc",
            "ponelo",
            "ponela",
            "dale play",
        )
    )
    wants_close = any(t in normalized for t in ("cerr", "close", "cierra", "cerra")) and any(
        t in normalized for t in ("ventan", "window", "pestan", "tab")
    )

    if wants_play and not wants_pause:
        return "play", wants_close
    if wants_pause:
        return "pause", wants_close
    return None


def _pick_active_site_window_id(
    site_key: str, expected_profile: str | None = None
) -> tuple[str | None, str]:
    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, "workspace_not_detected"
    active = _xdotool_active_window()
    if not active:
        return None, "active_window_not_detected"
    token = "gemini" if site_key == "gemini" else ("chatgpt" if site_key == "chatgpt" else site_key)
    for wid, pid_raw, title in _wmctrl_windows_for_desktop(desk):
        if wid.lower() != active.lower():
            continue
        t = str(title).lower().strip()
        if token not in t:
            return None, "active_window_not_site"
        if "molbot direct chat" in t:
            return None, "active_window_is_dc"
        if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
            return None, "active_window_profile_mismatch"
        return wid, str(title)
    return None, "active_window_not_in_current_workspace"


def _capture_window_snapshot(win_id: str, out_path: Path) -> bool:
    import_bin = shutil.which("import")
    if not import_bin:
        return False
    try:
        subprocess.run(
            [import_bin, "-window", win_id, str(out_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
    except Exception:
        return False
    return out_path.exists()


def _youtube_try_skip_ads(win_id: str, timeout_s: float = 7.0) -> tuple[int, str]:
    geom = _xdotool_window_geometry(win_id)
    if not geom:
        return 0, "geometry_not_found"
    gx, gy, gw, gh = geom
    screen_dir = Path.home() / ".openclaw" / "logs" / "youtube_transport_screens"
    screen_dir.mkdir(parents=True, exist_ok=True)

    can_ocr = bool(shutil.which("tesseract")) and bool(shutil.which("import"))
    if not can_ocr:
        return 0, "skip_ocr_unavailable"

    skip_clicks = 0
    last_detail = "no_ad_detected"
    deadline = time.time() + max(1.5, float(timeout_s))
    loops = 0
    while time.time() < deadline:
        loops += 1
        snap = screen_dir / f"youtube_transport_{int(time.time() * 1000)}.png"
        if not _capture_window_snapshot(win_id, snap):
            last_detail = "snapshot_failed"
            break
        txt = _ocr_read_text(snap)
        txt_norm = str(txt or "").lower()
        has_skip = any(
            t in txt_norm
            for t in (
                "omitir anuncio",
                "omitir",
                "skip ad",
                "skip ads",
                "saltar anuncio",
                "saltar",
            )
        )
        has_ad_hint = any(t in txt_norm for t in ("patrocinado", "anuncio", "advertisement", "sponsored"))
        if has_skip:
            pt_rel = _ocr_find_phrase_center(
                snap,
                [
                    "omitir anuncio",
                    "omitir",
                    "skip ad",
                    "skip ads",
                    "saltar anuncio",
                ],
            )
            if pt_rel:
                px_rel, py_rel = int(pt_rel[0]), int(pt_rel[1])
                safe_x_min = int(gw * 0.62)
                safe_y_min = int(gh * 0.28)
                safe_y_max = int(gh * 0.82)
                if px_rel >= safe_x_min and safe_y_min <= py_rel <= safe_y_max:
                    px = gx + px_rel
                    py = gy + py_rel
                    _xdotool_command(["mousemove", str(px), str(py)], timeout=2.0)
                    _xdotool_command(["click", "1"], timeout=2.0)
                    skip_clicks += 1
                    last_detail = "ad_detected_skip_clicked"
                else:
                    last_detail = "ad_detected_skip_outside_safe_zone"
            else:
                # Safety: detect skip-capable ad but avoid blind clicks that can open
                # advertiser destinations in the active profile.
                last_detail = "ad_detected_skip_available"
            time.sleep(0.45)
            continue

        if skip_clicks > 0 and (not has_ad_hint):
            return skip_clicks, "ad_skipped"
        if (not has_ad_hint) and loops >= 2:
            return skip_clicks, "no_ad_detected"
        last_detail = "ad_detected_skip_not_available" if has_ad_hint else last_detail
        time.sleep(0.45)
    return skip_clicks, last_detail


def _youtube_read_playback_second(win_id: str) -> int | None:
    geom = _xdotool_window_geometry(win_id)
    if geom:
        gx, gy, gw, gh = geom
        # Reveal player controls before OCR, without clicking.
        mx = gx + max(42, int(gw * 0.18))
        my = gy + max(42, int(gh * 0.86))
        _xdotool_command(["mousemove", str(mx), str(my)], timeout=2.0)
        time.sleep(0.10)
    screen_dir = Path.home() / ".openclaw" / "logs" / "youtube_transport_screens"
    screen_dir.mkdir(parents=True, exist_ok=True)
    snap = screen_dir / f"youtube_clock_{int(time.time() * 1000)}.png"
    if not _capture_window_snapshot(win_id, snap):
        return None
    txt = _ocr_read_text(snap)
    if not txt:
        return None
    # Typical OCR match: "0:03 / 53:41".
    m = re.search(r"\b(\d{1,2}):(\d{2})\s*/\s*\d{1,2}:\d{2}\b", txt)
    if not m:
        # Fallback: first mm:ss token seen in the controls.
        m = re.search(r"\b(\d{1,2}):(\d{2})\b", txt)
    if not m:
        return None
    try:
        mm = int(m.group(1))
        ss = int(m.group(2))
    except Exception:
        return None
    if mm < 0 or ss < 0 or ss >= 60:
        return None
    return (mm * 60) + ss


def _youtube_is_progressing(win_id: str, wait_s: float = 1.35) -> tuple[bool, str]:
    t1 = _youtube_read_playback_second(win_id)
    if t1 is None:
        return False, "clock_unreadable_t1"
    time.sleep(max(0.8, float(wait_s)))
    t2 = _youtube_read_playback_second(win_id)
    if t2 is None:
        return False, "clock_unreadable_t2"
    if t2 > t1:
        return True, f"clock_advanced_{t1}_to_{t2}"
    return False, f"clock_stalled_{t1}_to_{t2}"


def _youtube_title_is_provisional(title: str) -> bool:
    t = str(title or "").lower().strip()
    if not t:
        return True
    if "about:blank" in t:
        return True
    if "youtube.com/watch" in t or "youtube.com/results" in t:
        return True
    return False


def _youtube_wait_loaded_title(win_id: str, timeout_s: float = 16.0) -> tuple[bool, str]:
    deadline = time.time() + max(1.0, float(timeout_s))
    last = ""
    while time.time() < deadline:
        cur = str(_wmctrl_list().get(win_id, "")).strip()
        if cur:
            last = cur
        if cur and ("youtube" in cur.lower()) and (not _youtube_title_is_provisional(cur)):
            return True, cur
        time.sleep(0.25)
    return False, last


def _youtube_visual_progress(win_id: str, interval_s: float = 2.8) -> tuple[bool, str]:
    screen_dir = Path.home() / ".openclaw" / "logs" / "youtube_transport_screens"
    screen_dir.mkdir(parents=True, exist_ok=True)
    p1 = screen_dir / f"youtube_visual_{int(time.time() * 1000)}_a.png"
    p2 = screen_dir / f"youtube_visual_{int(time.time() * 1000)}_b.png"
    if not _capture_window_snapshot(win_id, p1):
        return False, "visual_snap_a_failed"
    time.sleep(max(1.2, float(interval_s)))
    if not _capture_window_snapshot(win_id, p2):
        return False, "visual_snap_b_failed"
    try:
        h1 = hashlib.sha256(p1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(p2.read_bytes()).hexdigest()
    except Exception:
        return False, "visual_hash_failed"
    if h1 != h2:
        return True, "visual_changed"
    return False, "visual_static"


def _best_youtube_window_candidate(wins: list[tuple[str, str]]) -> tuple[str, str] | None:
    best: tuple[str, str] | None = None
    best_score = -10**9
    for idx, item in enumerate(wins):
        try:
            wid, title = item
        except Exception:
            continue
        t = str(title or "").lower().strip()
        # Slight bias to recent windows, but quality dominates.
        score = idx
        if " - youtube" in t:
            score += 30
        if "youtube - google chrome" in t:
            score += 8
        if "youtube.com/watch" in t:
            # URL-title windows are often still loading/blank.
            score -= 18
        if "about:blank" in t:
            score -= 30
        if score > best_score:
            best_score = score
            best = (str(wid), str(title))
    return best


def _youtube_transport_action(action: str, close_window: bool = False, session_id: str | None = None) -> tuple[bool, str]:
    _ = session_id  # Reserved for future per-session telemetry.
    expected_profile = _expected_profile_directory_for_site("youtube")
    win_id, detail = _pick_active_site_window_id("youtube", expected_profile=expected_profile)
    if not win_id:
        wins = _wmctrl_current_desktop_site_windows("youtube", expected_profile=expected_profile)
        picked = _best_youtube_window_candidate(wins) if wins else None
        if picked:
            win_id, detail = picked
    if not win_id:
        win_id, detail = _pick_active_site_window_id("youtube", expected_profile=None)
    if not win_id:
        wins = _wmctrl_current_desktop_site_windows("youtube", expected_profile=None)
        picked = _best_youtube_window_candidate(wins) if wins else None
        if picked:
            win_id, detail = picked
    if not win_id:
        return False, f"youtube_window_not_found_current_desktop profile={expected_profile}"

    rc_activate, _ = _xdotool_command(["windowactivate", win_id], timeout=2.5)
    if rc_activate != 0:
        return False, f"window_activate_failed win={win_id}"
    time.sleep(0.16)

    action_norm = str(action or "").strip().lower()
    skip_clicks = 0
    skip_detail = "n/a"
    progress_detail = "n/a"
    load_detail = "n/a"
    toggle_count = 0
    ad_detected = False
    if action_norm == "play":
        cur_title = str(_wmctrl_list().get(win_id, detail or "")).strip()
        if _youtube_title_is_provisional(cur_title):
            load_url = "https://www.youtube.com/"
            m_watch = re.search(r"(youtube\.com/watch\?[^\s]+)", cur_title, flags=re.IGNORECASE)
            if m_watch:
                cand = str(m_watch.group(1) or "").strip().strip("'\"")
                cand = cand.rstrip(")").rstrip("]").rstrip("}")
                load_url = f"https://{cand}"
            _xdotool_command(["key", "--window", win_id, "ctrl+l"], timeout=2.0)
            time.sleep(0.08)
            _xdotool_command(
                ["type", "--delay", "14", "--clearmodifiers", "--window", win_id, load_url],
                timeout=8.0,
            )
            time.sleep(0.08)
            _xdotool_command(["key", "--window", win_id, "Return"], timeout=2.0)
            ok_loaded, loaded_title = _youtube_wait_loaded_title(win_id, timeout_s=16.0)
            if ok_loaded:
                detail = loaded_title
                load_detail = "forced_load_ok"
            else:
                load_detail = f"forced_load_failed:{loaded_title[:80]}"
        else:
            load_detail = "already_loaded"
        # Dismiss possible UI overlays and attempt "Skip Ad" before toggling play.
        _xdotool_command(["key", "--window", win_id, "Escape"], timeout=1.5)
        skip_clicks, skip_detail = _youtube_try_skip_ads(win_id, timeout_s=7.0)
        ad_detected = str(skip_detail).startswith("ad_detected")

    rc_key = 0
    if action_norm != "play":
        # YouTube keyboard control: 'k' toggles play/pause consistently across layouts.
        rc_key, _ = _xdotool_command(["key", "--window", win_id, "k"], timeout=2.0)
        if rc_key != 0:
            return False, f"youtube_key_toggle_failed win={win_id}"

    if action_norm == "play":
        pre_progressing, pre_progress_detail = _youtube_is_progressing(win_id, wait_s=1.1)
        if pre_progressing:
            progress_detail = f"already_playing:{pre_progress_detail}"
        elif ad_detected:
            # Avoid toggling while an ad is still detected, to prevent pausing
            # autoplay at 0:00.
            pre2_progressing, pre2_detail = _youtube_is_progressing(win_id, wait_s=1.1)
            if pre2_progressing:
                progress_detail = f"ad_detected_playing:{pre_progress_detail};confirm={pre2_detail}"
            else:
                vis_ok_pre, vis_detail_pre = _youtube_visual_progress(win_id, interval_s=1.7)
                if vis_ok_pre:
                    progress_detail = (
                        f"ad_detected_visual_playing:{pre_progress_detail};confirm={pre2_detail};{vis_detail_pre}"
                    )
                else:
                    # Rescue path: if ad is visible but static, one toggle can resume.
                    rc_key, _ = _xdotool_command(["key", "--window", win_id, "k"], timeout=2.0)
                    if rc_key != 0:
                        return False, f"youtube_key_toggle_failed win={win_id}"
                    toggle_count += 1
                    progress_detail = (
                        f"ad_detected_rescue_toggle:{pre_progress_detail};confirm={pre2_detail};visual={vis_detail_pre}"
                    )
        else:
            rc_key, _ = _xdotool_command(["key", "--window", win_id, "k"], timeout=2.0)
            if rc_key != 0:
                return False, f"youtube_key_toggle_failed win={win_id}"
            toggle_count += 1
        # Some ad chains show another skip button right after toggling.
        extra_clicks, extra_detail = _youtube_try_skip_ads(win_id, timeout_s=2.2)
        skip_clicks += extra_clicks
        ad_detected = ad_detected or str(extra_detail).startswith("ad_detected")
        if extra_clicks > 0 or skip_detail in ("n/a", "no_ad_detected"):
            skip_detail = extra_detail
        progressing, progress_detail = _youtube_is_progressing(win_id, wait_s=1.35)
        if (not progressing) and str(progress_detail).startswith("clock_stalled") and (not ad_detected):
            # If autoplay already started, first toggle can pause at 0:00.
            # Re-toggle once and verify progress again.
            _xdotool_command(["key", "--window", win_id, "k"], timeout=2.0)
            toggle_count += 1
            time.sleep(0.20)
            progressing2, progress_detail2 = _youtube_is_progressing(win_id, wait_s=1.35)
            progress_detail = f"{progress_detail};retoggle={progress_detail2}"
            if not progressing2:
                _xdotool_command(["key", "--window", win_id, "Escape"], timeout=1.5)
        if (not progressing) and str(progress_detail).startswith("clock_unreadable"):
            vis_ok, vis_detail = _youtube_visual_progress(win_id, interval_s=2.6)
            if vis_ok:
                progressing = True
                progress_detail = f"{progress_detail};{vis_detail}"
            elif ad_detected and toggle_count <= 1:
                # OCR can fail for the ad timer; if ad frame is static, retry one
                # explicit resume and validate with visual movement.
                rc_key, _ = _xdotool_command(["key", "--window", win_id, "k"], timeout=2.0)
                if rc_key == 0:
                    toggle_count += 1
                    time.sleep(0.20)
                    vis_ok2, vis_detail2 = _youtube_visual_progress(win_id, interval_s=2.6)
                    if vis_ok2:
                        progressing = True
                    progress_detail = f"{progress_detail};ad_rescue_visual={vis_detail2}"
            elif toggle_count <= 0 and (not ad_detected):
                rc_key, _ = _xdotool_command(["key", "--window", win_id, "k"], timeout=2.0)
                if rc_key == 0:
                    toggle_count += 1
                    time.sleep(0.20)
                    vis_ok2, vis_detail2 = _youtube_visual_progress(win_id, interval_s=2.6)
                    if vis_ok2:
                        progressing = True
                    progress_detail = f"{progress_detail};retoggle_visual={vis_detail2}"
        if progressing and ("clock_advanced" not in str(progress_detail)):
            # Visual-only changes can happen while ad overlays are static/looped.
            # Re-check ad presence before claiming successful playback.
            post_clicks, post_detail = _youtube_try_skip_ads(win_id, timeout_s=1.8)
            skip_clicks += int(post_clicks or 0)
            if post_clicks > 0 or skip_detail in ("n/a", "no_ad_detected"):
                skip_detail = post_detail
            if str(post_detail).startswith("ad_detected"):
                progressing = False
                progress_detail = f"{progress_detail};ad_still_detected={post_detail}"
        if _youtube_title_is_provisional(str(_wmctrl_list().get(win_id, detail or ""))):
            return False, f"youtube_not_loaded_after_play win={win_id} load_detail={load_detail}"
        final_title = str(_wmctrl_list().get(win_id, detail or "")).lower().strip()
        if "youtube" not in final_title:
            return False, f"youtube_navigation_lost win={win_id} title={final_title[:120]}"
        if not progressing:
            return False, f"youtube_play_not_confirmed win={win_id} detail={progress_detail}"

    if close_window:
        time.sleep(0.15)
        if not _wmctrl_close_window(win_id):
            return False, f"youtube_close_failed win={win_id}"

    return (
        True,
        f"ok action={action_norm or action} close={int(close_window)} win={win_id} "
        f"load_detail={load_detail} toggle_count={toggle_count} skip_clicks={skip_clicks} skip_detail={skip_detail} "
        f"progress_detail={progress_detail} detail={detail[:120]}",
    )


def _extract_gemini_write_request(message: str) -> str | None:
    msg = (message or "").strip()
    normalized = _normalize_text(msg)
    if not any(t in normalized for t in SITE_CANONICAL_TOKENS.get("gemini", [])):
        return None
    if not any(
        v in normalized
        for v in (
            "escrib",
            "deci",
            "decí",
            "pone",
            "poné",
            "manda",
            "envia",
            "enviá",
            "redact",
            "tipe",
            "coloc",
            "deja",
            "dejá",
            "mete",
            "carg",
            "public",
            "poste",
        )
    ):
        return None

    quoted = re.search(r"[\"“”'`]\s*([^\"“”'`]{1,320})\s*[\"“”'`]", msg)
    if quoted:
        text = quoted.group(1).strip()
        if text:
            return text[:320]

    # Pick the LAST writing verb in the phrase, so requests like
    # "decile a cunn que abra gemini y escriba hola gemini"
    # extract only "hola gemini".
    verb_pat = re.compile(
        r"\b(?:escrib\w*|dec[ií]\w*|pon[eé]\w*|manda\w*|envia\w*|envi[aá]\w*|redact\w*|tipe\w*|coloc\w*|deja\w*|dej[aá]\w*|mete\w*|carg\w*|public\w*|poste\w*)\b",
        flags=re.IGNORECASE,
    )
    matches = list(verb_pat.finditer(normalized))
    if not matches:
        return None
    text = normalized[matches[-1].end() :].strip()
    text = re.split(r"\s+y\s+(?:da\s+)?enter\b|\s+enter\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"[\n\r]", text, maxsplit=1)[0]
    text = re.sub(r"\ben\s+el\s+chat\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\ben\s+gemini\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpor\s+favor\b", "", text, flags=re.IGNORECASE)
    text = text.strip(" .,:;\"'`")
    if not text:
        return None
    return text[:320]


def _extract_gemini_ask_request(message: str) -> str | None:
    normalized = _normalize_text(message or "")
    if not any(t in normalized for t in SITE_CANONICAL_TOKENS.get("gemini", [])):
        return None
    if not any(v in normalized for v in ("pregunt", "consult", "pedi", "pedile", "decile", "dile", "busc", "busq")):
        return None

    # Variant: "busca <tema> en gemini"
    m = re.search(
        r"(?:^|\b)(?:que\s+)?(?:me\s+)?(?:busc\w*|busq\w*)\s+(.+?)\s+en\s+gemini\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if m:
        prompt = (m.group(1) or "").strip()
        prompt = re.sub(r"^(sobre|acerca de)\s+", "", prompt, flags=re.IGNORECASE).strip()
        prompt = prompt.strip(" .,:;\"'`")
        if prompt:
            return prompt[:320]

    m = re.search(
        r"(?:pregunt\w*|consult\w*|ped\w*|dec\w*|dile|busc\w*|busq\w*)\s+(?:en\s+)?(?:a\s+)?gemini\b[\s,:-]*(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"\bgemini\b.*?(?:pregunt\w*|consult\w*|ped\w*|dec\w*|dile|busc\w*|busq\w*)\b[\s,:-]*(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
    if not m:
        return None
    prompt = (m.group(1) or "").strip()
    prompt = re.sub(r"^(que|sobre|acerca de)\s+", "", prompt, flags=re.IGNORECASE).strip()
    prompt = prompt.strip(" .,:;\"'`")
    if not prompt:
        return None
    return prompt[:320]


def _ocr_read_text(image_path: Path) -> str:
    if not shutil.which("tesseract"):
        return ""
    try:
        proc = subprocess.run(
            ["tesseract", str(image_path), "stdout"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return re.sub(r"\s+", " ", (proc.stdout or "").lower()).strip()
    except Exception:
        return ""


def _ocr_contains_text(image_path: Path, expected: str) -> bool:
    try:
        txt = _ocr_read_text(image_path)
        if not txt:
            return False
        exp = re.sub(r"\s+", " ", expected.lower().strip()).strip()
        if not exp:
            return False
        # accept either full text or first token for short prompts
        if exp in txt:
            return True
        # For multi-word prompts, require contiguous phrase match to avoid false positives
        # from unrelated UI text (e.g., "Hola, diego" + "Gemini" in different places).
        if len(exp.split()) >= 2:
            return False
        parts = [p for p in re.split(r"\W+", exp) if len(p) >= 3]
        if not parts:
            first = exp.split()[0] if exp.split() else exp
            return len(first) >= 4 and first in txt
        hits = sum(1 for p in parts if p in txt)
        return hits >= max(1, len(parts) // 2)
    except Exception:
        return False


def _ocr_contains_any(image_path: Path, expected_terms: list[str]) -> bool:
    txt = _ocr_read_text(image_path)
    if not txt:
        return False
    for term in expected_terms:
        exp = re.sub(r"\s+", " ", term.lower().strip()).strip()
        if exp and exp in txt:
            return True
    return False


def _ocr_phrase_centers(image_path: Path, phrase: str) -> list[tuple[int, int]]:
    if not shutil.which("tesseract"):
        return []
    try:
        proc = subprocess.run(
            ["tesseract", str(image_path), "stdout", "hocr"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw = proc.stdout or ""
    except Exception:
        return []
    if not raw.strip():
        return []

    words: list[tuple[str, tuple[int, int, int, int]]] = []
    for m in re.finditer(
        r"<span[^>]*class=[\"']ocrx_word[\"'][^>]*title=[\"']([^\"']+)[\"'][^>]*>(.*?)</span>",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        title = m.group(1) or ""
        body = re.sub(r"<[^>]+>", "", m.group(2) or "")
        body = html.unescape(body).strip()
        if not body:
            continue
        bb = re.search(r"bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", title)
        if not bb:
            continue
        try:
            x1, y1, x2, y2 = [int(bb.group(i)) for i in range(1, 5)]
        except Exception:
            continue
        norm_word = re.sub(r"[^\wáéíóúüñ]+", "", _normalize_text(body))
        if not norm_word:
            continue
        words.append((norm_word, (x1, y1, x2, y2)))
    if not words:
        return None

    tokens = [w for w, _ in words]
    pnorm = _normalize_text(phrase)
    wanted = [re.sub(r"[^\wáéíóúüñ]+", "", t) for t in pnorm.split()]
    wanted = [t for t in wanted if t]
    if not wanted:
        return []

    n = len(wanted)
    out: list[tuple[int, int]] = []
    for i in range(0, len(tokens) - n + 1):
        if tokens[i : i + n] != wanted:
            continue
        xs = []
        ys = []
        for _w, (x1, y1, x2, y2) in words[i : i + n]:
            xs.extend([x1, x2])
            ys.extend([y1, y2])
        if not xs or not ys:
            continue
        cx = (min(xs) + max(xs)) // 2
        cy = (min(ys) + max(ys)) // 2
        out.append((cx, cy))
    return out


def _ocr_find_phrase_center(image_path: Path, phrases: list[str]) -> tuple[int, int] | None:
    for phrase in phrases:
        centers = _ocr_phrase_centers(image_path, phrase)
        if centers:
            return centers[0]
    return None


def _looks_like_phrase_still_in_composer(
    image_path: Path, phrase: str, win_h: int, threshold_pct: int = 72
) -> bool:
    pts = _ocr_phrase_centers(image_path, phrase)
    if not pts:
        return False
    threshold = int(win_h * threshold_pct / 100)
    return any(y >= threshold for _x, y in pts)


def _composer_send_click_point(
    image_path: Path, win_w: int, win_h: int, composer_center: tuple[int, int] | None
) -> tuple[int, int] | None:
    anchor = _ocr_find_phrase_center(
        image_path,
        [
            "pensar",
            "think",
            "herramientas",
            "tools",
        ],
    )
    if anchor:
        ax, ay = anchor
        # In Gemini layout, the send button sits to the right of "Pensar/Think".
        return min(win_w - 24, ax + int(win_w * 0.12)), ay
    if composer_center:
        cx, cy = composer_center
        # Fallback: right edge of composer row.
        return min(win_w - 24, cx + int(win_w * 0.38)), cy
    return None


def _composer_looks_empty(image_path: Path) -> bool:
    return _ocr_contains_any(
        image_path,
        [
            "preguntale a gemini",
            "pregúntale a gemini",
            "pregunta a gemini",
            "pregunta a gemini 3",
            "que quieres investigar",
            "¿qué quieres investigar?",
            "ask gemini",
        ],
    )


def _gemini_write_in_current_workspace(text: str, session_id: str | None = None) -> tuple[bool, str]:
    if not shutil.which("wmctrl") or not shutil.which("xdotool"):
        return False, "missing_wmctrl_or_xdotool"

    workspace, _anchor = _preferred_workspace_and_anchor()
    if workspace is None:
        return False, "workspace_not_detected"

    expected_profile = _expected_profile_directory_for_site("gemini")

    # Reuse Gemini in the current workspace when available.
    opened: list[str]
    existing = _wmctrl_current_desktop_site_windows(
        "gemini", expected_profile=expected_profile, desktop_idx=workspace
    )
    if existing:
        opened = ["reuse_existing_gemini_window"]
    else:
        ok_open, detail = _open_gemini_in_current_workspace_via_ui(
            expected_profile=expected_profile, session_id=session_id
        )
        if not ok_open:
            return False, detail
        opened = [detail]

    win_id = ""
    for _ in range(140):
        wins = _wmctrl_current_desktop_site_windows(
            "gemini", expected_profile=expected_profile, desktop_idx=workspace
        )
        if wins:
            win_id = wins[-1][0]
            break
        time.sleep(0.12)
    if not win_id:
        return False, f"gemini_window_not_found_current_workspace profile={expected_profile}"

    _xdotool_command(["windowactivate", win_id], timeout=2.5)
    time.sleep(0.65)
    geom = _xdotool_window_geometry(win_id)
    if not geom:
        return False, "gemini_geometry_not_found"
    gx, gy, gw, gh = geom

    screen_dir = Path.home() / ".openclaw" / "logs" / "gemini_write_screens"
    screen_dir.mkdir(parents=True, exist_ok=True)
    import_bin = shutil.which("import")
    if not import_bin:
        return False, "missing_import_for_visual_verification"

    snap_state = screen_dir / f"gemini_write_state_{int(time.time() * 1000)}.png"
    try:
        subprocess.run(
            [import_bin, "-window", win_id, str(snap_state)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
    except Exception:
        return False, "state_screenshot_failed"

    if _ocr_contains_any(snap_state, ["iniciar sesión", "iniciar sesion", "sign in"]):
        return False, f"login_required workspace={workspace} win={win_id} snap={snap_state}"

    composer_center = _ocr_find_phrase_center(
        snap_state,
        [
            "preguntale a gemini",
            "pregúntale a gemini",
            "pregunta a gemini",
            "pregunta a gemini 3",
            "que quieres investigar",
            "¿qué quieres investigar?",
            "ask gemini",
        ],
    )
    if not composer_center:
        tools_anchor = _ocr_find_phrase_center(
            snap_state,
            [
                "herramientas",
                "tools",
                "pensar",
                "think",
            ],
        )
        if tools_anchor:
            tx, ty = tools_anchor
            # When placeholder text is absent, anchors in the composer footer are usually visible.
            # Click a bit above that footer to focus the text input area.
            composer_center = (tx, max(12, ty - int(gh * 0.055)))
    if not composer_center:
        # OCR can miss dark-theme placeholders; use geometric fallback over the
        # central lower panel where Gemini composer usually lives.
        composer_center = (int(gw * 0.62), int(gh * 0.56))

    rel_x, rel_y = composer_center
    px = gx + rel_x
    py = gy + rel_y
    _xdotool_command(["mousemove", str(px), str(py)], timeout=2.0)
    _xdotool_command(["click", "1"], timeout=2.0)
    time.sleep(0.14)

    dirty_detected = False
    pre_clean = screen_dir / f"gemini_write_pre_clean_{int(time.time() * 1000)}.png"
    try:
        subprocess.run(
            [import_bin, "-window", win_id, str(pre_clean)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        if _looks_like_phrase_still_in_composer(pre_clean, text, gh) or not _composer_looks_empty(pre_clean):
            dirty_detected = True
    except Exception:
        pass

    # Self-heal: clear any leftover draft to avoid cascading failures.
    clean_ok = False
    clean_snap = None
    for _ in range(3):
        _xdotool_command(["key", "--window", win_id, "ctrl+a"], timeout=2.0)
        time.sleep(0.06)
        _xdotool_command(["key", "--window", win_id, "BackSpace"], timeout=2.0)
        time.sleep(0.10)
        clean_snap = screen_dir / f"gemini_write_clean_{int(time.time() * 1000)}.png"
        try:
            subprocess.run(
                [import_bin, "-window", win_id, str(clean_snap)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
            if not _looks_like_phrase_still_in_composer(clean_snap, text, gh):
                clean_ok = True
                break
        except Exception:
            continue
    if not clean_ok:
        return False, f"dirty_chat_not_cleaned workspace={workspace} win={win_id} snap={clean_snap}"

    tools_anchor = _ocr_find_phrase_center(
        snap_state,
        [
            "herramientas",
            "tools",
            "pensar",
            "think",
        ],
    )
    focus_candidates: list[tuple[int, int]] = [composer_center]
    if tools_anchor:
        tx, ty = tools_anchor
        focus_candidates.append((tx, max(12, ty - int(gh * 0.080))))
    focus_candidates.extend(
        [
            # Safe geometric fallbacks inside the upper half of the composer.
            (int(gw * 0.58), int(gh * 0.53)),
            (int(gw * 0.68), int(gh * 0.53)),
            (int(gw * 0.58), int(gh * 0.56)),
        ]
    )

    snap_pre = None
    pre_verified = False
    focus_ok = False
    for fx, fy in focus_candidates:
        # Keep focus attempts in a conservative region to avoid clicks below composer.
        fx = max(int(gw * 0.42), min(int(fx), int(gw * 0.95)))
        fy = max(int(gh * 0.46), min(int(fy), int(gh * 0.60)))
        px = gx + fx
        py = gy + fy
        _xdotool_command(["mousemove", str(px), str(py)], timeout=2.0)
        _xdotool_command(["click", "1"], timeout=2.0)
        time.sleep(0.08)
        _xdotool_command(["type", "--delay", "34", "--clearmodifiers", "--window", win_id, text], timeout=8.0)
        time.sleep(0.25)

        snap_try = screen_dir / f"gemini_write_pre_{int(time.time() * 1000)}.png"
        try:
            subprocess.run(
                [import_bin, "-window", win_id, str(snap_try)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
        except Exception:
            continue
        snap_pre = snap_try
        if _looks_like_phrase_still_in_composer(snap_try, text, gh):
            focus_ok = True
            pre_verified = True
            break

    if not focus_ok or not snap_pre:
        return False, f"composer_focus_failed workspace={workspace} win={win_id} snap={snap_pre or snap_state}"

    send_pt_rel = _composer_send_click_point(snap_pre, gw, gh, composer_center)
    send_attempts = [("enter", None), ("ctrl_enter", None), ("enter_kp", None)]
    if send_pt_rel:
        send_attempts.append(("click_send_ocr", send_pt_rel))
    # Crucial fallback: click on the right side of the SAME composer row, not near window bottom.
    if composer_center:
        send_attempts.extend(
            [
                ("click_send_row_right", (96, int((composer_center[1] * 100) / max(1, gh)))),
                ("click_send_row_right_alt", (93, int((composer_center[1] * 100) / max(1, gh)))),
            ]
        )
    send_attempts.extend([("click_send", (92, 95)), ("click_send_alt", (95, 95))])
    last_post = None
    for action, point in send_attempts:
        if action == "enter":
            _xdotool_command(["key", "--window", win_id, "Return"], timeout=2.0)
        elif action == "ctrl_enter":
            _xdotool_command(["key", "--window", win_id, "ctrl+Return"], timeout=2.0)
        elif action == "enter_kp":
            _xdotool_command(["key", "--window", win_id, "KP_Enter"], timeout=2.0)
        else:
            if action == "click_send_ocr":
                spx = gx + int(point[0])
                spy = gy + int(point[1])
            else:
                spx = gx + int(gw * point[0] / 100)
                spy = gy + int(gh * point[1] / 100)
            _xdotool_command(["mousemove", str(spx), str(spy)], timeout=2.0)
            _xdotool_command(["click", "1"], timeout=2.0)
        time.sleep(0.85)

        snap_post = screen_dir / f"gemini_write_post_{int(time.time() * 1000)}_{action}.png"
        try:
            subprocess.run(
                [import_bin, "-window", win_id, str(snap_post)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
            last_post = snap_post
            if not _looks_like_phrase_still_in_composer(snap_post, text, gh):
                # Stabilize verdict: verify again shortly after to avoid transient false positives.
                time.sleep(0.75)
                snap_post_confirm = screen_dir / f"gemini_write_post_{int(time.time() * 1000)}_{action}_confirm.png"
                try:
                    subprocess.run(
                        [import_bin, "-window", win_id, str(snap_post_confirm)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=4,
                    )
                    last_post = snap_post_confirm
                    if _looks_like_phrase_still_in_composer(snap_post_confirm, text, gh):
                        continue
                except Exception:
                    # If confirm capture fails, keep original optimistic sample.
                    snap_post_confirm = snap_post
                return True, (
                    f"verified workspace={workspace} win={win_id} click={px},{py} "
                    f"submit={action} dirty={int(dirty_detected)} "
                    f"pre_verified={int(pre_verified)} snap_pre={snap_pre} "
                    f"snap_post={snap_post_confirm} opened={' | '.join(opened)}"
                )
        except Exception:
            continue

    return False, (
        f"submit_failed_draft_present workspace={workspace} win={win_id} "
        f"pre_verified={int(pre_verified)} snap_pre={snap_pre} snap_post={last_post}"
    )


def _browser_windows_load() -> dict:
    BROWSER_WINDOWS_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with BROWSER_WINDOWS_LOCK_PATH.open("a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_SH)
            if BROWSER_WINDOWS_PATH.exists():
                try:
                    data = json.loads(BROWSER_WINDOWS_PATH.read_text(encoding="utf-8") or "{}")
                    return data if isinstance(data, dict) else {}
                except Exception:
                    return {}
            return {}
    except Exception:
        return {}


def _browser_windows_save(data: dict) -> None:
    try:
        BROWSER_WINDOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
        BROWSER_WINDOWS_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = BROWSER_WINDOWS_PATH.with_suffix(".json.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        with BROWSER_WINDOWS_LOCK_PATH.open("a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(BROWSER_WINDOWS_PATH)
    except Exception:
        return


def _load_trusted_dc_anchor() -> dict:
    try:
        if not TRUSTED_DC_ANCHOR_PATH.exists():
            return {}
        raw = json.loads(TRUSTED_DC_ANCHOR_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return {}
    return {}


def _save_trusted_dc_anchor(win_id: str, desktop: int, title: str) -> None:
    try:
        TRUSTED_DC_ANCHOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "win_id": str(win_id),
            "desktop": int(desktop),
            "title": str(title),
            "ts": int(time.time()),
        }
        TRUSTED_DC_ANCHOR_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _trusted_dc_anchor_for_current_workspace() -> tuple[str | None, str]:
    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, "workspace_not_detected"
    data = _load_trusted_dc_anchor()
    win_id = str(data.get("win_id", "")).strip()
    if not win_id:
        return None, "trusted_anchor_not_set"
    wins = _wmctrl_windows_for_desktop(desk)
    for wid, _pid_raw, title in wins:
        if wid.lower() != win_id.lower():
            continue
        t = str(title).lower()
        if "molbot direct chat" not in t:
            return None, "trusted_anchor_title_mismatch"
        if "chrome" not in t and "google" not in t:
            return None, "trusted_anchor_not_chrome"
        return wid, "ok"
    return None, "trusted_anchor_not_in_current_workspace"


def _active_dc_anchor_for_current_workspace(expected_profile: str | None = None) -> tuple[str | None, str]:
    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, "workspace_not_detected"
    active = _xdotool_active_window()
    if not active:
        return None, "active_window_not_detected"
    wins = _wmctrl_windows_for_desktop(desk)
    for wid, pid_raw, title in wins:
        if wid.lower() != active.lower():
            continue
        t = str(title).lower()
        if "molbot direct chat" not in t:
            return None, "active_window_not_dc"
        if "chrome" not in t and "google" not in t:
            return None, "active_window_not_chrome"
        if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
            return None, "active_window_profile_mismatch"
        _save_trusted_dc_anchor(wid, desk, str(title))
        return wid, "active_anchor_ok"
    return None, "active_window_not_in_current_workspace"


def _autodetect_dc_anchor_for_current_workspace(expected_profile: str | None = None) -> tuple[str | None, str]:
    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, "workspace_not_detected"
    candidates: list[tuple[str, str]] = []
    for wid, pid_raw, title in _wmctrl_windows_for_desktop(desk):
        t = str(title).lower()
        if "molbot direct chat" not in t:
            continue
        if "chrome" not in t and "google" not in t:
            continue
        if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
            continue
        candidates.append((wid, str(title)))
    if len(candidates) == 1:
        wid, title = candidates[0]
        _save_trusted_dc_anchor(wid, desk, title)
        return wid, "auto_anchor_ok"
    if len(candidates) > 1:
        return None, "auto_anchor_ambiguous_multiple_windows"
    return None, "auto_anchor_not_found"


def _trusted_or_autodetected_dc_anchor(expected_profile: str | None = None) -> tuple[str | None, str]:
    active, active_status = _active_dc_anchor_for_current_workspace(expected_profile=expected_profile)
    if active:
        return active, active_status
    trusted, trusted_status = _trusted_dc_anchor_for_current_workspace()
    if trusted:
        return trusted, trusted_status
    auto, auto_status = _autodetect_dc_anchor_for_current_workspace(expected_profile=expected_profile)
    if auto:
        return auto, auto_status
    return None, f"{trusted_status}; {auto_status}"


def _record_browser_windows(session_id: str, items: list[dict]) -> None:
    data = _browser_windows_load()
    sess = data.get(session_id)
    if not isinstance(sess, dict):
        sess = {"items": []}
    if not isinstance(sess.get("items"), list):
        sess["items"] = []

    now = time.time()
    keep: list[dict] = []
    for it in sess["items"]:
        if not isinstance(it, dict):
            continue
        ts = float(it.get("ts", 0) or 0)
        if ts and (now - ts) < 30 * 60:
            keep.append(it)
    keep.extend(items)

    seen = set()
    deduped: list[dict] = []
    for it in reversed(keep):
        win_id = str(it.get("win_id", "")).strip()
        url = str(it.get("url", "")).strip()
        key = (win_id, url)
        if not win_id or key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    sess["items"] = list(reversed(deduped))[-40:]
    data[session_id] = sess
    _browser_windows_save(data)


def _close_recorded_browser_windows(session_id: str) -> tuple[int, list[str]]:
    data = _browser_windows_load()
    sess = data.get(session_id)
    if not isinstance(sess, dict):
        return 0, []
    items = sess.get("items", [])
    if not isinstance(items, list) or not items:
        return 0, []
    if not shutil.which("wmctrl"):
        return 0, ["wmctrl_missing"]

    closed = 0
    errors: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        win_id = str(it.get("win_id", "")).strip()
        if not win_id:
            continue
        try:
            subprocess.run(["wmctrl", "-ic", win_id], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            closed += 1
        except Exception as e:
            errors.append(str(e))

    data.pop(session_id, None)
    _browser_windows_save(data)
    return closed, errors


def _reset_recorded_browser_windows(session_id: str) -> None:
    data = _browser_windows_load()
    if session_id in data:
        data.pop(session_id, None)
        _browser_windows_save(data)


def _looks_like_open_request(normalized: str) -> bool:
    tokens = ("abr", "abri", "abir", "abrir", "open", "entra", "entrar", "ir a", "lanz", "inici")
    return any(t in normalized for t in tokens)


def _looks_like_direct_gemini_open(normalized: str) -> bool:
    has_gemini = any(t in normalized for t in SITE_CANONICAL_TOKENS.get("gemini", []))
    if not has_gemini:
        return False
    openish = _looks_like_open_request(normalized) or any(t in normalized for t in ("acceso directo", "shortcut"))
    return bool(openish)

def _read_meminfo() -> dict:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            parts = line.split(":")
            if len(parts) < 2:
                continue
            key = parts[0].strip()
            val = parts[1].strip().split()[0]
            if val.isdigit():
                out[key] = int(val)  # kB
    except Exception:
        return {}
    return out


def _proc_rss_mb(pid: int) -> float | None:
    try:
        statm = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8").split()
        if len(statm) < 2:
            return None
        rss_pages = int(statm[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (rss_pages * page_size) / (1024 * 1024)
    except Exception:
        return None


def _read_vram_nvidia() -> dict | None:
    # Cache for a few seconds to avoid hammering nvidia-smi.
    now = time.time()
    if (now - float(_VRAM_CACHE.get("ts", 0.0) or 0.0)) < 4.0:
        return _VRAM_CACHE.get("data")

    smi = shutil.which("nvidia-smi")
    if not smi:
        _VRAM_CACHE["ts"] = now
        _VRAM_CACHE["data"] = None
        return None
    try:
        proc = subprocess.run(
            [
                smi,
                "--query-gpu=memory.used,memory.total,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        line = (proc.stdout or "").strip().splitlines()[:1]
        if not line:
            raise RuntimeError("empty")
        parts = [p.strip() for p in line[0].split(",")]
        used = float(parts[0])
        total = float(parts[1])
        name = parts[2] if len(parts) > 2 else ""
        data = {"used_mb": used, "total_mb": total, "name": name}
        _VRAM_CACHE["ts"] = now
        _VRAM_CACHE["data"] = data
        return data
    except Exception:
        _VRAM_CACHE["ts"] = now
        _VRAM_CACHE["data"] = None
        return None



def _extract_topic(message: str) -> str | None:
    patterns = [
        r"iniciar (?:una )?conversacion(?: nueva)? sobre ([^.,;:\n]+)",
        r"conversacion(?: nueva)? sobre ([^.,;:\n]+)",
        r"chat nuevo sobre ([^.,;:\n]+)",
        r"sobre ([^.,;:\n]+)",
    ]
    text = _normalize_text(message)
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            topic = m.group(1).strip(" \"'").strip()
            if topic:
                return topic[:120]
    return None


def _canonical_site_keys(message: str) -> list[str]:
    text = _normalize_text(message)
    found = []
    for key, tokens in SITE_CANONICAL_TOKENS.items():
        if any(token in text for token in tokens):
            found.append(key)
    return found


def _open_firefox_urls(urls: list[str]) -> tuple[list[str], str | None]:
    opened = []
    for url in urls:
        try:
            subprocess.Popen(
                ["firefox", "--new-tab", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            opened.append(url)
        except FileNotFoundError:
            return opened, "No pude abrir Firefox: comando no encontrado en el sistema."
        except Exception as e:
            return opened, f"No pude abrir Firefox: {e}"
    return opened, None


def _load_browser_profile_config() -> dict:
    config = dict(DEFAULT_BROWSER_PROFILE_CONFIG)
    try:
        if PROFILE_CONFIG_PATH.exists():
            raw = json.loads(PROFILE_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(k, str) and isinstance(v, dict):
                        config[k] = v
    except Exception:
        pass
    return config


def _site_browser_profile_hint(site_key: str | None) -> tuple[str, str]:
    cfg = _load_browser_profile_config()
    site_cfg = cfg.get(site_key or "", {})
    if not site_cfg:
        site_cfg = cfg.get("_default", {})
    browser = str(site_cfg.get("browser", "")).lower().strip() or "chrome"
    profile_hint = str(site_cfg.get("profile", "")).strip()
    return browser, profile_hint


def _expected_profile_directory_for_site(site_key: str | None) -> str:
    _browser, hint = _site_browser_profile_hint(site_key)
    return _resolve_chrome_profile_directory(hint)


def _chrome_command() -> str | None:
    for cmd in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        found = shutil.which(cmd)
        if found:
            return found
    return None


def _chrome_user_data_dir_override() -> str:
    raw = str(os.environ.get("DIRECT_CHAT_CHROME_USER_DATA_DIR", "")).strip()
    if not raw:
        return ""
    p = Path(raw).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        return ""
    return str(p)


def _resolve_chrome_profile_directory(profile_hint: str) -> str:
    hint = profile_hint.strip()
    if not hint:
        hint = "Default"

    chrome_root = Path.home() / ".config" / "google-chrome"
    local_state = chrome_root / "Local State"
    known_keys: list[str] = []
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        info = data.get("profile", {}).get("info_cache", {})
        if isinstance(info, dict):
            known_keys = [k for k in info.keys() if isinstance(k, str)]
            hint_norm = hint.lower().strip()
            # Prefer a human profile-name match first ("diego" -> "Profile 1"),
            # then fall back to exact profile-directory key.
            for key, value in info.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                name = str(value.get("name", "")).lower().strip()
                if name == hint_norm:
                    return key
            for key in known_keys:
                if key.lower().strip() == hint_norm:
                    return key
    except Exception:
        pass

    if (chrome_root / hint).is_dir():
        return hint

    if (chrome_root / "Default").is_dir():
        return "Default"
    for key in known_keys:
        if (chrome_root / key).is_dir():
            return key
    return "Default"


def _fallback_profiled_chrome_anchor_for_workspace(
    desktop_idx: int, expected_profile: str | None
) -> tuple[str | None, str]:
    active = _xdotool_active_window()
    strict_candidates: list[str] = []
    lenient_candidates: list[str] = []
    for wid, pid_raw, title in _wmctrl_windows_for_desktop(desktop_idx):
        t = str(title).lower().strip()
        if "chrome" not in t and "google" not in t:
            continue
        lenient_candidates.append(wid)
        if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
            continue
        if active and wid.lower() == active.lower():
            return wid, "fallback_active_profiled_chrome"
        strict_candidates.append(wid)
    if strict_candidates:
        return strict_candidates[-1], "fallback_recent_profiled_chrome"
    if active and any(w.lower() == active.lower() for w in lenient_candidates):
        return active, "fallback_active_chrome_unverified_profile"
    if lenient_candidates:
        return lenient_candidates[-1], "fallback_recent_chrome_unverified_profile"
    return None, "fallback_profiled_chrome_not_found"


def _spawn_profiled_chrome_anchor_for_workspace(
    desktop_idx: int, expected_profile: str | None, initial_url: str = "about:blank"
) -> tuple[str | None, str]:
    chrome_cmd = _chrome_command()
    if not chrome_cmd:
        return None, "chrome_command_missing"
    profile = str(expected_profile or "").strip()
    if not profile:
        profile = "Default"
    before_ids = set(_wmctrl_list().keys())
    cmd = [chrome_cmd]
    user_data_dir = _chrome_user_data_dir_override()
    if user_data_dir:
        cmd.append(f"--user-data-dir={user_data_dir}")
    launch_url = str(initial_url or "").strip() or "about:blank"
    cmd.extend(
        [
            f"--profile-directory={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            launch_url,
        ]
    )
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return None, f"spawn_profiled_chrome_failed: {e}"
    win_id, desk = _find_new_profiled_chrome_window(before_ids, expected_profile=profile, timeout_s=8.0)
    if not win_id:
        win_id, desk = _find_new_profiled_chrome_window(before_ids, expected_profile=None, timeout_s=4.0)
        if win_id and desk is not None and int(desk) == int(desktop_idx):
            return win_id, "spawn_chrome_unverified_profile_ok"
    if not win_id:
        return None, "spawn_profiled_chrome_not_detected"
    if desk is None:
        return None, "spawn_profiled_chrome_workspace_unknown"
    if int(desk) != int(desktop_idx):
        # Workspace safety: never move windows across workspaces.
        return None, f"spawn_profiled_chrome_other_workspace={desk}"
    return win_id, "spawn_profiled_chrome_ok"


def _firefox_profile_roots() -> list[Path]:
    return [
        Path.home() / ".mozilla" / "firefox",
        Path.home() / "snap" / "firefox" / "common" / ".mozilla" / "firefox",
        Path.home() / ".var" / "app" / "org.mozilla.firefox" / ".mozilla" / "firefox",
    ]


def _resolve_firefox_profile_from_profile_groups(profile_hint: str) -> str:
    hint_norm = str(profile_hint or "").strip().lower()
    if not hint_norm:
        return ""
    for root in _firefox_profile_roots():
        pg_dir = root / "Profile Groups"
        if not pg_dir.exists():
            continue
        for db_path in sorted(pg_dir.glob("*.sqlite")):
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                try:
                    rows = con.execute("SELECT path, name FROM Profiles").fetchall()
                finally:
                    con.close()
            except Exception:
                continue
            for row in rows:
                if not isinstance(row, (tuple, list)) or len(row) < 2:
                    continue
                raw_path = str(row[0] or "").strip()
                raw_name = str(row[1] or "").strip()
                if raw_name and raw_name.lower().strip() == hint_norm:
                    return raw_name
                if raw_path:
                    path_norm = raw_path.lower().strip()
                    path_leaf = Path(raw_path).name.lower().strip()
                    if hint_norm in (path_norm, path_leaf):
                        return raw_name or raw_path
    return ""


def _resolve_firefox_profile_name(profile_hint: str) -> str:
    hint = str(profile_hint or "").strip()
    if not hint:
        return ""
    from_groups = _resolve_firefox_profile_from_profile_groups(hint)
    if from_groups:
        return from_groups
    ini_candidates = [
        root / "profiles.ini" for root in _firefox_profile_roots()
    ]
    for ini in ini_candidates:
        if not ini.exists():
            continue
        try:
            cp = configparser.ConfigParser()
            cp.read(str(ini), encoding="utf-8")
            hint_norm = hint.lower().strip()
            default_name = ""
            for section in cp.sections():
                if not section.lower().startswith("profile"):
                    continue
                name = str(cp.get(section, "Name", fallback="")).strip()
                path = str(cp.get(section, "Path", fallback="")).strip()
                if not default_name:
                    is_default = str(cp.get(section, "Default", fallback="0")).strip().lower() in ("1", "true", "yes", "on")
                    if is_default and name:
                        default_name = name
                if name and name.lower().strip() == hint_norm:
                    return name
                if path:
                    path_leaf = Path(path).name.lower().strip()
                    if path_leaf == hint_norm:
                        return name or Path(path).name
            if default_name:
                return default_name
        except Exception:
            continue
    return hint


def _open_url_with_site_context(url: str, site_key: str | None, session_id: str | None = None) -> str | None:
    browser, profile_hint = _site_browser_profile_hint(site_key)
    profile = _resolve_chrome_profile_directory(profile_hint)

    if browser == "chrome":
        desk = _wmctrl_current_desktop()
        if desk is None:
            return "No pude detectar el escritorio actual."
        wins = _wmctrl_windows_for_desktop(desk)
        anchor, anchor_status = _trusted_or_autodetected_dc_anchor(expected_profile=profile)
        fallback_status = ""
        spawn_status = ""
        if not anchor:
            anchor, fallback_status = _fallback_profiled_chrome_anchor_for_workspace(desk, profile)
        spawned_with_target = False
        if not anchor:
            spawn_result = _spawn_profiled_chrome_anchor_for_workspace(desk, profile, initial_url=str(url))
            if isinstance(spawn_result, tuple) and len(spawn_result) >= 2:
                anchor, spawn_status = spawn_result[0], str(spawn_result[1])
            else:
                anchor, spawn_status = None, "spawn_profiled_chrome_invalid_result"
            spawned_with_target = bool(anchor and str(spawn_status).startswith("spawn_"))
        if not anchor:
            return (
                "No abrí nada para evitar mezclar clientes: no encontré cliente Chrome del perfil diego. "
                f"(anchor={anchor_status}; fallback={fallback_status or 'n/a'}; spawn={spawn_status or 'n/a'})"
            )

        target = anchor
        skip_typing = False
        if spawned_with_target:
            skip_typing = True
            _xdotool_command(["windowactivate", target], timeout=2.5)
            time.sleep(0.12)
        else:
            before_ids = {wid for wid, _, _ in wins}
            _xdotool_command(["windowactivate", anchor], timeout=2.5)
            time.sleep(0.18)
            _xdotool_command(["key", "--window", anchor, "ctrl+n"], timeout=2.0)

            target = ""
            for _ in range(80):
                now = _wmctrl_windows_for_desktop(desk)
                for wid, _pid_raw, title in now:
                    t = str(title).lower()
                    if wid in before_ids:
                        continue
                    if "chrome" in t or "google" in t:
                        target = wid
                        break
                if target:
                    break
                time.sleep(0.08)
            if not target:
                retry_spawn = _spawn_profiled_chrome_anchor_for_workspace(desk, profile, initial_url=str(url))
                retry_target = ""
                if isinstance(retry_spawn, tuple) and len(retry_spawn) >= 2:
                    retry_target = str(retry_spawn[0] or "").strip()
                if retry_target:
                    target = retry_target
                    skip_typing = True
                else:
                    return (
                        "No pude abrir nueva ventana segura para navegar URL "
                        "(evité reutilizar la ventana de chat)."
                    )

            _xdotool_command(["windowactivate", target], timeout=2.5)
            time.sleep(0.10)

        if (not skip_typing) and target.lower() == anchor.lower():
            anchor_title = str(_wmctrl_list().get(anchor, "")).lower().strip()
            if "molbot direct chat" in anchor_title:
                return "No pude abrir nueva ventana segura (evité escribir URL sobre Molbot Direct Chat)."

        rc_a, _ = _xdotool_command(["windowactivate", target], timeout=2.5)
        if rc_a != 0:
            return f"No pude activar ventana objetivo. (win={target})"
        time.sleep(0.10)

        def _navigate_target_url() -> str | None:
            rc_l, _ = _xdotool_command(["key", "--window", target, "ctrl+l"], timeout=2.0)
            if rc_l != 0:
                return f"No pude enfocar barra de direcciones. (win={target})"
            time.sleep(0.06)
            rc_t, _ = _xdotool_command(
                ["type", "--delay", "16", "--clearmodifiers", "--window", target, str(url)],
                timeout=8.0,
            )
            if rc_t != 0:
                return f"No pude tipear URL. (win={target})"
            time.sleep(0.06)
            rc_r, _ = _xdotool_command(["key", "--window", target, "Return"], timeout=2.0)
            if rc_r != 0:
                return f"No pude enviar Enter. (win={target})"
            return None

        if not skip_typing:
            nav_error = _navigate_target_url()
            if nav_error:
                return nav_error

        terms: list[str] = []
        sk = str(site_key or "").strip().lower()
        if sk in ("google", "youtube", "gemini", "chatgpt", "wikipedia", "gmail"):
            terms.append(sk)
        try:
            host = (urlparse(str(url or "")).netloc or "").lower().strip(".")
            if host:
                base = host.split(".")
                for tok in (host, base[0] if base else ""):
                    t = str(tok).strip().lower()
                    if t and t not in terms:
                        terms.append(t)
        except Exception:
            pass
        if not terms:
            terms = ["google", "youtube", "chatgpt", "gemini", "wikipedia", "gmail"]
        wait_timeout = 12.0 if skip_typing else 7.0
        ok_title, seen = _wait_window_title_contains(target, terms, timeout_s=wait_timeout)
        if ok_title and (not _site_title_looks_loaded(site_key, str(url), str(seen))):
            ok_title = False
        if (not ok_title) and skip_typing:
            # Some Chrome sessions restore a previous tab and ignore the spawn URL.
            # Force explicit navigation in the same window before failing.
            nav_error = _navigate_target_url()
            if nav_error:
                return nav_error
            time.sleep(0.12)
            retry_timeout = 20.0 if sk == "youtube" else 8.0
            ok_title, seen = _wait_window_title_contains(target, terms, timeout_s=retry_timeout)
            if ok_title and (not _site_title_looks_loaded(site_key, str(url), str(seen))):
                ok_title = False
        if (not ok_title) and sk == "youtube":
            seen_norm = str(seen or "").lower().strip()
            if "youtube.com/watch" in seen_norm or "youtube.com/results" in seen_norm:
                # Allow the downstream YouTube transport step to finish playback
                # even when Chrome still reports a provisional URL-title.
                ok_title = True
        if not ok_title:
            return f"No pude verificar apertura real (win={target}, seen_title={seen or '(none)'})."

        if session_id:
            title = _wmctrl_list().get(target, "")
            _record_browser_windows(
                session_id,
                [{"win_id": target, "title": title, "url": url, "site_key": site_key, "ts": time.time()}],
            )
        return None

    if browser == "firefox":
        try:
            ff_profile = _resolve_firefox_profile_name(profile_hint)
            cmd = ["firefox"]
            if ff_profile:
                cmd.extend(["--new-instance", "-P", ff_profile, "--new-window", str(url)])
            else:
                cmd.extend(["--new-tab", str(url)])
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return None
        except FileNotFoundError:
            return "No pude abrir Firefox: comando no encontrado en el sistema."
        except Exception as e:
            return f"No pude abrir Firefox: {e}"

    return f"Navegador no soportado en config para {site_key or 'site'}: {browser}"


def _open_site_urls(entries: list[tuple[str | None, str]], session_id: str | None = None) -> tuple[list[str], str | None]:
    opened = []
    for site_key, url in entries:
        if site_key == "gemini":
            browser_gemini, _profile_hint = _site_browser_profile_hint("gemini")
            if browser_gemini == "chrome":
                gem_opened, gem_error = _open_gemini_client_flow(session_id=session_id)
                if gem_error:
                    return opened, gem_error
                opened.extend(gem_opened)
                continue
        error = _open_url_with_site_context(url, site_key, session_id=session_id)
        if error:
            return opened, error
        opened.append(url)
    return opened, None


def _open_gemini_client_flow(session_id: str | None = None) -> tuple[list[str], str | None]:
    # Deterministic + workspace-safe "human-like" flow:
    # 1) from a Chrome window in the current workspace with expected profile
    # 2) open new window, then Google -> Gemini in that same client/profile
    expected_profile = _expected_profile_directory_for_site("gemini")
    ok, detail = _open_gemini_in_current_workspace_via_ui(
        expected_profile=expected_profile, session_id=session_id
    )
    if not ok:
        return (
            [],
            (
                "No pude abrir Gemini en el cliente configurado dentro de este workspace. "
                f"({detail}) "
                "Dejá visible una ventana de Chrome del perfil diego (Profile 1), por ejemplo Molbot Direct Chat, y repetí."
            ),
        )
    return ["https://www.google.com/", _site_url("gemini")], None


def _site_url(site_key: str) -> str:
    if site_key == "google":
        return SITE_ALIASES["google"]
    if site_key == "chatgpt":
        return SITE_ALIASES["chatgpt"]
    if site_key == "gemini":
        return SITE_ALIASES["gemini"]
    if site_key == "youtube":
        return SITE_ALIASES["youtube"]
    if site_key == "wikipedia":
        return SITE_ALIASES["wikipedia"]
    if site_key == "gmail":
        return SITE_ALIASES["gmail"]
    return SITE_ALIASES.get(site_key, "about:blank")


def _build_site_search_url(site_key: str, query: str) -> str | None:
    template = SITE_SEARCH_TEMPLATES.get(site_key)
    if not template:
        return None
    return template.format(q=quote_plus(query))


def _looks_like_youtube_play_request(normalized: str) -> bool:
    if "youtube" not in normalized and "you tube" not in normalized:
        return False
    playish = any(
        t in normalized
        for t in (
            "reproduc",
            "play",
            "pone",
            "ponelo",
            "ponela",
            "abrilo",
            "abrílo",
            "abrilo y",
            "abrílo y",
            "primer video",
            "ultimo video",
            "último video",
            "abrí un video",
            "abri un video",
            "abrir un video",
        )
    )
    return playish


def _looks_like_open_top_results_request(normalized: str) -> bool:
    text = str(normalized or "")
    if not text:
        return False
    openish = any(t in text for t in ("abr", "open", "lanz", "inici"))
    if not openish:
        return False
    refs_results = any(t in text for t in ("resultado", "resultados", "link", "links", "top"))
    if not refs_results:
        return False
    wants_three = any(t in text for t in (" top 3", "top3", "3 resultados", "tres resultados", "primeros 3", "primeros tres"))
    return wants_three


def _looks_like_open_first_result_request(normalized: str) -> bool:
    text = str(normalized or "")
    if not text:
        return False
    openish = any(t in text for t in ("abr", "open", "lanz", "inici"))
    if not openish:
        return False
    refs_results = any(
        t in text
        for t in (
            "resultado",
            "resultados",
            "link",
            "links",
            "primer resultado",
            "resultado 1",
            "resultado uno",
        )
    )
    if not refs_results:
        return False
    asks_many = any(t in text for t in (" top 3", "top3", "3 resultados", "tres resultados", "primeros 3", "primeros tres"))
    return not asks_many


def _extract_youtube_search_intent_query(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    m = re.search(
        r"(?:en\s+)?(?:you\s*tube|youtube)\b.*?(?:busca|buscá|buscar|investiga|investigar|search|encontra|encontrá|encontrar)\s+(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    q = _sanitize_youtube_query(m.group(1) or "")
    if not q:
        return None
    return q[:400]


def _sanitize_youtube_query(query: str) -> str:
    q = (query or "").strip().strip("\"'").strip()
    if not q:
        return q
    # Cut trailing action clauses ("y abrí...", "y reproducilo...", "y dale play...")
    q = re.sub(
        r"\s+(?:y|e)\s+(?:abri|abr[ií]|abrir|abre|reproduc\w*|pon(?:e|é)\w*|dale\s+play|play)\b.*$",
        "",
        q,
        flags=re.IGNORECASE,
    ).strip()
    # Keep query compact and deterministic for SearXNG/yt-dlp.
    q = re.sub(r"\s+", " ", q).strip(" ,.;:-")
    return q


def _youtube_query_asks_latest(query: str) -> bool:
    n = _normalize_text(query or "")
    if not n:
        return False
    return any(
        t in n
        for t in (
            "ultimo video",
            "ultimo",
            "ultimos",
            "mas reciente",
            "latest",
            "newest",
        )
    )


def _is_direct_youtube_video_url(url: str) -> bool:
    u = str(url or "").strip()
    if not u:
        return False
    p = urlparse(u)
    host = (p.netloc or "").lower()
    if "youtu.be" in host:
        return bool((p.path or "").strip("/"))
    if "youtube.com" not in host:
        return False
    path = (p.path or "").strip()
    if path.startswith("/watch"):
        q = parse_qs(p.query)
        v = str((q.get("v", [""])[0] or "")).strip()
        return bool(v)
    if path.startswith("/shorts/") or path.startswith("/live/"):
        return bool(path.split("/", 2)[-1].strip())
    return False


def _pick_first_youtube_video_url(query: str) -> tuple[str | None, str]:
    clean_query = _sanitize_youtube_query(query) or (query or "").strip()
    wants_latest = _youtube_query_asks_latest(clean_query)

    def from_ytdlp(mode: str) -> str | None:
        ytdlp = shutil.which("yt-dlp")
        if not ytdlp:
            return None
        try:
            proc = subprocess.run(
                [
                    ytdlp,
                    "--no-playlist",
                    "--get-id",
                    "--default-search",
                    "ytsearch",
                    f"{mode}:{clean_query}",
                ],
                capture_output=True,
                text=True,
                timeout=14,
            )
            vid = (proc.stdout or "").strip().splitlines()
            if not vid:
                return None
            v = vid[0].strip()
            if not v:
                return None
            return f"https://www.youtube.com/watch?v={v}"
        except Exception:
            return None

    yd_mode = "ytsearchdate1" if wants_latest else "ytsearch1"
    yd = from_ytdlp(yd_mode)
    if yd:
        chosen = yd
        if "autoplay=" not in chosen:
            chosen = chosen + ("&" if "?" in chosen else "?") + "autoplay=1"
        return chosen, f"ok_ytdlp:{yd_mode}"

    def normalize_candidate(raw_url: str) -> str:
        u = str(raw_url or "").strip()
        if not u:
            return ""
        p = urlparse(u)
        host = (p.netloc or "").lower()
        if "youtube.com" in host or "youtu.be" in host:
            return u
        # Some engines wrap destination in query param (e.g., ?url=...)
        try:
            q = parse_qs(p.query)
            for key in ("url", "target", "u"):
                vals = q.get(key, [])
                if not vals:
                    continue
                cand = str(vals[0]).strip()
                cp = urlparse(cand)
                ch = (cp.netloc or "").lower()
                if "youtube.com" in ch or "youtu.be" in ch:
                    return cand
        except Exception:
            return ""
        return ""

    results: list[dict] = []
    sp = web_search.searxng_search(clean_query, site_key="youtube", max_results=10)
    if sp.get("ok") and isinstance(sp.get("results"), list):
        results.extend([r for r in sp.get("results", []) if isinstance(r, dict)])
    # Fallback: some SearXNG setups don't keep YouTube engine/domain filter stable.
    sp2 = web_search.searxng_search(clean_query, site_key=None, max_results=12)
    if sp2.get("ok") and isinstance(sp2.get("results"), list):
        results.extend([r for r in sp2.get("results", []) if isinstance(r, dict)])
    if not results:
        yd = from_ytdlp("ytsearch1")
        if yd:
            chosen = yd
            if "autoplay=" not in chosen:
                chosen = chosen + ("&" if "?" in chosen else "?") + "autoplay=1"
            return chosen, "ok_ytdlp:fallback"
        return None, "no_results"

    preferred: str | None = None
    for r in results:
        if not isinstance(r, dict):
            continue
        url = normalize_candidate(str(r.get("url", "")).strip())
        if not url:
            continue
        if not _is_direct_youtube_video_url(url):
            continue
        preferred = url
        break
    chosen = preferred
    if not chosen:
        yd = from_ytdlp("ytsearch1")
        if yd:
            chosen = yd
        else:
            return None, "no_youtube_video_url"
    if "autoplay=" not in chosen:
        chosen = chosen + ("&" if "?" in chosen else "?") + "autoplay=1"
    return chosen, "ok"

def _sanitize_history_component(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    if not cleaned:
        return "default"
    return cleaned[: max(8, int(limit))]


def _history_scope_key(session_id: str, model: str | None = None, backend: str | None = None) -> str:
    base = _safe_session_id(session_id)
    model_raw = str(model or "").strip()
    if not model_raw:
        return base
    backend_key = _sanitize_history_component(str(backend or "auto"), limit=20)
    model_key = _sanitize_history_component(model_raw, limit=96)
    return f"{base}__{backend_key}__{model_key}"


def _history_path(session_id: str, model: str | None = None, backend: str | None = None) -> Path:
    return HISTORY_DIR / f"{_history_scope_key(session_id, model=model, backend=backend)}.json"


def _chat_events_path(session_id: str) -> Path:
    sid = _safe_session_id(session_id or "default")
    return HISTORY_DIR / f"{sid}__chat_events.json"


def _load_chat_events_state(session_id: str) -> dict:
    p = _chat_events_path(session_id)
    state = {"seq": 0, "items": []}
    if not p.exists():
        return state
    try:
        raw = json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception:
        return state
    if not isinstance(raw, dict):
        return state
    try:
        seq = max(0, int(raw.get("seq", 0) or 0))
    except Exception:
        seq = 0
    items_raw = raw.get("items", [])
    items: list[dict] = []
    if isinstance(items_raw, list):
        for item in items_raw[-500:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            content = item.get("content")
            if role not in ("user", "assistant", "system") or not isinstance(content, str):
                continue
            try:
                item_seq = max(0, int(item.get("seq", 0) or 0))
            except Exception:
                item_seq = 0
            if item_seq <= 0:
                continue
            items.append(
                {
                    "seq": int(item_seq),
                    "role": role,
                    "content": str(content),
                    "source": str(item.get("source", "")).strip(),
                    "ts": float(item.get("ts", 0.0) or 0.0),
                }
            )
    if items:
        seq = max(seq, int(items[-1].get("seq", 0) or 0))
    return {"seq": int(seq), "items": items[-500:]}


def _save_chat_events_state(session_id: str, state: dict) -> None:
    p = _chat_events_path(session_id)
    seq = 0
    items: list[dict] = []
    if isinstance(state, dict):
        try:
            seq = max(0, int(state.get("seq", 0) or 0))
        except Exception:
            seq = 0
        src_items = state.get("items", [])
        if isinstance(src_items, list):
            for item in src_items[-500:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "")).strip().lower()
                content = item.get("content")
                if role not in ("user", "assistant", "system") or not isinstance(content, str):
                    continue
                try:
                    item_seq = max(0, int(item.get("seq", 0) or 0))
                except Exception:
                    continue
                items.append(
                    {
                        "seq": int(item_seq),
                        "role": role,
                        "content": str(content),
                        "source": str(item.get("source", "")).strip(),
                        "ts": float(item.get("ts", 0.0) or 0.0),
                    }
                )
    payload = {"seq": int(seq), "items": items[-500:]}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _chat_events_append(session_id: str, role: str, content: str, source: str = "", ts: float | None = None) -> dict:
    sid = _safe_session_id(session_id or "default")
    role_norm = str(role or "").strip().lower()
    if role_norm not in ("user", "assistant", "system"):
        role_norm = "assistant"
    text = str(content or "").strip()
    if not text:
        return {}
    now_ts = float(ts) if isinstance(ts, (int, float)) and float(ts) > 0.0 else time.time()
    with _CHAT_EVENTS_LOCK:
        state = _load_chat_events_state(sid)
        seq = int(state.get("seq", 0) or 0) + 1
        item = {
            "seq": int(seq),
            "role": role_norm,
            "content": text,
            "source": str(source or "").strip(),
            "ts": float(now_ts),
        }
        items = state.get("items", [])
        if not isinstance(items, list):
            items = []
        items.append(item)
        state["seq"] = int(seq)
        state["items"] = items[-500:]
        _save_chat_events_state(sid, state)
    return item


def _chat_events_poll(session_id: str, after_seq: int = 0, limit: int = 120) -> dict:
    sid = _safe_session_id(session_id or "default")
    lim = max(1, min(400, int(limit or 120)))
    after = max(0, int(after_seq or 0))
    with _CHAT_EVENTS_LOCK:
        state = _load_chat_events_state(sid)
    items = state.get("items", [])
    if not isinstance(items, list):
        items = []
    fresh = [it for it in items if isinstance(it, dict) and int(it.get("seq", 0) or 0) > after]
    if len(fresh) > lim:
        fresh = fresh[-lim:]
    return {"session_id": sid, "seq": int(state.get("seq", 0) or 0), "after": int(after), "items": fresh}


def _chat_events_reset(session_id: str) -> None:
    sid = _safe_session_id(session_id or "default")
    with _CHAT_EVENTS_LOCK:
        _save_chat_events_state(sid, {"seq": 0, "items": []})


def _load_history(session_id: str, model: str | None = None, backend: str | None = None) -> list:
    p = _history_path(session_id, model=model, backend=backend)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            out = []
            for item in data:
                if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                    out.append({"role": item["role"], "content": item["content"]})
            return out[-200:]
    except Exception:
        return []
    return []


def _save_history(session_id: str, history: list, model: str | None = None, backend: str | None = None) -> None:
    p = _history_path(session_id, model=model, backend=backend)
    payload = history[-200:]
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class ReaderSessionStore:
    def __init__(self, state_path: Path | None = None, lock_path: Path | None = None, max_sessions: int = 200) -> None:
        self.state_path = Path(state_path or READER_STATE_PATH)
        self.lock_path = Path(lock_path or READER_LOCK_PATH)
        self.max_sessions = max(16, int(max_sessions))

    @staticmethod
    def _default_state() -> dict:
        return {
            "version": 1,
            "updated_ts": float(time.time()),
            "sessions": {},
        }

    def _load_state_unlocked(self) -> dict:
        if not self.state_path.exists():
            return self._default_state()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return self._default_state()
        if not isinstance(raw, dict):
            return self._default_state()
        sessions = raw.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        return {
            "version": int(raw.get("version", 1) or 1),
            "updated_ts": float(raw.get("updated_ts", 0.0) or 0.0),
            "sessions": sessions,
        }

    def _save_state_unlocked(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.state_path)

    def _with_state(self, write: bool, func):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lockf:
            mode = fcntl.LOCK_EX if write else fcntl.LOCK_SH
            fcntl.flock(lockf.fileno(), mode)
            state = self._load_state_unlocked()
            out = func(state)
            if write:
                state["updated_ts"] = float(time.time())
                self._save_state_unlocked(state)
            return out

    @staticmethod
    def _split_text_to_chunks(text: str, max_chars: int = 720) -> list[str]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return []
        max_chars = max(320, int(max_chars))
        paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n{2,}", cleaned) if str(p or "").strip()]
        if not paragraphs:
            paragraphs = [re.sub(r"\s+", " ", cleaned).strip()]
        out: list[str] = []
        for para in paragraphs:
            if len(para) <= max_chars:
                out.append(para)
                continue
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
            if not sentences:
                sentences = [para]
            acc = ""
            for sent in sentences:
                if len(sent) > max_chars:
                    if acc:
                        out.append(acc)
                        acc = ""
                    for i in range(0, len(sent), max_chars):
                        piece = sent[i : i + max_chars].strip()
                        if piece:
                            out.append(piece)
                    continue
                candidate = f"{acc} {sent}".strip() if acc else sent
                if len(candidate) <= max_chars:
                    acc = candidate
                else:
                    if acc:
                        out.append(acc)
                    acc = sent
            if acc:
                out.append(acc)
        return [x for x in out if x]

    def _normalize_chunks(self, chunks, text: str = "") -> list[dict]:
        src = chunks
        if not isinstance(src, list):
            src = []
        out: list[dict] = []
        for idx, item in enumerate(src):
            if isinstance(item, str):
                chunk_text = item.strip()
                chunk_id = ""
            elif isinstance(item, dict):
                chunk_text = str(item.get("text", "")).strip()
                chunk_id = str(item.get("id", "")).strip()
            else:
                continue
            if not chunk_text:
                continue
            if not chunk_id:
                chunk_id = f"chunk_{idx + 1:03d}"
            out.append({"id": chunk_id[:80], "text": chunk_text[:8000]})

        if not out and str(text or "").strip():
            split = self._split_text_to_chunks(
                text,
                max_chars=max(320, _int_env("DIRECT_CHAT_READER_CHUNK_MAX_CHARS", 960)),
            )
            for idx, piece in enumerate(split):
                out.append({"id": f"chunk_{idx + 1:03d}", "text": piece[:8000]})

        if not out:
            raise ValueError("reader_chunks_empty")
        return out

    @staticmethod
    def _pending_view(pending: dict | None) -> dict | None:
        if not isinstance(pending, dict):
            return None
        raw_text = str(pending.get("text", ""))
        offset_chars = int(pending.get("offset_chars", 0) or 0)
        if offset_chars < 0:
            offset_chars = 0
        if offset_chars > len(raw_text):
            offset_chars = len(raw_text)
        text_view = raw_text[offset_chars:] if raw_text else ""
        return {
            "chunk_index": int(pending.get("chunk_index", 0) or 0),
            "chunk_id": str(pending.get("chunk_id", "")),
            "text": text_view,
            "offset_chars": offset_chars,
            "offset_quality": str(pending.get("offset_quality", "start") or "start"),
            "last_snippet": str(pending.get("last_snippet", "")),
            "deliveries": int(pending.get("deliveries", 0) or 0),
            "last_delivery_ts": float(pending.get("last_delivery_ts", 0.0) or 0.0),
            "last_barge_in_ts": float(pending.get("last_barge_in_ts", 0.0) or 0.0),
        }

    @staticmethod
    def _bookmark_view(bookmark: dict | None) -> dict | None:
        if not isinstance(bookmark, dict):
            return None
        return {
            "chunk_index": int(bookmark.get("chunk_index", 0) or 0),
            "chunk_id": str(bookmark.get("chunk_id", "")),
            "offset_chars": int(bookmark.get("offset_chars", 0) or 0),
            "quality": str(bookmark.get("quality", "unknown") or "unknown"),
            "last_snippet": str(bookmark.get("last_snippet", "")),
            "updated_ts": float(bookmark.get("updated_ts", 0.0) or 0.0),
        }

    @staticmethod
    def _snippet_around(text: str, offset_chars: int, before: int = 40, after: int = 80) -> str:
        src = str(text or "")
        if not src:
            return ""
        off = max(0, min(int(offset_chars), len(src)))
        start = max(0, off - max(0, int(before)))
        end = min(len(src), off + max(1, int(after)))
        return src[start:end].strip()

    @classmethod
    def _bookmark_from_pending(cls, pending: dict | None, now: float, quality_fallback: str = "unknown") -> dict | None:
        if not isinstance(pending, dict):
            return None
        text = str(pending.get("text", ""))
        offset = int(pending.get("offset_chars", 0) or 0)
        if offset < 0:
            offset = 0
        if offset > len(text):
            offset = len(text)
        quality = str(pending.get("offset_quality", quality_fallback) or quality_fallback)
        snippet = str(pending.get("last_snippet", "")).strip() or cls._snippet_around(text, offset)
        return {
            "chunk_index": int(pending.get("chunk_index", 0) or 0),
            "chunk_id": str(pending.get("chunk_id", "")),
            "offset_chars": offset,
            "quality": quality[:24],
            "last_snippet": snippet[:220],
            "updated_ts": float(now),
        }

    @classmethod
    def _set_pending_offset(cls, pending: dict, offset_chars: int, now: float, quality: str) -> None:
        text = str(pending.get("text", ""))
        off = max(0, min(int(offset_chars), len(text)))
        pending["offset_chars"] = off
        pending["offset_quality"] = str(quality or "unknown")[:24]
        pending["offset_updated_ts"] = float(now)
        pending["last_snippet"] = cls._snippet_around(text, off)[:220]

    @staticmethod
    def _rewind_sentence_offset(text: str, offset_chars: int) -> int:
        src = str(text or "")
        if not src:
            return 0
        off = max(0, min(int(offset_chars), len(src)))
        if off <= 0:
            return 0
        starts = [0]
        for m in re.finditer(r"[.!?]\s+", src):
            starts.append(m.end())
        starts = sorted(set(starts))
        prev = 0
        curr = 0
        for st in starts:
            if st <= off:
                prev = curr
                curr = st
            else:
                break
        return max(0, min(prev, len(src)))

    @staticmethod
    def _rewind_paragraph_offset(text: str, offset_chars: int) -> int:
        src = str(text or "")
        if not src:
            return 0
        off = max(0, min(int(offset_chars), len(src)))
        if off <= 0:
            return 0
        starts = [0]
        for m in re.finditer(r"\n\s*\n", src):
            starts.append(m.end())
        starts = sorted(set(starts))
        prev = 0
        curr = 0
        for st in starts:
            if st <= off:
                prev = curr
                curr = st
            else:
                break
        return max(0, min(prev, len(src)))

    def _session_view(self, session_id: str, session: dict, include_chunks: bool = False) -> dict:
        chunks = session.get("chunks")
        if not isinstance(chunks, list):
            chunks = []
        cursor = int(session.get("cursor", 0) or 0)
        total = len(chunks)
        pending = self._pending_view(session.get("pending"))
        bookmark_raw = session.get("bookmark")
        if not isinstance(bookmark_raw, dict):
            bookmark_raw = self._bookmark_from_pending(session.get("pending"), now=float(time.time()), quality_fallback="pending")
        bookmark = self._bookmark_view(bookmark_raw)
        payload = {
            "ok": True,
            "exists": True,
            "session_id": str(session_id),
            "cursor": max(0, cursor),
            "total_chunks": total,
            "done": bool(cursor >= total and pending is None),
            "has_pending": pending is not None,
            "pending": pending,
            "bookmark": bookmark,
            "barge_in_count": int(session.get("barge_in_count", 0) or 0),
            "last_barge_in_detail": str(session.get("last_barge_in_detail", "")),
            "last_barge_in_ts": float(session.get("last_barge_in_ts", 0.0) or 0.0),
            "last_event": str(session.get("last_event", "")),
            "reader_state": str(session.get("reader_state", "paused") or "paused"),
            "updated_ts": float(session.get("updated_ts", 0.0) or 0.0),
            "created_ts": float(session.get("created_ts", 0.0) or 0.0),
            "last_commit_ts": float(session.get("last_commit_ts", 0.0) or 0.0),
            "continuous_active": bool(session.get("continuous_active", False)),
            "continuous_enabled": bool(session.get("continuous_enabled", session.get("continuous_active", False))),
            "manual_mode": bool(session.get("manual_mode", False)),
            "continuous_reason": str(session.get("continuous_reason", "")),
            "continuous_updated_ts": float(session.get("continuous_updated_ts", 0.0) or 0.0),
            "last_chunk_emit_ts": float(session.get("last_chunk_emit_ts", 0.0) or 0.0),
            "burst_window_start_ts": float(session.get("burst_window_start_ts", 0.0) or 0.0),
            "burst_chunks_in_window": int(session.get("burst_chunks_in_window", 0) or 0),
        }
        meta = session.get("metadata")
        if isinstance(meta, dict):
            payload["metadata"] = {str(k): v for k, v in meta.items() if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
        if include_chunks:
            payload["chunks"] = [
                {"id": str(item.get("id", "")), "text": str(item.get("text", ""))}
                for item in chunks
                if isinstance(item, dict)
            ]
        return payload

    @staticmethod
    def _session_missing(session_id: str) -> dict:
        return {
            "ok": False,
            "exists": False,
            "session_id": str(session_id),
            "error": "reader_session_not_found",
        }

    @staticmethod
    def _prune_sessions(state: dict, max_sessions: int) -> None:
        sessions = state.get("sessions")
        if not isinstance(sessions, dict):
            state["sessions"] = {}
            return
        if len(sessions) <= max_sessions:
            return
        sortable: list[tuple[float, str]] = []
        for sid, sess in sessions.items():
            if not isinstance(sid, str) or not isinstance(sess, dict):
                continue
            ts = float(sess.get("updated_ts", 0.0) or 0.0)
            sortable.append((ts, sid))
        sortable.sort(key=lambda x: x[0])
        remove_count = max(0, len(sortable) - max_sessions)
        for _, sid in sortable[:remove_count]:
            sessions.pop(sid, None)

    def summary(self, include_sessions: bool = False) -> dict:
        def _read(state: dict) -> dict:
            sessions = state.get("sessions", {})
            count = len(sessions) if isinstance(sessions, dict) else 0
            out = {
                "ok": True,
                "mode": "reader_v0",
                "state_file": str(self.state_path),
                "session_count": int(count),
                "updated_ts": float(state.get("updated_ts", 0.0) or 0.0),
            }
            if include_sessions and isinstance(sessions, dict):
                out["sessions"] = sorted([str(k) for k in sessions.keys()])[:120]
            return out

        return self._with_state(False, _read)

    def start_session(
        self,
        session_id: str,
        chunks,
        text: str = "",
        reset: bool = True,
        metadata: dict | None = None,
    ) -> dict:
        sid = _safe_session_id(session_id)
        normalized_chunks = self._normalize_chunks(chunks, text=text)
        meta: dict = {}
        if isinstance(metadata, dict):
            for k, v in metadata.items():
                if not isinstance(k, str):
                    continue
                if isinstance(v, (str, int, float, bool)):
                    meta[k[:64]] = v

        def _write(state: dict) -> dict:
            sessions = state.get("sessions")
            if not isinstance(sessions, dict):
                sessions = {}
                state["sessions"] = sessions
            now = float(time.time())
            exists = isinstance(sessions.get(sid), dict)
            if exists and not reset:
                out = self._session_view(sid, sessions[sid], include_chunks=False)
                out["started"] = False
                out["detail"] = "reader_session_exists"
                return out
            sessions[sid] = {
                "chunks": normalized_chunks,
                "cursor": 0,
                "pending": None,
                "bookmark": None,
                "continuous_active": False,
                "continuous_enabled": False,
                "manual_mode": False,
                "continuous_reason": "session_started",
                "continuous_updated_ts": now,
                "last_chunk_emit_ts": 0.0,
                "burst_window_start_ts": 0.0,
                "burst_chunks_in_window": 0,
                "barge_in_count": 0,
                "last_barge_in_detail": "",
                "last_barge_in_ts": 0.0,
                "last_event": "session_started",
                "reader_state": "paused",
                "last_commit_ts": 0.0,
                "created_ts": now,
                "updated_ts": now,
                "metadata": meta,
            }
            self._prune_sessions(state, self.max_sessions)
            out = self._session_view(sid, sessions[sid], include_chunks=False)
            out["started"] = True
            out["reset"] = bool(reset)
            return out

        return self._with_state(True, _write)

    def get_session(self, session_id: str, include_chunks: bool = False) -> dict:
        sid = _safe_session_id(session_id)

        def _read(state: dict) -> dict:
            sessions = state.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            return self._session_view(sid, sessions[sid], include_chunks=include_chunks)

        return self._with_state(False, _read)

    def next_chunk(self, session_id: str) -> dict:
        sid = _safe_session_id(session_id)

        def _write(state: dict) -> dict:
            sessions = state.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            chunks = sess.get("chunks")
            if not isinstance(chunks, list):
                chunks = []
                sess["chunks"] = chunks
            cursor = max(0, int(sess.get("cursor", 0) or 0))
            now = float(time.time())
            pacing_cfg = _reader_pacing_config()
            burst_window_sec = float(pacing_cfg.get("burst_window_ms", 0)) / 1000.0

            def _touch_delivery_window() -> None:
                prev_start = float(sess.get("burst_window_start_ts", 0.0) or 0.0)
                prev_count = int(sess.get("burst_chunks_in_window", 0) or 0)
                if prev_start <= 0.0 or burst_window_sec <= 0.0 or (now - prev_start) >= burst_window_sec:
                    sess["burst_window_start_ts"] = now
                    sess["burst_chunks_in_window"] = 1
                else:
                    sess["burst_window_start_ts"] = prev_start
                    sess["burst_chunks_in_window"] = max(0, prev_count) + 1
                sess["last_chunk_emit_ts"] = now

            pending = sess.get("pending")
            if isinstance(pending, dict):
                deliveries = int(pending.get("deliveries", 0) or 0) + 1
                pending["deliveries"] = deliveries
                pending["last_delivery_ts"] = now
                if "offset_chars" not in pending:
                    pending["offset_chars"] = 0
                if "offset_quality" not in pending:
                    pending["offset_quality"] = "start"
                if "last_snippet" not in pending:
                    pending["last_snippet"] = self._snippet_around(str(pending.get("text", "")), int(pending.get("offset_chars", 0) or 0))
                sess["bookmark"] = self._bookmark_from_pending(pending, now=now, quality_fallback="pending")
                sess["reader_state"] = "reading"
                _touch_delivery_window()
                sess["updated_ts"] = now
                sess["last_event"] = "next_replay"
                out = self._session_view(sid, sess, include_chunks=False)
                out["replayed"] = True
                out["chunk"] = self._pending_view(pending)
                return out
            if cursor >= len(chunks):
                sess["updated_ts"] = now
                sess["last_event"] = "next_eof"
                out = self._session_view(sid, sess, include_chunks=False)
                out["replayed"] = False
                out["chunk"] = None
                return out
            raw = chunks[cursor] if isinstance(chunks[cursor], dict) else {}
            chunk_id = str(raw.get("id", f"chunk_{cursor + 1:03d}")).strip() or f"chunk_{cursor + 1:03d}"
            chunk_text = str(raw.get("text", "")).strip()
            pending = {
                "chunk_index": cursor,
                "chunk_id": chunk_id[:80],
                "text": chunk_text[:8000],
                "offset_chars": 0,
                "offset_quality": "start",
                "last_snippet": self._snippet_around(chunk_text[:8000], 0),
                "deliveries": 1,
                "last_delivery_ts": now,
                "last_barge_in_ts": 0.0,
            }
            sess["pending"] = pending
            sess["bookmark"] = self._bookmark_from_pending(pending, now=now, quality_fallback="start")
            sess["reader_state"] = "reading"
            _touch_delivery_window()
            sess["updated_ts"] = now
            sess["last_event"] = "next"
            out = self._session_view(sid, sess, include_chunks=False)
            out["replayed"] = False
            out["chunk"] = self._pending_view(pending)
            return out

        return self._with_state(True, _write)

    def commit(self, session_id: str, chunk_id: str = "", chunk_index: int | None = None, reason: str = "") -> dict:
        sid = _safe_session_id(session_id)
        expected_id = str(chunk_id or "").strip()
        expected_index = None if chunk_index is None else int(chunk_index)

        def _write(state: dict) -> dict:
            sessions = state.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            pending = sess.get("pending")
            if not isinstance(pending, dict):
                out = self._session_view(sid, sess, include_chunks=False)
                out["committed"] = False
                out["detail"] = "reader_no_pending_chunk"
                return out
            got_id = str(pending.get("chunk_id", ""))
            got_index = int(pending.get("chunk_index", 0) or 0)
            if expected_id and expected_id != got_id:
                out = self._session_view(sid, sess, include_chunks=False)
                out["ok"] = False
                out["error"] = "reader_commit_chunk_mismatch"
                out["expected_chunk_id"] = expected_id
                out["pending_chunk_id"] = got_id
                return out
            if expected_index is not None and expected_index != got_index:
                out = self._session_view(sid, sess, include_chunks=False)
                out["ok"] = False
                out["error"] = "reader_commit_index_mismatch"
                out["expected_chunk_index"] = expected_index
                out["pending_chunk_index"] = got_index
                return out
            now = float(time.time())
            cursor = max(0, int(sess.get("cursor", 0) or 0))
            sess["cursor"] = max(cursor, got_index + 1)
            sess["pending"] = None
            sess["bookmark"] = None
            sess["last_commit_ts"] = now
            sess["updated_ts"] = now
            sess["last_event"] = "commit"
            chunks = sess.get("chunks")
            total = len(chunks) if isinstance(chunks, list) else 0
            if int(sess.get("cursor", 0) or 0) >= total:
                sess["continuous_active"] = False
                sess["continuous_enabled"] = False
                sess["continuous_reason"] = "eof"
                sess["continuous_updated_ts"] = now
                sess["reader_state"] = "paused"
            elif bool(sess.get("continuous_enabled", False)):
                sess["reader_state"] = "reading"
            else:
                sess["reader_state"] = "paused"
            if reason:
                sess["last_commit_reason"] = str(reason)[:120]
            out = self._session_view(sid, sess, include_chunks=False)
            out["committed"] = True
            out["committed_chunk_id"] = got_id
            out["committed_chunk_index"] = got_index
            return out

        return self._with_state(True, _write)

    def mark_barge_in(
        self,
        session_id: str,
        detail: str = "",
        keyword: str = "",
        offset_hint: int | None = None,
        playback_ms: float | None = None,
    ) -> dict:
        sid = _safe_session_id(session_id)
        detail_clean = str(detail or "barge_in_triggered").strip() or "barge_in_triggered"
        keyword_clean = str(keyword or "").strip()

        def _write(state: dict) -> dict:
            sessions = state.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            pending = sess.get("pending")
            now = float(time.time())
            if not isinstance(pending, dict):
                out = self._session_view(sid, sess, include_chunks=False)
                out["interrupted"] = False
                out["detail"] = "reader_no_pending_chunk"
                return out
            sess["barge_in_count"] = int(sess.get("barge_in_count", 0) or 0) + 1
            sess["last_barge_in_detail"] = detail_clean[:240]
            sess["last_barge_in_ts"] = now
            if keyword_clean:
                sess["last_barge_in_keyword"] = keyword_clean[:80]
            pending["last_barge_in_ts"] = now
            pending["deliveries"] = int(pending.get("deliveries", 0) or 0)
            pending_text = str(pending.get("text", ""))
            text_len = len(pending_text)
            offset = int(pending.get("offset_chars", 0) or 0)
            prev_offset = int(offset)
            quality = "approx"
            if offset_hint is not None:
                try:
                    offset = int(offset_hint)
                    quality = "hint"
                except Exception:
                    offset = int(pending.get("offset_chars", 0) or 0)
            elif playback_ms is not None:
                cps = max(4.0, float(os.environ.get("DIRECT_CHAT_READER_APPROX_CHARS_PER_SEC", "16")))
                offset = int((max(0.0, float(playback_ms)) / 1000.0) * cps)
                quality = "playback_ms"
            else:
                last_delivery_ts = float(pending.get("last_delivery_ts", 0.0) or 0.0)
                if last_delivery_ts > 0.0:
                    cps = max(4.0, float(os.environ.get("DIRECT_CHAT_READER_APPROX_CHARS_PER_SEC", "16")))
                    elapsed = max(0.0, now - last_delivery_ts)
                    offset = int(elapsed * cps)
            # Prefer already-known live progress when available to avoid jumping
            # backwards/forwards from rough time estimates.
            prev_quality = str(pending.get("offset_quality", "") or "").strip().lower()
            if prev_offset > 0 and prev_quality in ("ui_live", "live", "phrase", "rewind_sentence", "rewind_paragraph"):
                offset = max(prev_offset, int(offset))
                quality = "existing_live"
            if text_len > 0:
                offset = max(0, min(offset, text_len))
            else:
                offset = 0
            self._set_pending_offset(pending, offset_chars=offset, now=now, quality=quality)
            sess["bookmark"] = self._bookmark_from_pending(pending, now=now, quality_fallback=quality)
            sess["updated_ts"] = now
            sess["last_event"] = "barge_in"
            sess["continuous_active"] = False
            sess["continuous_enabled"] = False
            sess["continuous_reason"] = "barge_in"
            sess["continuous_updated_ts"] = now
            sess["reader_state"] = "commenting"
            out = self._session_view(sid, sess, include_chunks=False)
            out["interrupted"] = True
            out["chunk"] = self._pending_view(pending)
            return out

        return self._with_state(True, _write)

    def update_progress(
        self,
        session_id: str,
        chunk_id: str = "",
        offset_chars: int = 0,
        quality: str = "ui_live",
    ) -> dict:
        sid = _safe_session_id(session_id)
        wanted_chunk = str(chunk_id or "").strip()
        qual = str(quality or "ui_live").strip().lower()[:24] or "ui_live"

        def _write(state: dict) -> dict:
            sessions = state.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            pending = sess.get("pending")
            if not isinstance(pending, dict):
                out = self._session_view(sid, sess, include_chunks=False)
                out["progress_updated"] = False
                out["detail"] = "reader_no_pending_chunk"
                return out
            got_chunk = str(pending.get("chunk_id", "")).strip()
            if wanted_chunk and got_chunk and wanted_chunk != got_chunk:
                out = self._session_view(sid, sess, include_chunks=False)
                out["progress_updated"] = False
                out["detail"] = "reader_progress_chunk_mismatch"
                out["expected_chunk_id"] = wanted_chunk
                out["pending_chunk_id"] = got_chunk
                return out
            now = float(time.time())
            try:
                target = int(offset_chars)
            except Exception:
                target = int(pending.get("offset_chars", 0) or 0)
            current = int(pending.get("offset_chars", 0) or 0)
            # Never move backwards from live UI updates.
            if target < current:
                target = current
            self._set_pending_offset(pending, offset_chars=target, now=now, quality=qual)
            sess["bookmark"] = self._bookmark_from_pending(pending, now=now, quality_fallback=qual)
            sess["updated_ts"] = now
            sess["last_event"] = "reader_progress_update"
            out = self._session_view(sid, sess, include_chunks=False)
            out["progress_updated"] = True
            out["chunk"] = self._pending_view(pending)
            return out

        return self._with_state(True, _write)

    def set_continuous(self, session_id: str, active: bool, reason: str = "") -> dict:
        sid = _safe_session_id(session_id)
        reason_clean = str(reason or "").strip()[:120]

        def _write(state: dict) -> dict:
            sessions = state.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            now = float(time.time())
            sess["continuous_active"] = bool(active)
            sess["continuous_enabled"] = bool(active)
            if bool(active):
                sess["manual_mode"] = False
            sess["continuous_reason"] = reason_clean or ("continuous_on" if active else "continuous_off")
            sess["continuous_updated_ts"] = now
            sess["updated_ts"] = now
            sess["last_event"] = "continuous_on" if active else "continuous_off"
            if active:
                sess["reader_state"] = "reading"
            elif str(sess.get("reader_state", "")) == "reading":
                sess["reader_state"] = "paused"
            out = self._session_view(sid, sess, include_chunks=False)
            out["continuous_changed"] = True
            return out

        return self._with_state(True, _write)

    def set_manual_mode(self, session_id: str, enabled: bool, reason: str = "") -> dict:
        sid = _safe_session_id(session_id)
        reason_clean = str(reason or "").strip()[:120]

        def _write(state_obj: dict) -> dict:
            sessions = state_obj.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            now = float(time.time())
            on = bool(enabled)
            sess["manual_mode"] = on
            sess["updated_ts"] = now
            sess["last_event"] = "manual_mode_on" if on else "manual_mode_off"
            sess["manual_mode_reason"] = reason_clean or ("manual_mode_on" if on else "manual_mode_off")
            if on:
                sess["continuous_active"] = False
                sess["continuous_enabled"] = False
                sess["continuous_reason"] = "manual_mode_on"
                sess["continuous_updated_ts"] = now
                if str(sess.get("reader_state", "")) == "reading":
                    sess["reader_state"] = "paused"
            out = self._session_view(sid, sess, include_chunks=False)
            out["manual_mode_changed"] = True
            return out

        return self._with_state(True, _write)

    def set_reader_state(self, session_id: str, state: str, reason: str = "") -> dict:
        sid = _safe_session_id(session_id)
        wanted = str(state or "").strip().lower()
        if wanted not in ("reading", "paused", "commenting"):
            wanted = "paused"
        reason_clean = str(reason or "").strip()[:120]

        def _write(state_obj: dict) -> dict:
            sessions = state_obj.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            now = float(time.time())
            sess["reader_state"] = wanted
            if reason_clean:
                sess["reader_state_reason"] = reason_clean
            sess["updated_ts"] = now
            sess["last_event"] = f"reader_state_{wanted}"
            out = self._session_view(sid, sess, include_chunks=False)
            out["reader_state_changed"] = True
            return out

        return self._with_state(True, _write)

    def seek_phrase(self, session_id: str, phrase: str) -> dict:
        sid = _safe_session_id(session_id)
        needle = str(phrase or "").strip()

        def _write(state_obj: dict) -> dict:
            sessions = state_obj.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            now = float(time.time())
            chunks = sess.get("chunks")
            if not isinstance(chunks, list):
                chunks = []
                sess["chunks"] = chunks
            pending = sess.get("pending") if isinstance(sess.get("pending"), dict) else None
            cursor = max(0, int(sess.get("cursor", 0) or 0))
            if pending is None:
                base_idx = min(max(0, cursor - 1), len(chunks) - 1) if chunks else -1
                if base_idx < 0:
                    out = self._session_view(sid, sess, include_chunks=False)
                    out["ok"] = False
                    out["error"] = "reader_no_chunk_for_seek"
                    return out
                raw = chunks[base_idx] if isinstance(chunks[base_idx], dict) else {}
                pending = {
                    "chunk_index": base_idx,
                    "chunk_id": str(raw.get("id", f"chunk_{base_idx + 1:03d}"))[:80],
                    "text": str(raw.get("text", ""))[:8000],
                    "offset_chars": 0,
                    "offset_quality": "start",
                    "last_snippet": "",
                    "deliveries": 0,
                    "last_delivery_ts": 0.0,
                    "last_barge_in_ts": 0.0,
                }
                sess["pending"] = pending
            ptext = str(pending.get("text", ""))
            idx = ptext.lower().find(needle.lower()) if needle else -1
            seek_wrapped = False
            if idx < 0:
                next_idx = int(pending.get("chunk_index", 0) or 0) + 1
                scan_ranges = [range(max(0, next_idx), len(chunks))]
                if next_idx > 0 and chunks:
                    scan_ranges.append(range(0, min(next_idx, len(chunks))))
                for pass_idx, scan_range in enumerate(scan_ranges):
                    for scan_idx in scan_range:
                        raw_n = chunks[scan_idx] if isinstance(chunks[scan_idx], dict) else {}
                        text_n = str(raw_n.get("text", ""))
                        idx_n = text_n.lower().find(needle.lower()) if needle else -1
                        if idx_n < 0:
                            continue
                        pending = {
                            "chunk_index": scan_idx,
                            "chunk_id": str(raw_n.get("id", f"chunk_{scan_idx + 1:03d}"))[:80],
                            "text": text_n[:8000],
                            "offset_chars": 0,
                            "offset_quality": "start",
                            "last_snippet": "",
                            "deliveries": 0,
                            "last_delivery_ts": 0.0,
                            "last_barge_in_ts": 0.0,
                        }
                        sess["pending"] = pending
                        ptext = str(pending.get("text", ""))
                        idx = idx_n
                        seek_wrapped = bool(pass_idx > 0)
                        break
                    if idx >= 0:
                        break
            if idx < 0:
                out = self._session_view(sid, sess, include_chunks=False)
                out["ok"] = False
                out["error"] = "reader_phrase_not_found"
                out["phrase"] = needle
                return out
            self._set_pending_offset(pending, offset_chars=idx, now=now, quality="phrase")
            sess["bookmark"] = self._bookmark_from_pending(pending, now=now, quality_fallback="phrase")
            sess["reader_state"] = "reading"
            sess["updated_ts"] = now
            sess["last_event"] = "reader_seek_phrase"
            out = self._session_view(sid, sess, include_chunks=False)
            out["seeked"] = True
            out["chunk"] = self._pending_view(pending)
            out["seek_wrapped"] = bool(seek_wrapped)
            return out

        return self._with_state(True, _write)

    def rewind(self, session_id: str, unit: str = "sentence") -> dict:
        sid = _safe_session_id(session_id)
        mode = "paragraph" if str(unit or "").strip().lower().startswith("para") else "sentence"

        def _write(state_obj: dict) -> dict:
            sessions = state_obj.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            now = float(time.time())
            chunks = sess.get("chunks")
            if not isinstance(chunks, list):
                chunks = []
                sess["chunks"] = chunks
            pending = sess.get("pending") if isinstance(sess.get("pending"), dict) else None
            cursor = max(0, int(sess.get("cursor", 0) or 0))
            if pending is None:
                idx = min(max(0, cursor - 1), len(chunks) - 1) if chunks else -1
                if idx < 0:
                    out = self._session_view(sid, sess, include_chunks=False)
                    out["ok"] = False
                    out["error"] = "reader_no_chunk_for_rewind"
                    return out
                raw = chunks[idx] if isinstance(chunks[idx], dict) else {}
                pending = {
                    "chunk_index": idx,
                    "chunk_id": str(raw.get("id", f"chunk_{idx + 1:03d}"))[:80],
                    "text": str(raw.get("text", ""))[:8000],
                    "offset_chars": 0,
                    "offset_quality": "start",
                    "last_snippet": "",
                    "deliveries": 0,
                    "last_delivery_ts": 0.0,
                    "last_barge_in_ts": 0.0,
                }
                sess["pending"] = pending
            ptext = str(pending.get("text", ""))
            cur = int(pending.get("offset_chars", 0) or 0)
            if mode == "paragraph":
                target = self._rewind_paragraph_offset(ptext, cur)
                quality = "rewind_paragraph"
            else:
                target = self._rewind_sentence_offset(ptext, cur)
                quality = "rewind_sentence"
            self._set_pending_offset(pending, offset_chars=target, now=now, quality=quality)
            sess["bookmark"] = self._bookmark_from_pending(pending, now=now, quality_fallback=quality)
            sess["reader_state"] = "reading"
            sess["updated_ts"] = now
            sess["last_event"] = "reader_rewind"
            out = self._session_view(sid, sess, include_chunks=False)
            out["rewound"] = True
            out["rewind_unit"] = mode
            out["chunk"] = self._pending_view(pending)
            return out

        return self._with_state(True, _write)

    def jump_to_chunk(self, session_id: str, chunk_number: int) -> dict:
        sid = _safe_session_id(session_id)
        try:
            requested = int(chunk_number)
        except Exception:
            requested = 0

        def _write(state_obj: dict) -> dict:
            sessions = state_obj.get("sessions", {})
            if not isinstance(sessions, dict) or sid not in sessions or not isinstance(sessions.get(sid), dict):
                return self._session_missing(sid)
            sess = sessions[sid]
            chunks = sess.get("chunks")
            if not isinstance(chunks, list):
                chunks = []
                sess["chunks"] = chunks
            total = len(chunks)
            out = self._session_view(sid, sess, include_chunks=False)
            if total <= 0:
                out["ok"] = False
                out["error"] = "reader_no_chunks"
                return out
            if requested < 1 or requested > total:
                out["ok"] = False
                out["error"] = "reader_chunk_out_of_range"
                out["requested_chunk_number"] = int(requested)
                out["total_chunks"] = int(total)
                return out
            idx = int(requested - 1)
            raw = chunks[idx] if isinstance(chunks[idx], dict) else {}
            chunk_id = str(raw.get("id", f"chunk_{idx + 1:03d}")).strip() or f"chunk_{idx + 1:03d}"
            chunk_text = str(raw.get("text", "")).strip()
            now = float(time.time())
            pending = {
                "chunk_index": idx,
                "chunk_id": chunk_id[:80],
                "text": chunk_text[:8000],
                "offset_chars": 0,
                "offset_quality": "jump",
                "last_snippet": self._snippet_around(chunk_text[:8000], 0),
                "deliveries": 0,
                "last_delivery_ts": 0.0,
                "last_barge_in_ts": 0.0,
            }
            sess["cursor"] = idx
            sess["pending"] = pending
            sess["bookmark"] = self._bookmark_from_pending(pending, now=now, quality_fallback="jump")
            sess["reader_state"] = "reading"
            sess["updated_ts"] = now
            sess["last_event"] = "reader_jump_chunk"
            out = self._session_view(sid, sess, include_chunks=False)
            out["jumped"] = True
            out["requested_chunk_number"] = int(requested)
            out["target_chunk_number"] = int(idx + 1)
            out["chunk"] = self._pending_view(pending)
            return out

        return self._with_state(True, _write)

    def is_continuous(self, session_id: str) -> bool:
        sid = _safe_session_id(session_id)

        def _read(state: dict) -> bool:
            sessions = state.get("sessions", {})
            if not isinstance(sessions, dict):
                return False
            sess = sessions.get(sid)
            if not isinstance(sess, dict):
                return False
            return bool(sess.get("continuous_enabled", sess.get("continuous_active", False)))

        return bool(self._with_state(False, _read))


_READER_STORE = ReaderSessionStore()


class ReaderLibraryIndex:
    def __init__(
        self,
        library_dir: Path | None = None,
        index_path: Path | None = None,
        lock_path: Path | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.library_dir = Path(library_dir or READER_LIBRARY_DIR)
        self.index_path = Path(index_path or READER_LIBRARY_INDEX_PATH)
        self.lock_path = Path(lock_path or READER_LIBRARY_LOCK_PATH)
        self.cache_dir = Path(cache_dir or READER_CACHE_DIR)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _default_state(self) -> dict:
        return {
            "version": 1,
            "library_dir": str(self.library_dir),
            "updated_at": self._now_iso(),
            "books": {},
        }

    def _load_state_unlocked(self) -> dict:
        if not self.index_path.exists():
            return self._default_state()
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return self._default_state()
        if not isinstance(raw, dict):
            return self._default_state()
        books = raw.get("books")
        if not isinstance(books, dict):
            books = {}
        return {
            "version": int(raw.get("version", 1) or 1),
            "library_dir": str(raw.get("library_dir", str(self.library_dir))),
            "updated_at": str(raw.get("updated_at", "")),
            "books": books,
        }

    def _save_state_unlocked(self, state: dict) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.index_path)

    def _with_state(self, write: bool, func):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lockf:
            mode = fcntl.LOCK_EX if write else fcntl.LOCK_SH
            fcntl.flock(lockf.fileno(), mode)
            state = self._load_state_unlocked()
            out = func(state)
            if write:
                state["updated_at"] = self._now_iso()
                state["library_dir"] = str(self.library_dir)
                self._save_state_unlocked(state)
            return out

    @staticmethod
    def _format_for_path(path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".txt":
            return "txt"
        if ext == ".pdf":
            return "pdf"
        if ext == ".epub":
            return "epub"
        return "unknown"

    @staticmethod
    def _book_id(path: Path, size: int, mtime_ns: int) -> str:
        digest = hashlib.sha256(f"{path.resolve()}:{int(size)}:{int(mtime_ns)}".encode("utf-8")).hexdigest()
        return digest[:32]

    @staticmethod
    def _extract_pdf_text(path: Path) -> tuple[str, str]:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return "", "pdf_extractor_unavailable"
        try:
            reader = PdfReader(str(path))
            parts: list[str] = []
            for page in reader.pages:
                txt = page.extract_text() if page is not None else ""
                if txt:
                    parts.append(str(txt))
            joined = "\n\n".join(parts).strip()
            if not joined:
                return "", "pdf_no_text"
            return joined, ""
        except Exception as e:
            return "", f"pdf_extract_failed:{e}"

    @staticmethod
    def _normalize_text(text: str) -> str:
        raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        paras = [re.sub(r"[ \t]+", " ", p).strip() for p in raw.split("\n")]
        lines = [p for p in paras if p]
        return "\n".join(lines).strip()

    def _extract_text(self, path: Path, fmt: str) -> tuple[str, str]:
        if fmt == "txt":
            try:
                return self._normalize_text(path.read_text(encoding="utf-8", errors="replace")), ""
            except Exception as e:
                return "", f"txt_read_failed:{e}"
        if fmt == "pdf":
            txt, err = self._extract_pdf_text(path)
            if err:
                return "", err
            return self._normalize_text(txt), ""
        if fmt == "epub":
            return "", "not_implemented_epub"
        return "", "unsupported_format"

    def _book_view(self, item: dict) -> dict:
        chars = int(item.get("chars", 0) or 0)
        approx_chunks = int((chars + 239) / 240) if chars > 0 else 0
        out = {
            "book_id": str(item.get("book_id", "")),
            "title": str(item.get("title", "")),
            "format": str(item.get("format", "")),
            "source_path": str(item.get("source_path", "")),
            "updated_at": str(item.get("updated_at", "")),
            "chars": chars,
            "approx_chunks": approx_chunks,
        }
        err = str(item.get("error", "")).strip()
        if err:
            out["error"] = err
        return out

    def list_books(self) -> dict:
        def _read(state: dict) -> dict:
            books_raw = state.get("books", {})
            books: list[dict] = []
            if isinstance(books_raw, dict):
                for item in books_raw.values():
                    if isinstance(item, dict):
                        books.append(self._book_view(item))
            books.sort(key=lambda b: (str(b.get("title", "")).lower(), str(b.get("book_id", ""))))
            return {
                "ok": True,
                "library_dir": str(self.library_dir),
                "index_path": str(self.index_path),
                "updated_at": str(state.get("updated_at", "")),
                "count": len(books),
                "books": books,
            }

        return self._with_state(False, _read)

    def get_book_text(self, book_id: str) -> dict:
        bid = str(book_id or "").strip()
        if not bid:
            return {"ok": False, "error": "reader_book_id_required"}

        def _read(state: dict) -> dict:
            books_raw = state.get("books", {})
            if not isinstance(books_raw, dict):
                return {"ok": False, "error": "reader_book_not_found", "book_id": bid}
            item = books_raw.get(bid)
            if not isinstance(item, dict):
                return {"ok": False, "error": "reader_book_not_found", "book_id": bid}
            cache_path = Path(str(item.get("cached_text_path", "")))
            if not cache_path.exists():
                return {"ok": False, "error": "reader_book_cache_missing", "book_id": bid}
            try:
                text = cache_path.read_text(encoding="utf-8")
            except Exception as e:
                return {"ok": False, "error": f"reader_book_cache_read_failed:{e}", "book_id": bid}
            return {"ok": True, "book_id": bid, "text": text, "book": self._book_view(item)}

        return self._with_state(False, _read)

    def rescan(self) -> dict:
        def _write(state: dict) -> dict:
            self.library_dir.mkdir(parents=True, exist_ok=True)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            books: dict[str, dict] = {}
            scanned = 0
            cached = 0
            errors = 0
            for path in sorted(self.library_dir.rglob("*")):
                if not path.is_file():
                    continue
                fmt = self._format_for_path(path)
                if fmt not in ("txt", "pdf", "epub"):
                    continue
                scanned += 1
                try:
                    st = path.stat()
                except Exception:
                    continue
                bid = self._book_id(path, st.st_size, st.st_mtime_ns)
                cache_path = self.cache_dir / f"{bid}.txt"
                text, err = self._extract_text(path, fmt)
                chars = len(text)
                if text:
                    cache_path.write_text(text, encoding="utf-8")
                    cached += 1
                else:
                    err = err or "empty_text"
                    errors += 1
                    try:
                        cache_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                item = {
                    "book_id": bid,
                    "title": path.stem.strip() or path.name,
                    "format": fmt,
                    "source_path": str(path.resolve()),
                    "size": int(st.st_size),
                    "mtime_ns": int(st.st_mtime_ns),
                    "cached_text_path": str(cache_path),
                    "chars": int(chars),
                    "updated_at": self._now_iso(),
                }
                if err:
                    item["error"] = err
                books[bid] = item
            state["books"] = books
            return {
                "ok": True,
                "library_dir": str(self.library_dir),
                "scanned_files": scanned,
                "cached_books": cached,
                "errors": errors,
                "count": len(books),
            }

        out = self._with_state(True, _write)
        out["books"] = self.list_books().get("books", [])
        return out


_READER_LIBRARY = ReaderLibraryIndex()


def _guardrail_check(session_id: str, tool_name: str, params: dict | None = None) -> tuple[bool, str]:
    if str(os.environ.get("GUARDRAIL_ENABLED", "1")).strip().lower() not in ("1", "true", "yes"):
        return True, "guardrail_disabled"
    fail_closed = str(os.environ.get("GUARDRAIL_FAIL_CLOSED", "0")).strip().lower() in ("1", "true", "yes")
    if not GUARDRAIL_SCRIPT_PATH.exists():
        return True, "guardrail_script_missing"
    payload = params or {}
    try:
        proc = subprocess.run(
            [str(GUARDRAIL_SCRIPT_PATH), str(session_id), str(tool_name), json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=6.0,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
    except Exception as e:
        if fail_closed:
            return False, f"guardrail_exec_error: {e}"
        return True, f"guardrail_bypass_exec_error: {e}"
    detail = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        # Infra failures may include noisy stderr before GUARDRAIL_ERROR.
        if (not fail_closed) and ("GUARDRAIL_ERROR:" in detail):
            return True, f"guardrail_bypass_infra_error: {detail}"
        return False, detail or f"guardrail_denied rc={proc.returncode}"
    return True, detail or "guardrail_ok"


def _guardrail_block_reply(tool_name: str, detail: str) -> str:
    reason = str(detail or "").strip()[:280]
    return (
        f"Bloqueado por guardrail ({tool_name}). "
        f"Detalle: {reason if reason else 'policy_denied'}"
    )


def _normalize_allowed_tool_name(name: str) -> str:
    t = str(name or "").strip().lower()
    alias = {
        "escritorio": "desktop",
        "modelo": "model",
        "voz": "tts",
    }
    return alias.get(t, t)


def _extract_allowed_tools(payload: dict) -> set[str]:
    out: set[str] = set()

    raw = payload.get("allowed_tools")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v:
                out.add(_normalize_allowed_tool_name(str(k)))
    elif isinstance(raw, (list, tuple, set)):
        for item in raw:
            if isinstance(item, str):
                t = _normalize_allowed_tool_name(item)
                if t:
                    out.add(t)

    # Backward compatibility with legacy clients/scripts that still send {"tools": {...}}.
    legacy = payload.get("tools")
    if isinstance(legacy, dict):
        for k, v in legacy.items():
            if v:
                t = _normalize_allowed_tool_name(str(k))
                if t:
                    out.add(t)
    elif isinstance(legacy, (list, tuple, set)):
        for item in legacy:
            if isinstance(item, str):
                t = _normalize_allowed_tool_name(item)
                if t:
                    out.add(t)

    return out


def _reader_pacing_config() -> dict:
    min_delay_ms = max(250, _int_env("DIRECT_CHAT_READER_PACING_MIN_MS", 1500))
    burst_window_ms = max(1000, _int_env("DIRECT_CHAT_READER_BURST_WINDOW_MS", 10000))
    burst_max_chunks = max(1, _int_env("DIRECT_CHAT_READER_BURST_MAX_CHUNKS", 6))
    return {
        "min_delay_ms": int(min_delay_ms),
        "burst_window_ms": int(burst_window_ms),
        "burst_max_chunks": int(burst_max_chunks),
    }


def _reader_tts_wait_timeout_ms(text_len: int = 0) -> int:
    env_ms = _int_env("DIRECT_CHAT_READER_TTS_WAIT_TIMEOUT_MS", 0)
    if env_ms > 0:
        return max(1500, int(env_ms))
    return int(max(1500.0, _reader_tts_end_max_wait_sec(text_len=max(0, int(text_len))) * 1000.0))


def _reader_pacing_wait_ms(state: dict | None, now_ts: float | None = None, cfg: dict | None = None) -> int:
    st = state if isinstance(state, dict) else {}
    conf = cfg if isinstance(cfg, dict) else _reader_pacing_config()
    now = float(now_ts if now_ts is not None else time.time())
    min_delay_ms = int(conf.get("min_delay_ms", 1500) or 1500)
    burst_window_ms = int(conf.get("burst_window_ms", 10000) or 10000)
    burst_max_chunks = int(conf.get("burst_max_chunks", 6) or 6)

    last_emit_ts = float(st.get("last_chunk_emit_ts", 0.0) or 0.0)
    wait_interval_ms = 0
    if last_emit_ts > 0.0:
        elapsed_ms = int((now - last_emit_ts) * 1000)
        wait_interval_ms = max(0, min_delay_ms - max(0, elapsed_ms))

    wait_burst_ms = 0
    burst_count = int(st.get("burst_chunks_in_window", 0) or 0)
    burst_start_ts = float(st.get("burst_window_start_ts", 0.0) or 0.0)
    if burst_count >= burst_max_chunks and burst_start_ts > 0.0:
        elapsed_window_ms = int((now - burst_start_ts) * 1000)
        wait_burst_ms = max(0, burst_window_ms - max(0, elapsed_window_ms))

    return max(wait_interval_ms, wait_burst_ms)


_READER_BOOK_CMD_RE = re.compile(
    r"\b(?:leer|leeme|abrir|abri|abrime)\s+(?:el\s+)?(?:libro\s+)?(?:numero\s+|nro\.?\s+|n°\s+)?(\d+)\b",
    flags=re.IGNORECASE,
)


def _extract_reader_book_index(message: str) -> int | None:
    normalized = _normalize_text(message)
    if not normalized:
        return None
    m = _READER_BOOK_CMD_RE.search(normalized)
    if not m:
        return None
    try:
        idx = int(str(m.group(1) or "").strip())
    except Exception:
        return None
    if idx <= 0:
        return None
    return idx


def _is_reader_control_command(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    if re.search(
        r"\b(?:continuar|continua|contiuna|contionua|segui|seguir|sigue|continue|resume|reanuda(?:r)?)\s+"
        r"(?:la\s+lectura\s+)?desde\b",
        normalized,
        flags=re.IGNORECASE,
    ):
        return True
    if any(
        k in normalized
        for k in (
            "ayuda lectura",
            "help lectura",
            "biblioteca",
            "estado lectura",
            "donde voy",
            "status lectura",
            "repetir",
            "repeti",
            "segui",
            "seguir",
            "seguir leyendo",
            "sigas leyendo",
            "siguiente",
            "next",
            "continuar",
            "continuar desde",
            "ir al parrafo",
            "ir al párrafo",
            "ir al bloque",
            "volver una frase",
            "volver un parrafo",
            "volver un párrafo",
            "continuo on",
            "continuo off",
            "modo manual on",
            "modo manual off",
            "manual on",
            "manual off",
            "detenete",
            "detente",
            "pausa lectura",
            "pausar la lectura",
            "pausar lectura",
            "detener lectura",
            "parar lectura",
            "pares la lectura",
            "stop lectura",
        )
    ):
        return True
    return _extract_reader_book_index(normalized) is not None


def _reader_chunk_reply(chunk: dict, total_chunks: int, title: str = "", prefix: str = "") -> str:
    chunk_index = int(chunk.get("chunk_index", 0) or 0)
    index = max(1, chunk_index + 1)
    total = max(int(total_chunks or 0), index)
    text = str(chunk.get("text", "")).strip()
    header = f"Bloque {index}/{total}"
    if title:
        header = f"{title} - {header}"
    parts: list[str] = []
    if prefix:
        parts.append(str(prefix).strip())
    parts.append(header)
    parts.append("")
    parts.append(text or "[bloque sin texto]")
    return "\n".join(parts)


def _reader_meta(
    session_id: str,
    state: dict | None,
    chunk: dict | None = None,
    auto_continue: bool = False,
    tts_stream_id: int = 0,
    tts_gate_required: bool = False,
) -> dict:
    st = state if isinstance(state, dict) else {}
    pacing_cfg = _reader_pacing_config()
    next_auto_after_ms = _reader_pacing_wait_ms(st, cfg=pacing_cfg) if auto_continue else 0
    chunk_text_len = 0
    if isinstance(chunk, dict):
        chunk_text_len = len(str(chunk.get("text", "")))
    out = {
        "session_id": _safe_session_id(session_id),
        "cursor": int(st.get("cursor", 0) or 0),
        "total_chunks": int(st.get("total_chunks", 0) or 0),
        "done": bool(st.get("done", False)),
        "has_pending": bool(st.get("has_pending", False)),
        "continuous_active": bool(st.get("continuous_active", False)),
        "continuous_enabled": bool(st.get("continuous_enabled", st.get("continuous_active", False))),
        "manual_mode": bool(st.get("manual_mode", False)),
        "continuous_reason": str(st.get("continuous_reason", "")),
        "reader_state": str(st.get("reader_state", "paused") or "paused"),
        "auto_continue": bool(auto_continue),
        "pacing_min_delay_ms": int(pacing_cfg.get("min_delay_ms", 1500) or 1500),
        "pacing_burst_window_ms": int(pacing_cfg.get("burst_window_ms", 10000) or 10000),
        "pacing_burst_max_chunks": int(pacing_cfg.get("burst_max_chunks", 6) or 6),
        "next_auto_after_ms": int(max(0, next_auto_after_ms)),
        "tts_gate_required": bool(tts_gate_required),
        "tts_wait_stream_id": int(tts_stream_id) if tts_gate_required and int(tts_stream_id) > 0 else 0,
        "tts_wait_timeout_ms": _reader_tts_wait_timeout_ms(chunk_text_len) if tts_gate_required else 0,
    }
    if isinstance(chunk, dict):
        out["chunk_index"] = int(chunk.get("chunk_index", 0) or 0)
        out["chunk_id"] = str(chunk.get("chunk_id", ""))
        out["offset_chars"] = int(chunk.get("offset_chars", 0) or 0)
        out["chunk_text"] = str(chunk.get("text", ""))
        out["chunk_total_chars"] = len(str(chunk.get("text", "")))
    if isinstance(st.get("bookmark"), dict):
        out["bookmark"] = {
            "chunk_index": int(st["bookmark"].get("chunk_index", 0) or 0),
            "chunk_id": str(st["bookmark"].get("chunk_id", "")),
            "offset_chars": int(st["bookmark"].get("offset_chars", 0) or 0),
            "quality": str(st["bookmark"].get("quality", "unknown") or "unknown"),
            "last_snippet": str(st["bookmark"].get("last_snippet", "")),
        }
    return out


def _reader_active_chunk_snapshot(session_id: str) -> dict:
    st_full = _READER_STORE.get_session(session_id, include_chunks=True)
    if not st_full.get("ok"):
        return {"ok": False, "error": "reader_session_not_found"}
    chunks = st_full.get("chunks")
    if not isinstance(chunks, list):
        chunks = []
    pending = st_full.get("pending") if isinstance(st_full.get("pending"), dict) else None
    cursor = max(0, int(st_full.get("cursor", 0) or 0))
    idx = -1
    text = ""
    if isinstance(pending, dict):
        idx = int(pending.get("chunk_index", -1) or -1)
        if 0 <= idx < len(chunks):
            raw = chunks[idx] if isinstance(chunks[idx], dict) else {}
            text = str(raw.get("text", "")).strip()
        if not text:
            text = str(pending.get("text", "")).strip()
    if not text and chunks:
        idx = min(max(0, cursor - 1), len(chunks) - 1)
        raw = chunks[idx] if isinstance(chunks[idx], dict) else {}
        text = str(raw.get("text", "")).strip()
    if not text:
        return {"ok": False, "error": "reader_no_chunk_for_comment"}
    total_chunks = int(st_full.get("total_chunks", len(chunks)) or len(chunks) or 0)
    if idx < 0:
        idx = max(0, min(len(chunks) - 1, cursor - 1)) if chunks else 0
    meta = st_full.get("metadata", {}) if isinstance(st_full.get("metadata"), dict) else {}
    title = str(meta.get("title", "")).strip()
    return {
        "ok": True,
        "chunk_index": int(idx),
        "total_chunks": max(1, int(total_chunks or 1)),
        "text": text,
        "title": title,
    }


def _reader_block_summary(text: str, max_chars: int = 520) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    parts = [seg.strip() for seg in re.split(r"(?<=[.!?])\s+", clean) if seg.strip()]
    picked: list[str] = []
    used = 0
    for seg in parts:
        if picked and len(seg) < 18:
            continue
        picked.append(seg)
        used += len(seg) + 1
        if len(picked) >= 2 or used >= max_chars:
            break
    if not picked:
        picked = [clean]
    out = " ".join(picked).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rstrip(" ,;:") + "..."
    return out


def _reader_voice_unavailable_detail() -> str:
    health = _alltalk_health_cached(force=False)
    if not bool(health.get("ok", False)):
        return _voice_diagnostics(str(health.get("detail", "health_failed")))
    last = str((_VOICE_LAST_STATUS or {}).get("detail", "")).strip()
    if last and last not in ("not_started", "queued"):
        return _voice_diagnostics(f"tts_start_failed:{last}")
    return _voice_diagnostics("tts_start_failed:stream_not_created")


def _reader_emit_chunk(
    session_id: str,
    chunk: dict,
    allowed_tools: set[str],
    commit_reason: str,
) -> tuple[bool, int, bool, str]:
    chunk_text = str(chunk.get("text", "")).strip()
    chunk_id = str(chunk.get("chunk_id", "")).strip()
    chunk_index = int(chunk.get("chunk_index", 0) or 0)
    start_offset = int(chunk.get("offset_chars", 0) or 0)
    tts_gate_required = ("tts" in allowed_tools) and _voice_enabled() and bool(chunk_text)
    tts_stream_id = 0
    committed = False
    tts_unavailable_detail = ""
    if tts_gate_required:
        tts_stream_id = int(_speak_reply_async(chunk_text) or 0)
        if tts_stream_id > 0:
            _reader_autocommit_register(
                stream_id=tts_stream_id,
                session_id=session_id,
                chunk_id=chunk_id,
                chunk_index=chunk_index,
                text_len=len(chunk_text),
                start_offset_chars=start_offset,
            )
        else:
            tts_gate_required = False
            tts_unavailable_detail = _reader_voice_unavailable_detail()
            _READER_STORE.set_continuous(session_id, False, reason="reader_voice_unavailable")
            _READER_STORE.set_reader_state(session_id, "paused", reason="reader_voice_unavailable")
    if not tts_gate_required:
        _READER_STORE.commit(
            session_id,
            chunk_id=chunk_id,
            chunk_index=chunk_index,
            reason=commit_reason,
        )
        committed = True
    return tts_gate_required, tts_stream_id, committed, tts_unavailable_detail


def _reader_force_commit_pending_if_stalled(session_id: str, state: dict | None) -> tuple[bool, dict]:
    st = state if isinstance(state, dict) else _READER_STORE.get_session(session_id, include_chunks=False)
    if not st.get("ok"):
        return False, st
    pending = st.get("pending") if isinstance(st.get("pending"), dict) else None
    if not isinstance(pending, dict):
        return False, st
    # Preserve mid-chunk resume semantics (barge-in/bookmark).
    if int(pending.get("offset_chars", 0) or 0) > 0:
        return False, st
    now = time.time()
    last_delivery_ts = float(pending.get("last_delivery_ts", 0.0) or 0.0)
    pending_text_len = len(str(pending.get("text", "")))
    max_wait = _reader_tts_end_max_wait_sec(text_len=pending_text_len)
    age = max(0.0, now - last_delivery_ts) if last_delivery_ts > 0.0 else 0.0
    detail = str((_VOICE_LAST_STATUS or {}).get("detail", "")).strip().lower()
    detail_is_failure = bool(detail) and any(
        k in detail for k in ("timeout", "tts_", "alltalk_", "health_", "player_", "fallback_failed")
    )
    if _is_user_tts_interrupt_detail(detail):
        return False, st
    should_force = False
    if age >= max_wait:
        should_force = True
    elif (not _tts_is_playing()) and detail_is_failure:
        should_force = True
    if not should_force:
        return False, st
    committed = _READER_STORE.commit(
        session_id,
        chunk_id=str(pending.get("chunk_id", "")),
        chunk_index=int(pending.get("chunk_index", 0) or 0),
        reason="tts_end_timeout_force_continue",
    )
    return bool(committed.get("ok", False) and committed.get("committed", False)), _READER_STORE.get_session(
        session_id, include_chunks=False
    )


def _maybe_handle_local_action(message: str, allowed_tools: set[str], session_id: str) -> dict | None:
    text = message.lower()
    normalized = _normalize_text(message)
    shadow_explicit = any(k in normalized for k in ("shadow", "experimental", "modo shadow"))

    if (
        ("cliente" in normalized and "diego" in normalized and any(k in normalized for k in ("fij", "usar", "set")))
        or ("este cliente es diego" in normalized)
    ):
        active = _xdotool_active_window()
        if not active:
            return {"reply": "No pude detectar la ventana activa. Activá DC en Chrome y repetí."}
        title = str(_wmctrl_list().get(active, ""))
        t = title.lower()
        if "molbot direct chat" not in t or ("chrome" not in t and "google" not in t):
            return {"reply": "La ventana activa no es Molbot Direct Chat en Chrome. Activala y repetí."}
        desk = _wmctrl_window_desktop(active)
        if desk is None:
            return {"reply": "No pude detectar el workspace de la ventana activa."}
        _save_trusted_dc_anchor(active, desk, title)
        return {"reply": f"Listo. Fijé este cliente como diego (anchor={active})."}

    if "tts" in allowed_tools:
        if any(k in normalized for k in ("voz off", "silenciar voz", "mute voz", "apaga la voz", "desactiva voz")):
            _set_voice_enabled(False, session_id=session_id)
            return {"reply": "Listo: desactivé la voz."}
        if any(k in normalized for k in ("voz on", "activa voz", "encende voz", "enciende voz")):
            _set_voice_enabled(True, session_id=session_id)
            return {"reply": "Listo: activé la voz."}
        if any(k in normalized for k in ("voz test", "proba voz", "probar voz", "test de voz")):
            _set_voice_enabled(True, session_id=session_id)
            _speak_reply_async("Prueba de voz activada. Sistema listo.")
            return {"reply": "Ejecuté prueba de voz."}

    if any(k in normalized for k in ("mic lista", "microfono lista", "microfono listar", "mic list", "listar microfonos")):
        devices = _stt_list_input_devices()
        state = _load_voice_state()
        current = str(state.get("stt_device", "")).strip()
        if not devices:
            return {"reply": "No pude listar micrófonos de entrada (sounddevice sin dispositivos).", "no_auto_tts": True}
        lines = []
        for d in devices[:24]:
            if not isinstance(d, dict):
                continue
            idx = int(d.get("index", -1))
            name = str(d.get("name", "")).strip() or "sin_nombre"
            max_in = int(d.get("max_input_channels", 0) or 0)
            is_default = bool(d.get("default", False))
            marker = ""
            if current and current == str(idx):
                marker = " [activo]"
            elif (not current) and is_default:
                marker = " [default]"
            lines.append(f"- {idx}: {name} (in={max_in}){marker}")
        return {
            "reply": "Micrófonos de entrada:\n" + "\n".join(lines) + "\nUsá: mic usar <indice> | mic usar default",
            "no_auto_tts": True,
        }

    match_mic_use = re.search(r"\bmic(?:rofono)?\s+usar\s+([^\s]+)", normalized)
    if match_mic_use:
        token = str(match_mic_use.group(1) or "").strip().lower()
        if token in ("default", "defecto", "por_defecto", "por-defecto"):
            _set_stt_runtime_config(stt_device="")
            return {"reply": "Listo: micrófono STT en modo default.", "no_auto_tts": True}
        if not re.fullmatch(r"-?\d+", token):
            return {"reply": "Formato inválido. Usá: mic usar <indice> o mic usar default.", "no_auto_tts": True}
        devices = _stt_list_input_devices()
        idx = int(token)
        exists = any(isinstance(d, dict) and int(d.get("index", -1)) == idx for d in devices)
        if (not exists) and devices:
            return {"reply": f"No existe el micrófono {idx}. Probá primero 'mic lista'.", "no_auto_tts": True}
        _set_stt_runtime_config(stt_device=str(idx))
        return {"reply": f"Listo: STT usará micrófono {idx}.", "no_auto_tts": True}

    match_stt_threshold_segment = re.search(
        r"\bstt\s+umbral\s+(?:segment|segmento|segmentacion)\s+([0-9]+(?:\.[0-9]+)?)",
        normalized,
    )
    if match_stt_threshold_segment:
        try:
            thr = max(0.0005, float(match_stt_threshold_segment.group(1)))
        except Exception:
            thr = 0.002
        _set_stt_runtime_config(stt_segment_rms_threshold=thr)
        return {"reply": f"Listo: umbral STT de segmentación en {thr:.4f}.", "no_auto_tts": True}

    match_stt_threshold_barge = re.search(
        r"\bstt\s+umbral\s+(?:barge|barge-any|bargeany|bargein)\s+([0-9]+(?:\.[0-9]+)?)",
        normalized,
    )
    if match_stt_threshold_barge:
        try:
            thr = max(0.001, float(match_stt_threshold_barge.group(1)))
        except Exception:
            thr = 0.012
        _set_stt_runtime_config(stt_barge_rms_threshold=thr)
        return {"reply": f"Listo: umbral STT de barge en {thr:.4f}.", "no_auto_tts": True}

    match_stt_threshold = re.search(r"\bstt\s+umbral\s+([0-9]+(?:\.[0-9]+)?)", normalized)
    if match_stt_threshold:
        try:
            thr = max(0.001, float(match_stt_threshold.group(1)))
        except Exception:
            thr = 0.012
        _set_stt_runtime_config(stt_rms_threshold=thr)
        return {"reply": f"Listo: umbral STT unificado en {thr:.4f} (segmentación + barge).", "no_auto_tts": True}

    match_stt_gain = re.search(r"\bstt\s+(?:ganancia|gain)\s+([0-9]+(?:\.[0-9]+)?)", normalized)
    if match_stt_gain:
        try:
            gain = max(0.05, float(match_stt_gain.group(1)))
        except Exception:
            gain = 1.0
        _set_stt_runtime_config(stt_preamp_gain=gain)
        return {"reply": f"Listo: ganancia STT en {gain:.2f}.", "no_auto_tts": True}

    if any(k in normalized for k in ("stt agc on", "agc stt on", "stt auto ganancia on")):
        _set_stt_runtime_config(stt_agc_enabled=True)
        return {"reply": "Listo: STT AGC activado.", "no_auto_tts": True}
    if any(k in normalized for k in ("stt agc off", "agc stt off", "stt auto ganancia off")):
        _set_stt_runtime_config(stt_agc_enabled=False)
        return {"reply": "Listo: STT AGC desactivado.", "no_auto_tts": True}

    match_stt_agc_target = re.search(r"\bstt\s+agc\s+(?:target|objetivo)\s+([0-9]+(?:\.[0-9]+)?)", normalized)
    if match_stt_agc_target:
        try:
            target = max(0.01, min(0.30, float(match_stt_agc_target.group(1))))
        except Exception:
            target = 0.06
        _set_stt_runtime_config(stt_agc_target_rms=target)
        return {"reply": f"Listo: objetivo AGC STT en {target:.3f}.", "no_auto_tts": True}

    if any(
        k in normalized
        for k in (
            "stt barge any on",
            "stt barge-any on",
            "stt bargein any on",
            "barge any on",
        )
    ):
        _set_stt_runtime_config(stt_barge_any=True)
        return {"reply": "Listo: STT barge-any activado (pausa por cualquier voz durante TTS).", "no_auto_tts": True}

    if any(
        k in normalized
        for k in (
            "stt barge any off",
            "stt barge-any off",
            "stt bargein any off",
            "barge any off",
        )
    ):
        _set_stt_runtime_config(stt_barge_any=False)
        return {"reply": "Listo: STT barge-any desactivado (solo comandos de voz).", "no_auto_tts": True}

    if any(k in normalized for k in ("stt chat on", "chat stt on", "voice chat on", "voz chat on")):
        _set_stt_runtime_config(stt_chat_enabled=True)
        return {
            "reply": "Listo: STT chat activado (fuera de Reader/TTS, la voz entra como mensaje al chat).",
            "no_auto_tts": True,
        }

    if any(k in normalized for k in ("stt chat off", "chat stt off", "voice chat off", "voz chat off")):
        _set_stt_runtime_config(stt_chat_enabled=False)
        return {"reply": "Listo: STT chat desactivado (solo comandos por voz).", "no_auto_tts": True}

    if any(k in normalized for k in ("stt debug on", "debug stt on", "stt depuracion on")):
        _set_stt_runtime_config(stt_debug=True)
        return {"reply": "STT debug activado.", "no_auto_tts": True}
    if any(k in normalized for k in ("stt debug off", "debug stt off", "stt depuracion off")):
        _set_stt_runtime_config(stt_debug=False)
        return {"reply": "STT debug desactivado.", "no_auto_tts": True}

    if any(k in normalized for k in ("mic nivel", "stt nivel", "nivel stt", "stt diag", "diagnostico stt")):
        st = _STT_MANAGER.status()
        no_audio = bool(st.get("stt_no_audio_input", False))
        no_speech = bool(st.get("stt_no_speech_detected", False))
        vad_ratio = float(st.get("stt_vad_true_ratio", 0.0) or 0.0) * 100.0
        return {
            "reply": (
                f"STT diag: running={bool(st.get('stt_running', False))}, owner={st.get('stt_owner_session_id', '') or '-'}, "
                f"frames={int(st.get('stt_frames_seen', 0) or 0)}, rms={float(st.get('stt_rms_current', 0.0) or 0.0):.4f}, "
                f"vad={bool(st.get('stt_vad_active', False))}, vad_true={vad_ratio:.1f}%, "
                f"seg_ms={int(st.get('stt_last_segment_ms', 0) or 0)}, silence_ms={int(st.get('stt_silence_ms', 0) or 0)}, "
                f"dropped_audio={int(st.get('items_dropped_audio', 0) or 0)}, "
                f"dropped_text={int(st.get('items_dropped_text', 0) or 0)}, last_drop={str(st.get('stt_drop_reason', '') or '-')}, "
                f"raw='{str(st.get('last_raw_text', '') or '-')[:48]}', norm='{str(st.get('last_norm_text', '') or '-')[:48]}', "
                f"cmd={str(st.get('matched_cmd', '') or '-')}, reason={str(st.get('match_reason', '') or '-')}, "
                f"chat={bool(st.get('stt_chat_enabled', False))}, "
                f"barge_any={bool(st.get('stt_barge_any', False))}, "
                f"thr_seg={float(st.get('stt_segment_rms_threshold', 0.0) or 0.0):.4f}, "
                f"thr_eff={float(st.get('stt_effective_seg_thr', st.get('stt_segment_rms_threshold', 0.0)) or 0.0):.4f}, "
                f"thr_off={float(st.get('stt_effective_seg_thr_off', 0.0) or 0.0):.4f}, "
                f"thr_barge={float(st.get('stt_barge_rms_threshold', 0.0) or 0.0):.4f}, "
                f"gain={float(st.get('stt_preamp_gain', 1.0) or 1.0):.2f}, "
                f"agc={bool(st.get('stt_agc_enabled', False))}, "
                f"agc_target={float(st.get('stt_agc_target_rms', 0.06) or 0.06):.3f}, "
                f"min_seg={int(st.get('stt_effective_min_segment_ms', 0) or 0)}, "
                f"speech_state=in:{bool(st.get('stt_in_speech', False))}|hang:{int(st.get('stt_speech_hangover_ms', 0) or 0)}ms, "
                f"emit={int(st.get('stt_emit_count', 0) or 0)}, "
                f"voice_text={int(st.get('stt_chat_commit_total', st.get('voice_text_committed', 0)) or 0)}, "
                f"drops={int(st.get('items_dropped', 0) or 0)}, "
                f"no_audio={no_audio}, no_speech={no_speech}."
            ),
            "no_auto_tts": True,
        }

    # Reader UX v0.3: local commands in DC chat, no model round-trip needed.
    if any(k in normalized for k in ("ayuda lectura", "help lectura")):
        return {
            "reply": (
                "Comandos de lectura:\n"
                "- biblioteca\n"
                "- biblioteca rescan\n"
                "- leer libro <n>\n"
                "- segui\n"
                "- continuar\n"
                "- continuar desde \"<frase>\"\n"
                "- ir al párrafo <n>\n"
                "- volver una frase | volver un párrafo\n"
                "- modo manual on|off\n"
                "- continuo on|off (alias)\n"
                "- repetir\n"
                "- estado lectura\n"
                "- pausa lectura | detenete"
            ),
            "no_auto_tts": True,
        }

    if any(k in normalized for k in ("biblioteca rescan", "actualizar biblioteca", "rescan biblioteca")):
        out = _READER_LIBRARY.rescan()
        return {
            "reply": (
                f"Biblioteca actualizada. Libros: {int(out.get('count', 0))}. "
                f"Archivos escaneados: {int(out.get('scanned_files', 0))}. "
                f"Errores: {int(out.get('errors', 0))}."
            ),
            "no_auto_tts": True,
        }

    if any(k in normalized for k in ("biblioteca", "mis libros", "lista de libros", "libros")):
        out = _READER_LIBRARY.list_books()
        books = out.get("books", []) if isinstance(out, dict) else []
        if not isinstance(books, list) or not books:
            return {
                "reply": "No encontré libros indexados. Decí: biblioteca rescan",
                "no_auto_tts": True,
            }
        lines = []
        for idx, item in enumerate(books[:12], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "sin_titulo")).strip() or "sin_titulo"
            fmt = str(item.get("format", "unknown")).strip() or "unknown"
            short_id = str(item.get("book_id", ""))[:8]
            lines.append(f"{idx}) {title} ({fmt}) [{short_id}]")
        total = len(books)
        body = "\n".join(lines)
        more = f"\n... y {total - 12} más." if total > 12 else ""
        return {
            "reply": f"Biblioteca ({total}):\n{body}{more}\nDecí: leer libro <n>",
            "no_auto_tts": True,
        }

    m_manual = re.search(r"\b(?:modo\s+manual|manual)\s+(on|off)\b", normalized, flags=re.IGNORECASE)
    if m_manual:
        st = _READER_STORE.get_session(session_id, include_chunks=False)
        if not st.get("ok"):
            return {"reply": "No hay sesión de lectura activa en este chat.", "no_auto_tts": True}
        mode = str(m_manual.group(1) or "").strip().lower()
        manual_on = mode == "on"
        _READER_STORE.set_manual_mode(session_id, manual_on, reason="reader_manual_mode_command")
        if manual_on:
            _READER_STORE.set_continuous(session_id, False, reason="reader_manual_mode_on")
        else:
            _READER_STORE.set_continuous(session_id, True, reason="reader_manual_mode_off_autopilot")
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        if manual_on:
            return {
                "reply": "Modo manual activado. Avanza de a un bloque con 'seguí'.",
                "no_auto_tts": True,
                "reader": _reader_meta(session_id, st_after, auto_continue=False),
            }
        return {
            "reply": "Modo manual desactivado. Vuelve el autopiloto de lectura.",
            "no_auto_tts": True,
            "reader": _reader_meta(session_id, st_after, auto_continue=has_more),
        }

    m_cont = re.search(r"\bcontinuo\s+(on|off)\b", normalized, flags=re.IGNORECASE)
    if m_cont:
        st = _READER_STORE.get_session(session_id, include_chunks=False)
        if not st.get("ok"):
            return {"reply": "No hay sesión de lectura activa en este chat.", "no_auto_tts": True}
        mode = str(m_cont.group(1) or "").strip().lower()
        enable = mode == "on"
        reason = "reader_continuous_opt_in" if enable else "reader_continuous_opt_out"
        _READER_STORE.set_manual_mode(session_id, not enable, reason="reader_continuous_alias")
        _READER_STORE.set_continuous(session_id, enable, reason=reason)
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        if enable:
            return {
                "reply": "Lectura continua activada. Va a avanzar sola con pacing hasta que la pauses.",
                "no_auto_tts": True,
                "reader": _reader_meta(session_id, st_after, auto_continue=has_more),
            }
        return {
            "reply": "Lectura continua desactivada. Quedó en modo manual (usá 'seguí').",
            "no_auto_tts": True,
            "reader": _reader_meta(session_id, st_after, auto_continue=False),
        }

    if any(
        k in normalized
        for k in (
            "de que habla este bloque",
            "de que habla el bloque",
            "de que trata este bloque",
            "de que trata el bloque",
            "que dice este bloque",
            "que dice el bloque",
            "resumime este bloque",
            "resumi este bloque",
            "comentame este bloque",
            "explicame este bloque",
            "que leiste en este bloque",
            "que leiste",
        )
    ):
        snap = _reader_active_chunk_snapshot(session_id)
        if not snap.get("ok"):
            return {
                "reply": "No tengo un bloque de lectura activo para comentar. Decí: leer libro <n>.",
                "no_auto_tts": True,
            }
        _READER_STORE.set_continuous(session_id, False, reason="reader_comment_query")
        _READER_STORE.set_reader_state(session_id, "commenting", reason="reader_comment_query")
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        summary = _reader_block_summary(str(snap.get("text", "")))
        block_idx = max(1, int(snap.get("chunk_index", 0) or 0) + 1)
        total = max(block_idx, int(snap.get("total_chunks", block_idx) or block_idx))
        title = str(snap.get("title", "")).strip()
        header = f"Bloque {block_idx}/{total}"
        if title:
            header = f"{title} - {header}"
        reply = f"{header}: {summary}" if summary else f"{header}: [sin texto legible]"
        return {
            "reply": reply,
            "no_auto_tts": True,
            "reader": _reader_meta(session_id, st_after, auto_continue=False),
        }

    read_idx = _extract_reader_book_index(normalized)
    if read_idx is not None:
        out = _READER_LIBRARY.list_books()
        books = out.get("books", []) if isinstance(out, dict) else []
        idx = int(read_idx)
        if (not isinstance(books, list)) or idx < 1 or idx > len(books):
            limit = len(books) if isinstance(books, list) else 0
            return {"reply": f"Índice de libro inválido. Rango disponible: 1..{limit}.", "no_auto_tts": True}
        item = books[idx - 1] if isinstance(books[idx - 1], dict) else {}
        book_id = str(item.get("book_id", "")).strip()
        if not book_id:
            return {"reply": "No pude resolver ese libro. Decí: biblioteca", "no_auto_tts": True}
        loaded = _READER_LIBRARY.get_book_text(book_id)
        if not loaded.get("ok"):
            return {"reply": f"No pude abrir el libro ({loaded.get('error', 'reader_book_error')}).", "no_auto_tts": True}
        book_meta = loaded.get("book", {})
        title = str(book_meta.get("title", item.get("title", "libro"))).strip() if isinstance(book_meta, dict) else "libro"
        explicit_manual = bool(re.search(r"\bmanual\b", normalized, flags=re.IGNORECASE))
        voice_state_now = _load_voice_state()
        reader_mode_live = bool(
            _normalize_voice_owner(voice_state_now.get("voice_owner", "chat")) == "reader"
            and bool(voice_state_now.get("reader_mode_active", False))
        )
        st_before = _READER_STORE.get_session(session_id, include_chunks=False)
        if st_before.get("ok"):
            meta_before = st_before.get("metadata", {}) if isinstance(st_before.get("metadata"), dict) else {}
            same_book = str(meta_before.get("book_id", "")).strip() == book_id
            state_before = str(st_before.get("reader_state", "")).strip().lower()
            # Guardrail: only resume same-book cursor when reader mode ownership is live.
            # If reader mode is OFF, "leer libro N" should be a fresh start from bloque 1.
            if same_book and reader_mode_live and state_before in ("reading", "paused", "commenting"):
                if explicit_manual != bool(st_before.get("manual_mode", False)):
                    _READER_STORE.set_manual_mode(session_id, explicit_manual, reason="reader_start_same_book_mode_toggle")
                    _READER_STORE.set_continuous(
                        session_id,
                        not explicit_manual,
                        reason="reader_start_same_book_manual_explicit" if explicit_manual else "reader_start_same_book_autopilot",
                    )
                    st_before = _READER_STORE.get_session(session_id, include_chunks=False)
                if state_before in ("paused", "commenting"):
                    manual_mode = bool(st_before.get("manual_mode", False))
                    _READER_STORE.set_continuous(
                        session_id,
                        not manual_mode,
                        reason="reader_start_same_book_resume_autopilot" if (not manual_mode) else "reader_start_same_book_resume_manual",
                    )
                    _READER_STORE.set_reader_state(session_id, "reading", reason="reader_start_same_book_resume")
                    out_resume = _READER_STORE.next_chunk(session_id)
                    chunk_resume = out_resume.get("chunk") if isinstance(out_resume, dict) else None
                    if out_resume.get("ok") and isinstance(chunk_resume, dict):
                        tts_gate_required, tts_stream_id, _committed, tts_unavailable_detail = _reader_emit_chunk(
                            session_id=session_id,
                            chunk=chunk_resume,
                            allowed_tools=allowed_tools,
                            commit_reason="reader_start_same_book_resume_autocommit",
                        )
                        st_resume = _READER_STORE.get_session(session_id, include_chunks=False)
                        has_more_resume = (not bool(st_resume.get("done", False))) and int(st_resume.get("cursor", 0) or 0) < int(
                            st_resume.get("total_chunks", 0) or 0
                        )
                        reply_resume = _reader_chunk_reply(
                            chunk_resume,
                            total_chunks=int(st_resume.get("total_chunks", 0) or 0),
                            title=title,
                            prefix="Retomo lectura del libro activo.",
                        )
                        if tts_unavailable_detail:
                            reply_resume = (
                                f"Retomo lectura, pero voz no disponible ({tts_unavailable_detail}). "
                                "Queda en manual estable.\n\n" + reply_resume
                            )
                        return {
                            "reply": reply_resume,
                            "no_auto_tts": True,
                            "reader": _reader_meta(
                                session_id,
                                st_resume,
                                chunk=chunk_resume,
                                auto_continue=bool(st_resume.get("continuous_enabled", False)) and has_more_resume,
                                tts_stream_id=tts_stream_id,
                                tts_gate_required=tts_gate_required,
                            ),
                        }
                has_more = (not bool(st_before.get("done", False))) and int(st_before.get("cursor", 0) or 0) < int(
                    st_before.get("total_chunks", 0) or 0
                )
                return {
                    "reply": (
                        f"Ya estoy leyendo '{title}'."
                        + (" Modo manual activo." if bool(st_before.get("manual_mode", False)) else " Autopiloto activo.")
                    ),
                    "no_auto_tts": True,
                    "reader": _reader_meta(session_id, st_before, auto_continue=bool(st_before.get("continuous_enabled", False)) and has_more),
                }
        started = _READER_STORE.start_session(
            session_id,
            chunks=[],
            text=str(loaded.get("text", "")),
            reset=True,
            metadata=book_meta if isinstance(book_meta, dict) else None,
        )
        if not started.get("ok"):
            return {"reply": f"No pude iniciar lectura ({started.get('error', 'reader_start_failed')}).", "no_auto_tts": True}
        _READER_STORE.set_manual_mode(session_id, explicit_manual, reason="reader_start_mode")
        _READER_STORE.set_continuous(
            session_id,
            not explicit_manual,
            reason="reader_start_manual_explicit" if explicit_manual else "reader_start_autopilot_default",
        )
        first = _READER_STORE.next_chunk(session_id)
        chunk = first.get("chunk") if isinstance(first, dict) else None
        if not first.get("ok") or not isinstance(chunk, dict):
            _READER_STORE.set_continuous(session_id, False, reason="reader_start_empty")
            return {
                "reply": f"Listo: abrí '{title}', pero no encontré contenido para leer.",
                "no_auto_tts": True,
                "reader": _reader_meta(session_id, _READER_STORE.get_session(session_id), auto_continue=False),
            }
        tts_gate_required, tts_stream_id, _committed, tts_unavailable_detail = _reader_emit_chunk(
            session_id=session_id,
            chunk=chunk,
            allowed_tools=allowed_tools,
            commit_reason="reader_start_autocommit",
        )
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        auto_continue = bool(st_after.get("continuous_enabled", False)) and has_more
        start_prefix = (
            f"Lectura iniciada de '{title}' (modo manual)."
            if explicit_manual
            else f"Lectura iniciada de '{title}' (autopiloto ON)."
        )
        if tts_unavailable_detail:
            start_prefix += f" Voz no disponible ({tts_unavailable_detail}). Queda en manual estable."
        return {
            "reply": _reader_chunk_reply(
                chunk,
                total_chunks=int(st_after.get("total_chunks", 0) or 0),
                title=title,
                prefix=start_prefix,
            ),
            "no_auto_tts": True,
            "reader": _reader_meta(
                session_id,
                st_after,
                chunk=chunk,
                auto_continue=auto_continue,
                tts_stream_id=tts_stream_id,
                tts_gate_required=tts_gate_required,
            ),
        }

    if any(
        k in normalized
        for k in (
            "detenete",
            "detente",
            "pausa lectura",
            "pausar la lectura",
            "pausar lectura",
            "detener lectura",
            "parar lectura",
            "pares la lectura",
            "stop lectura",
        )
    ):
        is_hard_stop = any(k in normalized for k in ("detenete", "detente", "stop lectura", "detener lectura"))
        st = _READER_STORE.get_session(session_id, include_chunks=False)
        had_reader_session = bool(st.get("ok"))
        interrupted = _apply_voice_pause_interrupt(session_id, source="typed", keyword="detenete")
        if (not had_reader_session) and (not interrupted):
            return {"reply": "No hay sesión de lectura activa en este chat.", "no_auto_tts": True}
        if not had_reader_session:
            return {"reply": ("detenida" if is_hard_stop else "si como seguimos?"), "no_auto_tts": True}
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        return {
            "reply": ("detenida" if is_hard_stop else "si como seguimos?"),
            "no_auto_tts": True,
            "reader": _reader_meta(session_id, st_after, auto_continue=False),
        }

    continue_phrase_alias = r"(?:continuar|continua|contiuna|contionua|segui|seguir|sigue|continue|resume|reanuda(?:r)?)"
    continue_from_patterns = (
        rf"\b(?:ok\s+)?{continue_phrase_alias}\s+(?:la\s+lectura\s+)?desde\s+(?:la\s+)?frase\s+[\"“”'](.+?)[\"“”']\s*$",
        rf"\b(?:ok\s+)?{continue_phrase_alias}\s+(?:la\s+lectura\s+)?desde\s+[\"“”'](.+?)[\"“”']\s*$",
        rf"\b(?:ok\s+)?{continue_phrase_alias}\s+(?:la\s+lectura\s+)?desde\s+(?:la\s+)?frase\s+(.+)$",
        rf"\b(?:ok\s+)?{continue_phrase_alias}\s+(?:la\s+lectura\s+)?desde\s+(.+)$",
    )
    continue_from_phrase = ""
    for src in (message, normalized):
        text_src = str(src or "").strip()
        if not text_src:
            continue
        for pat in continue_from_patterns:
            m_continue_from = re.search(pat, text_src, flags=re.IGNORECASE)
            if not m_continue_from:
                continue
            continue_from_phrase = str(m_continue_from.group(1) or "").strip()
            break
        if continue_from_phrase:
            break
    if continue_from_phrase:
        phrase = re.sub(r"^(?:la\s+lectura|lectura|la\s+frase|frase)\s+", "", continue_from_phrase, flags=re.IGNORECASE).strip()
        phrase = phrase.strip(" \"'“”`.,;:!?-")
        if not phrase:
            return {"reply": "Indicá una frase para continuar. Ejemplo: continuar desde \"matriz\".", "no_auto_tts": True}
        st_before = _READER_STORE.get_session(session_id, include_chunks=False)
        if not st_before.get("ok"):
            return {"reply": "No hay sesión de lectura activa. Usá 'biblioteca' y 'leer libro <n>'.", "no_auto_tts": True}
        manual_mode = bool(st_before.get("manual_mode", False))
        _READER_STORE.set_continuous(
            session_id,
            not manual_mode,
            reason="reader_continue_from_phrase_autopilot" if (not manual_mode) else "reader_continue_from_phrase_manual_mode",
        )
        sought = _READER_STORE.seek_phrase(session_id, phrase=phrase)
        if not sought.get("ok"):
            return {
                "reply": f"No encontré esa frase en el punto actual ({sought.get('error', 'reader_phrase_not_found')}).",
                "no_auto_tts": True,
                "reader": _reader_meta(session_id, _READER_STORE.get_session(session_id, include_chunks=False), auto_continue=False),
            }
        _READER_STORE.set_reader_state(session_id, "reading", reason="reader_continue_from_phrase")
        out = _READER_STORE.next_chunk(session_id)
        chunk = out.get("chunk") if isinstance(out, dict) else None
        if not isinstance(chunk, dict):
            st_now = _READER_STORE.get_session(session_id, include_chunks=False)
            return {"reply": "No pude retomar desde esa frase.", "no_auto_tts": True, "reader": _reader_meta(session_id, st_now)}
        tts_gate_required, tts_stream_id, _committed, tts_unavailable_detail = _reader_emit_chunk(
            session_id=session_id,
            chunk=chunk,
            allowed_tools=allowed_tools,
            commit_reason="reader_continue_from_phrase_autocommit",
        )
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        meta_after = st_after.get("metadata", {}) if isinstance(st_after.get("metadata"), dict) else {}
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        auto_continue = bool(st_after.get("continuous_enabled", False)) and has_more
        prefix = f"Retomo desde: \"{phrase}\"."
        if tts_unavailable_detail:
            prefix += f" Voz no disponible ({tts_unavailable_detail}). Queda en manual estable."
        return {
            "reply": _reader_chunk_reply(
                chunk,
                total_chunks=int(st_after.get("total_chunks", 0) or 0),
                title=str(meta_after.get("book_title", "")),
                prefix=prefix,
            ),
            "no_auto_tts": True,
            "reader": _reader_meta(
                session_id,
                st_after,
                chunk=chunk,
                auto_continue=auto_continue,
                tts_stream_id=tts_stream_id,
                tts_gate_required=tts_gate_required,
            ),
        }

    m_jump_paragraph = re.search(
        r"\b(?:ir(?:\s+a)?|anda|andá|salta|saltar|vamos)\s+(?:al\s+)?(?:parrafo|párrafo|bloque)\s+(\d+)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if not m_jump_paragraph:
        m_jump_paragraph = re.search(r"\b(?:parrafo|párrafo|bloque)\s+(\d+)\b", normalized, flags=re.IGNORECASE)
    if m_jump_paragraph:
        try:
            target_paragraph = int(str(m_jump_paragraph.group(1) or "0").strip())
        except Exception:
            target_paragraph = 0
        if target_paragraph <= 0:
            return {"reply": "Indicá un párrafo válido. Ejemplo: ir al párrafo 12.", "no_auto_tts": True}
        st_before = _READER_STORE.get_session(session_id, include_chunks=False)
        if not st_before.get("ok"):
            return {"reply": "No hay sesión de lectura activa. Usá 'biblioteca' y 'leer libro <n>'.", "no_auto_tts": True}
        manual_mode = bool(st_before.get("manual_mode", False))
        _READER_STORE.set_continuous(
            session_id,
            not manual_mode,
            reason="reader_jump_paragraph_autopilot" if (not manual_mode) else "reader_jump_paragraph_manual_mode",
        )
        jumped = _READER_STORE.jump_to_chunk(session_id, target_paragraph)
        if not jumped.get("ok"):
            err = str(jumped.get("error", "")).strip()
            if err == "reader_chunk_out_of_range":
                total = int(jumped.get("total_chunks", 0) or 0)
                return {"reply": f"Párrafo fuera de rango. Disponible: 1..{max(1, total)}.", "no_auto_tts": True}
            return {"reply": f"No pude ir a ese párrafo ({err or 'reader_jump_failed'}).", "no_auto_tts": True}
        chunk = jumped.get("chunk") if isinstance(jumped, dict) else None
        if not isinstance(chunk, dict):
            st_now = _READER_STORE.get_session(session_id, include_chunks=False)
            return {"reply": "No pude preparar ese párrafo para lectura.", "no_auto_tts": True, "reader": _reader_meta(session_id, st_now)}
        tts_gate_required, tts_stream_id, _committed, tts_unavailable_detail = _reader_emit_chunk(
            session_id=session_id,
            chunk=chunk,
            allowed_tools=allowed_tools,
            commit_reason="reader_jump_paragraph_autocommit",
        )
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        meta_after = st_after.get("metadata", {}) if isinstance(st_after.get("metadata"), dict) else {}
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        auto_continue = bool(st_after.get("continuous_enabled", False)) and has_more
        target_idx = int(chunk.get("chunk_index", 0) or 0) + 1
        prefix = f"Salto al párrafo {target_idx}."
        if tts_unavailable_detail:
            prefix += f" Voz no disponible ({tts_unavailable_detail}). Queda en manual estable."
        return {
            "reply": _reader_chunk_reply(
                chunk,
                total_chunks=int(st_after.get("total_chunks", 0) or 0),
                title=str(meta_after.get("book_title", "")),
                prefix=prefix,
            ),
            "no_auto_tts": True,
            "reader": _reader_meta(
                session_id,
                st_after,
                chunk=chunk,
                auto_continue=auto_continue,
                tts_stream_id=tts_stream_id,
                tts_gate_required=tts_gate_required,
            ),
        }

    if any(k in normalized for k in ("volver una frase",)):
        st_before = _READER_STORE.get_session(session_id, include_chunks=False)
        if not st_before.get("ok"):
            return {"reply": "No hay sesión de lectura activa. Usá 'biblioteca' y 'leer libro <n>'.", "no_auto_tts": True}
        manual_mode = bool(st_before.get("manual_mode", False))
        _READER_STORE.set_continuous(
            session_id,
            not manual_mode,
            reason="reader_rewind_sentence_autopilot" if (not manual_mode) else "reader_rewind_sentence_manual_mode",
        )
        rew = _READER_STORE.rewind(session_id, unit="sentence")
        if not rew.get("ok"):
            return {"reply": "No pude retroceder una frase en esta sesión.", "no_auto_tts": True}
        out = _READER_STORE.next_chunk(session_id)
        chunk = out.get("chunk") if isinstance(out, dict) else None
        if not isinstance(chunk, dict):
            st_now = _READER_STORE.get_session(session_id, include_chunks=False)
            return {"reply": "No pude retomar tras volver una frase.", "no_auto_tts": True, "reader": _reader_meta(session_id, st_now)}
        tts_gate_required, tts_stream_id, _committed, tts_unavailable_detail = _reader_emit_chunk(
            session_id=session_id,
            chunk=chunk,
            allowed_tools=allowed_tools,
            commit_reason="reader_rewind_sentence_autocommit",
        )
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        meta_after = st_after.get("metadata", {}) if isinstance(st_after.get("metadata"), dict) else {}
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        auto_continue = bool(st_after.get("continuous_enabled", False)) and has_more
        prefix = "Retrocedí una frase y retomo desde ahí."
        if tts_unavailable_detail:
            prefix += f" Voz no disponible ({tts_unavailable_detail}). Queda en manual estable."
        return {
            "reply": _reader_chunk_reply(
                chunk,
                total_chunks=int(st_after.get("total_chunks", 0) or 0),
                title=str(meta_after.get("book_title", "")),
                prefix=prefix,
            ),
            "no_auto_tts": True,
            "reader": _reader_meta(
                session_id,
                st_after,
                chunk=chunk,
                auto_continue=auto_continue,
                tts_stream_id=tts_stream_id,
                tts_gate_required=tts_gate_required,
            ),
        }

    if any(k in normalized for k in ("volver un parrafo", "volver un párrafo")):
        st_before = _READER_STORE.get_session(session_id, include_chunks=False)
        if not st_before.get("ok"):
            return {"reply": "No hay sesión de lectura activa. Usá 'biblioteca' y 'leer libro <n>'.", "no_auto_tts": True}
        manual_mode = bool(st_before.get("manual_mode", False))
        _READER_STORE.set_continuous(
            session_id,
            not manual_mode,
            reason="reader_rewind_paragraph_autopilot" if (not manual_mode) else "reader_rewind_paragraph_manual_mode",
        )
        rew = _READER_STORE.rewind(session_id, unit="paragraph")
        if not rew.get("ok"):
            return {"reply": "No pude retroceder un párrafo en esta sesión.", "no_auto_tts": True}
        out = _READER_STORE.next_chunk(session_id)
        chunk = out.get("chunk") if isinstance(out, dict) else None
        if not isinstance(chunk, dict):
            st_now = _READER_STORE.get_session(session_id, include_chunks=False)
            return {"reply": "No pude retomar tras volver un párrafo.", "no_auto_tts": True, "reader": _reader_meta(session_id, st_now)}
        tts_gate_required, tts_stream_id, _committed, tts_unavailable_detail = _reader_emit_chunk(
            session_id=session_id,
            chunk=chunk,
            allowed_tools=allowed_tools,
            commit_reason="reader_rewind_paragraph_autocommit",
        )
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        meta_after = st_after.get("metadata", {}) if isinstance(st_after.get("metadata"), dict) else {}
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        auto_continue = bool(st_after.get("continuous_enabled", False)) and has_more
        prefix = "Retrocedí un párrafo y retomo desde ahí."
        if tts_unavailable_detail:
            prefix += f" Voz no disponible ({tts_unavailable_detail}). Queda en manual estable."
        return {
            "reply": _reader_chunk_reply(
                chunk,
                total_chunks=int(st_after.get("total_chunks", 0) or 0),
                title=str(meta_after.get("book_title", "")),
                prefix=prefix,
            ),
            "no_auto_tts": True,
            "reader": _reader_meta(
                session_id,
                st_after,
                chunk=chunk,
                auto_continue=auto_continue,
                tts_stream_id=tts_stream_id,
                tts_gate_required=tts_gate_required,
            ),
        }

    if any(k in normalized for k in ("estado lectura", "donde voy", "status lectura")):
        st = _READER_STORE.get_session(session_id, include_chunks=False)
        if not st.get("ok"):
            return {"reply": "No hay sesión de lectura activa en este chat.", "no_auto_tts": True}
        meta = st.get("metadata", {}) if isinstance(st.get("metadata"), dict) else {}
        title = str(meta.get("book_title", "")).strip()
        label = f"'{title}' | " if title else ""
        continuous = "on" if bool(st.get("continuous_enabled", st.get("continuous_active", False))) else "off"
        manual_mode = "on" if bool(st.get("manual_mode", False)) else "off"
        reason = str(st.get("continuous_reason", "")).strip() or "-"
        bookmark = st.get("bookmark") if isinstance(st.get("bookmark"), dict) else {}
        b_chunk = int(bookmark.get("chunk_index", -1) or -1)
        b_off = int(bookmark.get("offset_chars", 0) or 0)
        b_quality = str(bookmark.get("quality", "-") or "-")
        r_state = str(st.get("reader_state", "paused") or "paused")
        return {
            "reply": (
                f"Estado lectura: {label}cursor={int(st.get('cursor', 0))}/"
                f"{int(st.get('total_chunks', 0))}, pending={bool(st.get('has_pending', False))}, "
                f"done={bool(st.get('done', False))}, continua={continuous}({reason}), manual={manual_mode}, "
                f"barge_in={int(st.get('barge_in_count', 0))}, state={r_state}, "
                f"bookmark=chunk:{b_chunk},offset:{b_off},quality:{b_quality}."
            ),
            "no_auto_tts": True,
            "reader": _reader_meta(session_id, st, auto_continue=False),
        }

    if any(k in normalized for k in ("repetir", "repeti")):
        st = _READER_STORE.get_session(session_id, include_chunks=True)
        if not st.get("ok"):
            return {"reply": "No hay sesión de lectura activa. Abrí un libro con 'leer libro <n>'.", "no_auto_tts": True}
        meta = st.get("metadata", {}) if isinstance(st.get("metadata"), dict) else {}
        title = str(meta.get("book_title", "")).strip()
        chunk = st.get("pending") if isinstance(st.get("pending"), dict) else None
        if not isinstance(chunk, dict):
            cursor = int(st.get("cursor", 0) or 0)
            chunks = st.get("chunks") if isinstance(st.get("chunks"), list) else []
            idx = min(max(0, cursor - 1), len(chunks) - 1) if chunks else -1
            if idx < 0:
                return {"reply": "No hay bloque pendiente para repetir.", "no_auto_tts": True}
            raw = chunks[idx] if isinstance(chunks[idx], dict) else {}
            chunk = {
                "chunk_index": idx,
                "chunk_id": str(raw.get("id", f"chunk_{idx + 1:03d}")),
                "text": str(raw.get("text", "")),
            }
        chunk_text = str(chunk.get("text", "")).strip()
        tts_gate_required = ("tts" in allowed_tools) and _voice_enabled() and bool(chunk_text)
        tts_stream_id = 0
        if tts_gate_required:
            tts_stream_id = int(_speak_reply_async(chunk_text) or 0)
            tts_gate_required = tts_stream_id > 0
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        return {
            "reply": _reader_chunk_reply(
                chunk,
                total_chunks=int(st_after.get("total_chunks", 0) or 0),
                title=title,
                prefix="Repito el bloque actual.",
            ),
            "no_auto_tts": True,
            "reader": _reader_meta(
                session_id,
                st_after,
                chunk=chunk,
                auto_continue=bool(st_after.get("continuous_enabled", st_after.get("continuous_active", False)))
                and has_more,
                tts_stream_id=tts_stream_id,
                tts_gate_required=tts_gate_required,
            ),
        }

    if any(
        k in normalized
        for k in ("segui", "siguiente", "continuar", "continua", "contiuna", "contionua", "seguir leyendo", "sigas leyendo")
    ) or bool(
        re.search(r"\bnext\b", normalized)
    ):
        st_before = _READER_STORE.get_session(session_id, include_chunks=False)
        if not st_before.get("ok"):
            return {"reply": "No hay sesión de lectura activa. Usá 'biblioteca' y 'leer libro <n>'.", "no_auto_tts": True}
        _reader_force_commit_pending_if_stalled(session_id, st_before)
        st_before = _READER_STORE.get_session(session_id, include_chunks=False)
        manual_mode = bool(st_before.get("manual_mode", False))
        _READER_STORE.set_continuous(
            session_id,
            not manual_mode,
            reason="reader_continue_autopilot_resume" if (not manual_mode) else "reader_continue_manual_mode",
        )
        st_before = _READER_STORE.get_session(session_id, include_chunks=False)
        _READER_STORE.set_reader_state(session_id, "reading", reason="reader_continue")
        was_continuous = bool(st_before.get("continuous_enabled", st_before.get("continuous_active", False)))
        if was_continuous:
            wait_ms = _reader_pacing_wait_ms(st_before)
            if wait_ms > 0:
                return {
                    "reply": f"Pausa breve de lectura ({wait_ms} ms) para evitar ráfaga.",
                    "no_auto_tts": True,
                    "reader": _reader_meta(session_id, st_before, auto_continue=True),
                }
        out = _READER_STORE.next_chunk(session_id)
        if not out.get("ok"):
            return {"reply": "No hay sesión de lectura activa. Usá 'biblioteca' y 'leer libro <n>'.", "no_auto_tts": True}
        chunk = out.get("chunk")
        if not isinstance(chunk, dict):
            _READER_STORE.set_continuous(session_id, False, reason="reader_eof")
            st_end = _READER_STORE.get_session(session_id, include_chunks=False)
            return {
                "reply": "Fin de lectura. No hay más bloques.",
                "no_auto_tts": True,
                "reader": _reader_meta(session_id, st_end, auto_continue=False),
            }
        tts_gate_required, tts_stream_id, _committed, tts_unavailable_detail = _reader_emit_chunk(
            session_id=session_id,
            chunk=chunk,
            allowed_tools=allowed_tools,
            commit_reason="dc_reader_autocommit",
        )
        st_after = _READER_STORE.get_session(session_id, include_chunks=False)
        meta_after = st_after.get("metadata", {}) if isinstance(st_after.get("metadata"), dict) else {}
        title = str(meta_after.get("book_title", "")).strip()
        has_more = (not bool(st_after.get("done", False))) and int(st_after.get("cursor", 0) or 0) < int(
            st_after.get("total_chunks", 0) or 0
        )
        auto_continue = bool(st_after.get("continuous_enabled", st_after.get("continuous_active", False))) and has_more
        reply = _reader_chunk_reply(
            chunk,
            total_chunks=int(st_after.get("total_chunks", 0) or 0),
            title=title,
        )
        if tts_unavailable_detail:
            reply = (
                f"Autopiloto pausado: voz no disponible ({tts_unavailable_detail}). "
                "Sigo en manual estable.\n\n" + reply
            )
        if not str(chunk.get("text", "")).strip():
            reply = f"Error: bloque {int(chunk.get('chunk_index', 0) or 0) + 1} sin texto legible."
        return {
            "reply": reply,
            "no_auto_tts": True,
            "reader": _reader_meta(
                session_id,
                st_after,
                chunk=chunk,
                auto_continue=auto_continue,
                tts_stream_id=tts_stream_id,
                tts_gate_required=tts_gate_required,
            ),
        }

    yt_transport = _extract_youtube_transport_request(message)
    if yt_transport:
        if "firefox" not in allowed_tools:
            return {"reply": "La herramienta local 'firefox' está deshabilitada en esta sesión."}
        action, close_window = yt_transport
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {
                "action": f"youtube_transport_{action}",
                "site": "youtube",
                "url": "https://www.youtube.com/",
                "close_window": int(close_window),
            },
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        ok, detail = _youtube_transport_action(action, close_window=close_window, session_id=session_id)
        if not ok:
            return {"reply": f"No pude controlar YouTube. ({detail})"}
        if close_window:
            return {"reply": f"Listo: detuve YouTube y cerré la ventana. ({detail})"}
        if action == "play":
            return {"reply": f"Listo: reanudé YouTube. ({detail})"}
        return {"reply": f"Listo: pausé YouTube. ({detail})"}

    close_words = any(k in normalized for k in ("cerr", "close", "cierra"))
    close_web_human_variant = bool(
        re.search(r"\blo\s+que\s+abriste\b", normalized, flags=re.IGNORECASE)
        or re.search(r"\babriste\s+reci[eé]n\b", normalized, flags=re.IGNORECASE)
    )

    # Close browser windows opened by this system (tracked by session).
    # Examples:
    # - "cerrá las ventanas web que abriste"
    # - "reset ventanas web"
    if (
        (any(k in normalized for k in ("web", "navegador", "browser")) and any(k in normalized for k in ("ventan", "windows")))
        or (close_words and close_web_human_variant and any(k in normalized for k in ("web", "navegador", "browser")))
    ):
        if close_words:
            closed, errors = _close_recorded_browser_windows(session_id=session_id)
            if closed == 0 and not errors:
                fallback_closed, _fallback_details = _close_known_site_windows_in_current_workspace(max_windows=12)
                if fallback_closed > 0:
                    return {"reply": f"Cerré {fallback_closed} ventana(s) web por fallback de sitio."}
            if errors:
                return {"reply": f"Cerré {closed} ventana(s) web que abrí. Errores: {', '.join(errors)[:260]}"}
            return {"reply": f"Cerré {closed} ventana(s) web que abrí (solo las registradas por el sistema)."}
        if any(k in normalized for k in ("reset", "reinic", "olvid", "limpia")):
            _reset_recorded_browser_windows(session_id=session_id)
            return {"reply": "Listo: limpié el registro de ventanas web abiertas por el sistema para esta sesión."}

    # Human variant fallback:
    # "cerrá la ventana que abriste recién" (without explicit "web/browser")
    if any(k in normalized for k in ("cerr", "close", "cierra")) and any(
        k in normalized for k in ("ventan", "window", "pestañ", "tab")
    ):
        closed, errors = _close_recorded_browser_windows(session_id=session_id)
        if closed > 0 or errors:
            if errors:
                return {"reply": f"Cerré {closed} ventana(s) web que abrí. Errores: {', '.join(errors)[:260]}"}
            return {"reply": f"Cerré {closed} ventana(s) web que abrí (solo las registradas por el sistema)."}
        fallback_closed, _fallback_details = _close_known_site_windows_in_current_workspace(max_windows=12)
        if fallback_closed > 0:
            return {"reply": f"Cerré {fallback_closed} ventana(s) web por fallback de sitio."}

        return {"reply": "No veo ventanas registradas por esta sesión para cerrar."}

    # Safe local opens/closes for Desktop items (no deletion).
    # Examples:
    # - "abrí carpeta Lucy del escritorio"
    # - "abrí Moscu del escritorio"
    # - "cerrá las ventanas que abriste del escritorio"
    if any(k in normalized for k in ("escritorio", "desktop")):
        if any(k in normalized for k in ("reset", "reinic", "olvid", "limpia")) and any(k in normalized for k in ("ventan", "registro", "track")):
            if "desktop" not in allowed_tools:
                return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
            ok_g, gd = _guardrail_check(session_id, "desktop", {"action": "reset_windows"})
            if not ok_g:
                return {"reply": _guardrail_block_reply("desktop", gd)}
            desktop_ops.reset_recorded_windows(session_id=session_id)
            return {"reply": "Listo: limpié el registro de ventanas abiertas por el sistema para esta sesión."}

        if any(k in normalized for k in ("cerr", "close", "cierra")):
            if "desktop" not in allowed_tools:
                return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
            ok_g, gd = _guardrail_check(session_id, "desktop", {"action": "close_windows"})
            if not ok_g:
                return {"reply": _guardrail_block_reply("desktop", gd)}
            closed, errors = desktop_ops.close_recorded_windows(session_id=session_id)
            if errors:
                return {"reply": f"Cerré {closed} ventana(s) que abrí. Errores: {', '.join(errors)[:260]}"}
            return {"reply": f"Cerré {closed} ventana(s) que abrí (solo las registradas por el sistema)."}

        m_open = re.search(
            r"(?:abr[ií]|abrir|open)\s+(?:la\s+)?(?:carpeta|archivo|documento)?\s*([^\n\r]+?)\s+(?:del|en|de)\s+(?:mi\s+)?(?:escritorio|desktop)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if m_open:
            if "desktop" not in allowed_tools:
                return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
            name = m_open.group(1).strip(" \"'").strip()
            ok_g, gd = _guardrail_check(session_id, "desktop", {"action": "open_item", "name": name})
            if not ok_g:
                return {"reply": _guardrail_block_reply("desktop", gd)}
            res = desktop_ops.open_desktop_item(name, session_id=session_id)
            if not res.get("ok"):
                return {"reply": str(res.get("error", "No pude abrir el item del escritorio."))}
            tracked = int(res.get("tracked_windows", 0) or 0)
            verify = " (verificado por ventana)" if tracked else " (no pude verificar ventana; lo abrí igualmente)"
            return {
                "reply": f"Listo: abrí {res.get('kind')} '{res.get('name')}'.{verify} Ruta: {res.get('path')}"
            }

    # One-time helper: open a shadow-profile Chrome window so the user can login manually.
    # This avoids brittle automation failures like "login_required" for ChatGPT/Gemini.
    m_login = re.search(
        r"(?:login|loguea|logueate|inicia\s+sesion|iniciar\s+sesion)\s+(?:en\s+)?(chatgpt|chat\s*gpt|gemini)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if m_login:
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'web_ask' está deshabilitada en esta sesión."}
        if not shadow_explicit:
            return {
                "reply": (
                    "Bloqueado por política de cliente: login web_ask usa shadow profile. "
                    "Si querés ejecutarlo explícitamente, pedilo con 'login shadow gemini' o 'login shadow chatgpt'."
                )
            }
        provider = m_login.group(1).strip().lower()
        site_key = "chatgpt" if "chat" in provider else "gemini"
        login_url = _site_url(site_key) or f"https://{site_key}.com/"
        ok_g, gd = _guardrail_check(session_id, "browser_vision", {"action": "bootstrap_login", "url": login_url, "site": site_key})
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        ok, info = web_ask.bootstrap_login(site_key)
        if not ok:
            return {"reply": f"No pude lanzar bootstrap de login para {site_key}: {info}"}
        return {
            "reply": (
                f"Abrí una ventana de Chrome (shadow profile) para loguearte en {site_key}. "
                "Iniciá sesión ahí y luego cerrá esa ventana. Después probá de nuevo: "
                f"dialoga con {site_key}: <tu pregunta>"
            )
        }

    gemini_ask_text = _extract_gemini_ask_request(message)
    if gemini_ask_text:
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'gemini write' está deshabilitada en esta sesión."}
        ok_g, gd = _guardrail_check(
            session_id,
            "web_ask",
            {"site": "gemini", "prompt": gemini_ask_text[:500], "action": "ask"},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("web_ask", gd)}
        result = web_ask.run_web_ask("gemini", gemini_ask_text, timeout_ms=60000, followups=None)
        reply = web_ask.format_web_ask_reply("gemini", gemini_ask_text, result)
        return {"reply": reply}

    gemini_write_text = _extract_gemini_write_request(message)
    if gemini_write_text:
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'gemini write' está deshabilitada en esta sesión."}
        browser_gemini, _profile_hint = _site_browser_profile_hint("gemini")
        if browser_gemini != "chrome":
            return {
                "reply": (
                    "No pude ejecutar 'gemini write' automático: ese flujo hoy requiere Gemini en Chrome "
                    f"(config actual: {browser_gemini})."
                )
            }
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "gemini_write", "url": "https://gemini.google.com/app", "text": gemini_write_text[:500]},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        ok, detail = _gemini_write_in_current_workspace(gemini_write_text, session_id=session_id)
        if ok:
            return {"reply": f"Listo: escribí en Gemini \"{gemini_write_text}\" y di Enter. ({detail})"}
        return {"reply": f"No pude escribir en Gemini automáticamente (no verificado). ({detail})"}

    web_req = web_ask.extract_web_ask_request(message)
    if web_req is not None:
        # web_ask is separate from opening URLs via firefox. Keep backward-compat:
        # if someone only enabled firefox (old UI), still allow web_ask.
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'web_ask' está deshabilitada en esta sesión."}
        site_key, prompt, followups = web_req
        site_url = _site_url(site_key) or f"https://{site_key}.com/"
        ok_g, gd = _guardrail_check(
            session_id,
            "web_ask",
            {"site": site_key, "url": site_url, "prompt": prompt[:500], "action": "dialog"},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("web_ask", gd)}

        result = web_ask.run_web_ask(site_key, prompt, timeout_ms=60000, followups=followups)
        reply = web_ask.format_web_ask_reply(site_key, prompt, result)
        if str(result.get("status", "")).strip() in ("login_required", "captcha_required"):
            reply += (
                "\n\nNo abrí shadow profile automáticamente (política estricta de cliente). "
                "Si querés hacerlo, pedí explícitamente: 'login shadow gemini' o 'login shadow chatgpt'."
            )
        return {"reply": reply}

    if "firefox" in text and any(k in normalized for k in ("abr", "open", "lanz", "inici")):
        if "firefox" not in allowed_tools:
            return {"reply": "La herramienta local 'firefox' está deshabilitada en esta sesión."}
        url = _extract_url(message) or "about:blank"
        ok_g, gd = _guardrail_check(session_id, "browser_vision", {"action": "open_url", "url": url})
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        opened, error = _open_site_urls([(None, url)], session_id=session_id)
        if error:
            return {"reply": error}
        return {"reply": f"Listo, abrí Firefox en: {opened[0]}"}

    site_keys = _canonical_site_keys(message)
    wants_open = _looks_like_open_request(normalized)
    wants_search = ("busc" in normalized) or any(
        k in normalized for k in ("search", "investiga", "investigar", "encontra", "encontrá", "encontrar")
    )
    wants_new_chat = any(k in normalized for k in ("chat nuevo", "nuevo chat", "iniciar una conversacion", "iniciar conversacion"))
    topic = _extract_topic(message)

    # "Open Gemini" uses deterministic Chrome flow when Gemini is configured on Chrome;
    # otherwise it opens the configured browser/site URL directly.
    if "firefox" in allowed_tools and _looks_like_direct_gemini_open(normalized) and not wants_search and not wants_new_chat:
        browser_gemini, _profile_hint = _site_browser_profile_hint("gemini")
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "open_site", "site": "gemini", "url": "https://gemini.google.com/app"},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        if browser_gemini == "chrome":
            opened, error = _open_gemini_client_flow(session_id=session_id)
            if error:
                return {"reply": error}
            return {"reply": "Abrí Gemini en el cliente correcto con el flujo entrenado (Google -> Gemini)."}
        opened, error = _open_site_urls([("gemini", _site_url("gemini"))], session_id=session_id)
        if error:
            return {"reply": error}
        return {"reply": f"Abrí Gemini en {browser_gemini} para esta sesión: {opened[0]}"}

    search_req = web_search.extract_web_search_request(message)
    if not search_req and ("youtube" in site_keys) and _looks_like_youtube_play_request(normalized):
        yt_query = _extract_youtube_search_intent_query(message)
        if yt_query:
            search_req = (yt_query, "youtube")
    if search_req and search_req[1] is None:
        query_implicit, _site_none = search_req
        has_only_youtube_hint = ("youtube" in site_keys) and (not any(sk in site_keys for sk in ("google", "wikipedia", "chatgpt", "gemini", "gmail")))
        youtube_intent = wants_search or wants_open or _looks_like_youtube_play_request(normalized)
        if has_only_youtube_hint and youtube_intent:
            search_req = (query_implicit, "youtube")
    if "firefox" in allowed_tools and search_req and search_req[1] == "youtube" and _looks_like_youtube_play_request(normalized):
        query = search_req[0]
        video_url, reason = _pick_first_youtube_video_url(query)
        if not video_url:
            return {"reply": f"No pude encontrar un video reproducible en YouTube para '{query}'. ({reason})"}
        ok_g2, gd2 = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "open_video", "site": "youtube", "url": video_url},
        )
        if not ok_g2:
            return {"reply": _guardrail_block_reply("browser_vision", gd2)}
        opened, error = _open_site_urls([("youtube", video_url)], session_id=session_id)
        if error:
            return {"reply": error}
        ok_play, play_detail = _youtube_transport_action("play", close_window=False, session_id=session_id)
        if ok_play:
            return {"reply": f"Abrí y reproduzco un video de YouTube sobre '{query}': {opened[0]}"}
        return {"reply": f"Abrí el video de YouTube sobre '{query}', pero no pude confirmar play real. ({play_detail})"}

    if search_req and ("web_search" in allowed_tools):
        query, site_key = search_req
        if "firefox" in allowed_tools and site_key == "google" and wants_open:
            url = _build_site_search_url("google", query)
            if not url:
                return {"reply": "No pude construir la búsqueda en Google."}
            ok_g2, gd2 = _guardrail_check(
                session_id,
                "browser_vision",
                {"action": "open_site_search", "site": "google", "url": url},
            )
            if not ok_g2:
                return {"reply": _guardrail_block_reply("browser_vision", gd2)}
            opened, error = _open_site_urls([("google", url)], session_id=session_id)
            if error:
                return {"reply": error}
            return {"reply": f"Abrí la página de resultados de Google para '{query}': {opened[0]}"}
        if "firefox" in allowed_tools and _looks_like_open_top_results_request(normalized):
            ok_g, gd = _guardrail_check(
                session_id,
                "web_search",
                {"action": "search_open_top_results", "query": query[:500], "site": (site_key or ""), "top_n": 3},
            )
            if not ok_g:
                return {"reply": _guardrail_block_reply("web_search", gd)}
            sp = web_search.searxng_search(query, site_key=site_key, max_results=8)
            if not sp.get("ok"):
                err = str(sp.get("error", "web_search_failed"))
                return {"reply": f"No pude buscar en SearXNG local: {err}"}
            results = sp.get("results", []) if isinstance(sp.get("results"), list) else []
            top: list[dict] = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url", "")).strip()
                if not url:
                    continue
                top.append(item)
                if len(top) >= 3:
                    break
            if not top:
                return {"reply": f"No encontré resultados útiles para abrir sobre: {query}"}
            best_url = str(top[0].get("url", "")).strip()
            ok_g2, gd2 = _guardrail_check(
                session_id,
                "browser_vision",
                {"action": "open_search_result", "query": query[:500], "site": (site_key or ""), "url": best_url},
            )
            if not ok_g2:
                return {"reply": _guardrail_block_reply("browser_vision", gd2)}
            opened, error = _open_site_urls([(site_key, best_url)], session_id=session_id)
            if error:
                return {"reply": error}
            lines = [f"Abrí el mejor resultado de la búsqueda para '{query}': {opened[0]}", "Top 3 detectados:"]
            for i, item in enumerate(top, 1):
                title = str(item.get("title", "")).strip() or "(sin titulo)"
                url = str(item.get("url", "")).strip()
                lines.append(f"{i}. {title} - {url}")
            return {"reply": "\n".join(lines)}
        if "firefox" in allowed_tools and _looks_like_open_first_result_request(normalized):
            ok_g, gd = _guardrail_check(
                session_id,
                "web_search",
                {"action": "search_open_first_result", "query": query[:500], "site": (site_key or "")},
            )
            if not ok_g:
                return {"reply": _guardrail_block_reply("web_search", gd)}
            sp = web_search.searxng_search(query, site_key=site_key, max_results=6)
            if not sp.get("ok"):
                err = str(sp.get("error", "web_search_failed"))
                return {"reply": f"No pude buscar en SearXNG local: {err}"}
            results = sp.get("results", []) if isinstance(sp.get("results"), list) else []
            first_item: dict | None = None
            for item in results:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url", "")).strip()
                if not url:
                    continue
                first_item = item
                break
            if not first_item:
                return {"reply": f"No encontré resultados útiles para abrir sobre: {query}"}
            best_url = str(first_item.get("url", "")).strip()
            ok_g2, gd2 = _guardrail_check(
                session_id,
                "browser_vision",
                {"action": "open_search_result", "query": query[:500], "site": (site_key or ""), "url": best_url},
            )
            if not ok_g2:
                return {"reply": _guardrail_block_reply("browser_vision", gd2)}
            opened, error = _open_site_urls([(site_key, best_url)], session_id=session_id)
            if error:
                return {"reply": error}
            title = str(first_item.get("title", "")).strip() or "(sin titulo)"
            return {"reply": f"Abrí el primer resultado para '{query}': {title} - {opened[0]}"}
        ok_g, gd = _guardrail_check(
            session_id,
            "web_search",
            {"action": "search", "query": query[:500], "site": (site_key or "")},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("web_search", gd)}
        sp = web_search.searxng_search(query, site_key=site_key)
        if not sp.get("ok"):
            err = str(sp.get("error", "web_search_failed"))
            return {"reply": f"No pude buscar en SearXNG local: {err}"}
        return {"reply": web_search.format_results_for_user(sp)}

    if "firefox" in allowed_tools and wants_new_chat and topic and ("chatgpt" in site_keys or "gemini" in site_keys):
        entries = []
        if "chatgpt" in site_keys:
            entries.append(("chatgpt", _site_url("chatgpt")))
        if "gemini" in site_keys:
            entries.append(("gemini", _site_url("gemini")))
        if "youtube" in site_keys:
            yt_url = _build_site_search_url("youtube", topic)
            if yt_url:
                entries.append(("youtube", yt_url))
        if "wikipedia" in site_keys:
            wiki_url = _build_site_search_url("wikipedia", topic)
            if wiki_url:
                entries.append(("wikipedia", wiki_url))

        if entries:
            urls = [u for _k, u in entries if u]
            ok_g, gd = _guardrail_check(
                session_id,
                "browser_vision",
                {"action": "open_multiple", "url": (urls[0] if urls else ""), "urls": urls},
            )
            if not ok_g:
                return {"reply": _guardrail_block_reply("browser_vision", gd)}
            opened, error = _open_site_urls(entries, session_id=session_id)
            if error:
                return {"reply": error}
            prompt = (
                "Prompt sugerido para pegar en ChatGPT/Gemini: "
                f"'Iniciemos una conversación sobre {topic}. "
                "Dame contexto geopolítico actual, actores clave, riesgos y escenarios probables.'"
            )
            return {"reply": f"Abrí recursos para el tema '{topic}': {' | '.join(opened)}\n{prompt}"}

    m_yt_about = re.search(r"(?:video|videos)\s+de\s+youtube\s+sobre\s+(.+)", normalized, flags=re.IGNORECASE)
    if "firefox" in allowed_tools and m_yt_about:
        query = m_yt_about.group(1).strip(" .")
        if query in ("el tema", "ese tema", "este tema") and topic:
            query = topic
        url = _build_site_search_url("youtube", query)
        if not url:
            return {"reply": "No pude construir la búsqueda en YouTube."}
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "open_site_search", "site": "youtube", "url": url},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        opened, error = _open_site_urls([("youtube", url)], session_id=session_id)
        if error:
            return {"reply": error}
        return {"reply": f"Abrí videos de YouTube sobre '{query}': {opened[0]}"}

    if "firefox" in allowed_tools and site_keys and wants_open and not wants_search and not wants_new_chat:
        entries = [(site_key, _site_url(site_key)) for site_key in site_keys]
        urls = [u for _k, u in entries if u]
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "open_sites", "url": (urls[0] if urls else ""), "urls": urls},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        opened, error = _open_site_urls(entries, session_id=session_id)
        if error:
            return {"reply": error}
        listing = " | ".join(opened)
        return {"reply": f"Abrí estos sitios: {listing}"}

    wants_desktop = any(k in text for k in ("escritorio", "desktop"))
    asks_dirs = any(k in text for k in ("carpeta", "carpetas", "folder", "folders", "directorio", "directorios"))
    asks_files = any(k in text for k in ("archivo", "archivos", "file", "files"))
    asks_list = any(k in text for k in ("listar", "lista", "mostrar", "decir", "cuales", "cuáles", "que hay", "qué hay"))
    if wants_desktop and (asks_dirs or asks_files or asks_list):
        if "desktop" not in allowed_tools:
            return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
        ok_g, gd = _guardrail_check(session_id, "desktop", {"action": "list_desktop"})
        if not ok_g:
            return {"reply": _guardrail_block_reply("desktop", gd)}
        home = Path.home()
        candidates = [home / "Escritorio", home / "Desktop"]
        desktop = next((p for p in candidates if p.exists() and p.is_dir()), None)
        if desktop is None:
            return {"reply": "No encontré carpeta de escritorio en ~/Escritorio ni ~/Desktop."}

        entries = sorted(desktop.iterdir(), key=lambda p: p.name.lower())
        dirs = [p.name for p in entries if p.is_dir()]
        files = [p.name for p in entries if p.is_file()]

        if asks_dirs and not asks_files:
            content = ", ".join(dirs) if dirs else "(ninguna)"
            return {"reply": f"Carpetas reales en {desktop}: {content}"}

        if asks_files and not asks_dirs:
            content = ", ".join(files) if files else "(ninguno)"
            return {"reply": f"Archivos reales en {desktop}: {content}"}

        return {
            "reply": (
                f"Contenido real de {desktop} | carpetas: "
                + (", ".join(dirs) if dirs else "(ninguna)")
                + " | archivos: "
                + (", ".join(files) if files else "(ninguno)")
            )
        }

    return None


def _is_voice_control_command(message: str) -> bool:
    normalized = _normalize_text(message)
    keys = ("voz on", "voz off", "voz test", "activa voz", "desactiva voz", "silenciar voz", "mute voz")
    return any(k in normalized for k in keys)


def _build_system_prompt(mode: str, allowed_tools: set[str]) -> str:
    base = [
        "Habla en español claro.",
        "No inventes resultados.",
        "Si una acción falla, decilo explícitamente.",
    ]
    if mode == "conciso":
        base.append("Respuesta breve (1-3 líneas salvo que pidan detalle).")
    elif mode == "investigacion":
        base.append("Respuesta más detallada y estructurada.")
    else:
        base.append("Modo operativo: directo, preciso, sin relleno.")

    base.append(
        "Herramientas locales habilitadas en esta sesión: " + (", ".join(sorted(allowed_tools)) if allowed_tools else "ninguna")
    )
    return " ".join(base)


def _split_csv(raw: str) -> list[str]:
    out: list[str] = []
    for item in str(raw or "").split(","):
        val = item.strip()
        if val:
            out.append(val)
    return out


def _split_alias_csv(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in str(raw or "").split(","):
        part = item.strip()
        if not part or "=" not in part:
            continue
        alias, target = part.split("=", 1)
        alias_key = alias.strip()
        target_val = target.strip()
        if alias_key and target_val:
            out[alias_key] = target_val
    return out


def _model_name_variants(name: str) -> set[str]:
    val = str(name or "").strip()
    if not val:
        return set()
    out = {val}
    if ":" in val:
        out.add(val.split(":", 1)[0].strip())
    else:
        out.add(f"{val}:latest")
    return {item for item in out if item}


def _normalized_model_name_set(names: list[str]) -> set[str]:
    out: set[str] = set()
    for name in names:
        out.update(_model_name_variants(name))
    return out


def _unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _load_openclaw_config_dict() -> dict:
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        if not cfg_path.exists():
            return {}
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _discover_cloud_models() -> tuple[str, list[str]]:
    cfg = _load_openclaw_config_dict()
    configured: list[str] = []
    default_model = "openai-codex/gpt-5.1-codex-mini"

    try:
        default_model = str(cfg.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", default_model)).strip()
    except Exception:
        pass

    try:
        configured_map = cfg.get("agents", {}).get("defaults", {}).get("models", {})
        if isinstance(configured_map, dict):
            configured.extend([str(k).strip() for k in configured_map.keys() if str(k).strip()])
    except Exception:
        pass

    env_models = _split_csv(str(os.environ.get("DIRECT_CHAT_CLOUD_MODELS", "")).strip())
    models = _unique_keep_order([default_model] + configured + env_models)
    if not models:
        models = [default_model]
    return default_model, models


def _discover_ollama_models() -> list[str]:
    base = str(os.environ.get("DIRECT_CHAT_OLLAMA_URL", "http://127.0.0.1:11434")).strip().rstrip("/")
    timeout_s = float(_int_env("DIRECT_CHAT_OLLAMA_LIST_TIMEOUT_SEC", 3))
    found: list[str] = []

    try:
        resp = requests.get(f"{base}/api/tags", timeout=max(1.0, timeout_s))
        if resp.status_code == 200:
            data = resp.json() if resp.content else {}
            models = data.get("models", []) if isinstance(data, dict) else []
            if isinstance(models, list):
                for item in models:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip() or str(item.get("model", "")).strip()
                    if name:
                        found.append(name)
    except Exception:
        pass

    if found:
        return _unique_keep_order(found)

    if shutil.which("ollama"):
        try:
            proc = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=max(2.0, timeout_s))
            if proc.returncode == 0:
                for idx, line in enumerate((proc.stdout or "").splitlines()):
                    if idx == 0:
                        continue
                    parts = line.split()
                    if parts:
                        name = str(parts[0]).strip()
                        if name and name.upper() != "NAME":
                            found.append(name)
        except Exception:
            pass

    return _unique_keep_order(found)


def _configured_local_model_candidates() -> tuple[list[str], bool]:
    # Preferred knob: strict allowlist for local selector entries.
    strict = _split_csv(str(os.environ.get("DIRECT_CHAT_OLLAMA_MODELS", "")).strip())
    if strict:
        return strict, True
    fallback = _split_csv(
        str(
            os.environ.get(
                "DIRECT_CHAT_LOCAL_MODEL_CANDIDATES",
                "dolphin-mixtral:latest,mistral-uncensored,qwen-32b-uncensored-q6",
            )
        ).strip()
    )
    return fallback, False


def _looks_embedding_model(model_id: str) -> bool:
    lower = str(model_id or "").strip().lower()
    if not lower:
        return False
    markers = (
        "embed",
        "embedding",
        "rerank",
        "colbert",
        "bge-",
        "e5-",
    )
    return any(token in lower for token in markers)


def _looks_vision_model(model_id: str) -> bool:
    return "vision" in str(model_id or "").strip().lower()


def _allow_vision_models() -> bool:
    return _env_flag("DIRECT_CHAT_ALLOW_VISION", False)


def _is_chat_selector_model(model_id: str) -> bool:
    # Direct chat selector should only show chat-capable text models.
    if _looks_embedding_model(model_id):
        return False
    if _looks_vision_model(model_id) and not _allow_vision_models():
        return False
    return True


def _model_alias_map() -> dict[str, str]:
    aliases = {
        "qwen-32b-uncensored-q6": "huihui_ai/qwq-abliterated:32b-Q6_K",
    }
    aliases.update(_split_alias_csv(str(os.environ.get("DIRECT_CHAT_LOCAL_MODEL_ALIASES", "")).strip()))
    return aliases


def _model_catalog(force_refresh: bool = False) -> dict:
    ttl = max(2, _int_env("DIRECT_CHAT_MODEL_CATALOG_TTL_SEC", 8))
    now = time.time()
    cached = _MODEL_CATALOG_CACHE.get("data")
    cache_ts = float(_MODEL_CATALOG_CACHE.get("ts", 0.0) or 0.0)
    if (not force_refresh) and cached and (now - cache_ts) < ttl:
        return cached

    default_cloud, cloud_models = _discover_cloud_models()
    installed_local = _discover_ollama_models()
    local_candidates, local_strict_allowlist = _configured_local_model_candidates()
    alias_map = _model_alias_map()
    alias_targets = {v for v in alias_map.values() if v}
    filtered_installed_local: list[str] = []
    candidate_set = set(local_candidates)
    for mid in installed_local:
        # Keep selector stable: if a target is already represented by an alias candidate,
        # do not expose the raw target model as a separate option.
        if mid in alias_targets and any(alias_map.get(cand) == mid for cand in local_candidates):
            continue
        if (not _is_chat_selector_model(mid)) and mid not in candidate_set:
            continue
        filtered_installed_local.append(mid)
    if local_strict_allowlist:
        local_all = _unique_keep_order(local_candidates)
    else:
        local_all = _unique_keep_order(local_candidates + filtered_installed_local)

    models: list[dict] = []
    by_id: dict[str, dict] = {}

    def _add(meta: dict) -> None:
        mid = str(meta.get("id", "")).strip()
        if not mid or mid in by_id:
            return
        by_id[mid] = meta
        models.append(meta)

    for mid in cloud_models:
        _add(
            {
                "id": mid,
                "label": mid,
                "backend": "cloud",
                "available": True,
            }
        )

    installed_set = _normalized_model_name_set(installed_local)
    local_selector_keys: set[str] = set()
    for mid in local_all:
        canonical_selector_id = mid[:-7] if mid.lower().endswith(":latest") else mid
        if canonical_selector_id in local_selector_keys:
            continue
        runtime_id = alias_map.get(mid, mid)
        is_available = runtime_id in installed_set
        if (not _is_chat_selector_model(mid)) and (not is_available):
            continue
        local_selector_keys.add(canonical_selector_id)
        _add(
            {
                "id": mid,
                "label": mid,
                "backend": "local",
                "available": is_available,
                "runtime_model": runtime_id,
                "alias_of": runtime_id if runtime_id != mid else "",
            }
        )

    default_model = str(os.environ.get("DIRECT_CHAT_DEFAULT_MODEL", "")).strip() or default_cloud
    if default_model not in by_id:
        default_model = default_cloud if default_cloud in by_id else (models[0]["id"] if models else "openai-codex/gpt-5.1-codex-mini")

    data = {
        "default_model": default_model,
        "models": models,
        "by_id": by_id,
        "ts": now,
    }
    _MODEL_CATALOG_CACHE["ts"] = now
    _MODEL_CATALOG_CACHE["data"] = data
    return data


class _ModelSelectionError(Exception):
    def __init__(self, code: str, model: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.model = model
        self.detail = detail

    def as_payload(self) -> dict:
        return {
            "error": self.code,
            "model": self.model,
            "detail": self.detail,
        }


class _BackendCallError(Exception):
    def __init__(self, code: str, detail: str, status: int = 502):
        super().__init__(detail)
        self.code = str(code or "BACKEND_ERROR")
        self.detail = str(detail or self.code)
        self.status = int(status or 502)

    def as_payload(self) -> dict:
        return {
            "error": self.code,
            "detail": self.detail,
        }


def _looks_missing_model_error(detail: str) -> bool:
    d = str(detail or "").strip().lower()
    if not d:
        return False
    markers = (
        "model not found",
        "not found, try pulling",
        "unknown model",
        "no such model",
        "missing model",
        "model_not_found",
        "does not exist",
        "not installed",
    )
    return any(m in d for m in markers)


def _resolve_model_request(model: str, model_backend: str | None = None) -> dict:
    catalog = _model_catalog()
    requested_model = str(model or "").strip() or str(catalog.get("default_model", "")).strip()
    requested_backend = str(model_backend or "").strip().lower()
    by_id = catalog.get("by_id", {})
    known = by_id.get(requested_model) if isinstance(by_id, dict) else None

    if not requested_model or not isinstance(known, dict):
        raise _ModelSelectionError(
            "UNKNOWN_MODEL",
            requested_model,
            "El modelo solicitado no existe en el catálogo actual.",
        )

    backend = str(known.get("backend", "")).strip().lower()
    available = bool(known.get("available", False))
    runtime_model = str(known.get("runtime_model", "")).strip() or requested_model

    if not available:
        raise _ModelSelectionError(
            "MISSING_MODEL",
            requested_model,
            "El modelo solicitado está en catálogo pero no está disponible/instalado.",
        )

    return {
        "requested_model": requested_model,
        "resolved_model": runtime_model,
        "resolved_backend": backend if backend in ("cloud", "local") else "cloud",
        "requested_backend": requested_backend if requested_backend in ("cloud", "local") else "",
    }


def _extract_reply_text(response_data: dict) -> str:
    if not isinstance(response_data, dict):
        return ""
    choices = response_data.get("choices", [])
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        if isinstance(content, str):
            return content
    message = response_data.get("message", {})
    if isinstance(message, dict):
        content = message.get("content", "")
        if isinstance(content, str):
            return content
    content = response_data.get("response", "")
    if isinstance(content, str):
        return content
    return ""


def load_gateway_token() -> str:
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    if not cfg_path.exists():
        raise RuntimeError(f"Missing OpenClaw config: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
    if not token:
        raise RuntimeError("Missing gateway.auth.token in ~/.openclaw/openclaw.json")
    return token


class Handler(BaseHTTPRequestHandler):
    server_version = "MolbotDirectChat/2.0"

    def _metrics_payload(self) -> dict:
        pid = os.getpid()
        rss_mb = _proc_rss_mb(pid)
        mem = _read_meminfo()
        mem_total_mb = (mem.get("MemTotal", 0) / 1024.0) if mem else None
        mem_avail_mb = (mem.get("MemAvailable", 0) / 1024.0) if mem else None
        mem_used_mb = (mem_total_mb - mem_avail_mb) if (mem_total_mb is not None and mem_avail_mb is not None) else None
        vram = _read_vram_nvidia()

        return {
            "ts": time.time(),
            "proc": {"pid": pid, "rss_mb": rss_mb},
            "sys": {"ram_total_mb": mem_total_mb, "ram_used_mb": mem_used_mb, "ram_avail_mb": mem_avail_mb},
            "gpu": {"vram": vram},
        }

    def _json(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except BrokenPipeError:
            # Client disconnected; avoid noisy tracebacks and "Empty reply" symptoms.
            return

    def _parse_payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8") or "{}")

    def _voice_payload(self, state: dict) -> dict:
        enabled = bool(state.get("enabled", False))
        stt_status = _STT_MANAGER.status()
        ui_last_sid, ui_last_age = _ui_session_snapshot()
        health = _alltalk_health_cached(force=False)
        server_ok = bool(health.get("ok", False))
        server_detail = str(health.get("detail", "health_unknown"))
        base_url = str(health.get("base_url", _alltalk_base_url()) or _alltalk_base_url())
        health_path = str(health.get("health_path", _alltalk_health_path()) or _alltalk_health_path())
        timeout_s = float(health.get("timeout_s", _alltalk_health_timeout_sec()) or _alltalk_health_timeout_sec())
        fallback_tools = _tts_fallback_available_tools()
        try:
            stt_min_chars = max(1, int(state.get("stt_min_chars", 3)))
        except Exception:
            stt_min_chars = 3
        try:
            stt_no_audio_timeout = max(1.0, float(state.get("stt_no_audio_timeout_sec", 3.0)))
        except Exception:
            stt_no_audio_timeout = 3.0
        try:
            stt_rms_threshold = max(0.001, float(state.get("stt_rms_threshold", 0.012)))
        except Exception:
            stt_rms_threshold = 0.012
        try:
            stt_segment_rms_threshold = max(0.0005, float(state.get("stt_segment_rms_threshold", stt_rms_threshold)))
        except Exception:
            stt_segment_rms_threshold = max(0.0005, float(stt_rms_threshold))
        try:
            stt_barge_rms_threshold = max(0.001, float(state.get("stt_barge_rms_threshold", stt_rms_threshold)))
        except Exception:
            stt_barge_rms_threshold = max(0.001, float(stt_rms_threshold))
        try:
            stt_barge_any_cooldown = max(300, int(state.get("stt_barge_any_cooldown_ms", 1200)))
        except Exception:
            stt_barge_any_cooldown = 1200
        try:
            stt_preamp_gain = max(0.05, float(state.get("stt_preamp_gain", 1.0)))
        except Exception:
            stt_preamp_gain = 1.0
        stt_agc_enabled = bool(state.get("stt_agc_enabled", False))
        try:
            stt_agc_target_rms = max(0.01, min(0.30, float(state.get("stt_agc_target_rms", 0.06))))
        except Exception:
            stt_agc_target_rms = 0.06
        return {
            "enabled": enabled,
            "voice_owner": _normalize_voice_owner(state.get("voice_owner", "chat")),
            "reader_mode_active": bool(state.get("reader_mode_active", False)),
            "reader_owner_token_set": bool(str(state.get("reader_owner_token", "")).strip()),
            "voice_mode_profile": _voice_mode_profile_from_state(state),
            "speaker": str(state.get("speaker", "")),
            "speaker_wav": str(state.get("speaker_wav", "")),
            "stt_device": str(state.get("stt_device", "")),
            "stt_min_chars": int(stt_min_chars),
            "stt_command_only": bool(state.get("stt_command_only", True)),
            "stt_chat_enabled": bool(state.get("stt_chat_enabled", _env_flag("DIRECT_CHAT_STT_CHAT_ENABLED", True))),
            "stt_debug": bool(state.get("stt_debug", False)),
            "stt_no_audio_timeout_sec": float(stt_no_audio_timeout),
            "stt_rms_threshold": float(stt_rms_threshold),
            "stt_segment_rms_threshold": float(stt_segment_rms_threshold),
            "stt_barge_rms_threshold": float(stt_barge_rms_threshold),
            "stt_barge_any": bool(state.get("stt_barge_any", False)),
            "stt_barge_any_cooldown_ms": int(stt_barge_any_cooldown),
            "stt_preamp_gain": float(stt_preamp_gain),
            "stt_agc_enabled": bool(stt_agc_enabled),
            "stt_agc_target_rms": float(stt_agc_target_rms),
            "stt_server_chat_bridge_enabled": bool(_voice_server_chat_bridge_enabled() and _DIRECT_CHAT_HTTP_PORT > 0),
            "provider": "alltalk",
            "tts_backend": "alltalk",
            "server_url": base_url,
            "tts_health_url": f"{base_url}{health_path}",
            "tts_health_path": health_path,
            "tts_health_timeout_sec": timeout_s,
            "server_ok": bool(server_ok),
            "server_detail": str(server_detail),
            "tts_fallback_tools": fallback_tools,
            "tts_available": bool(server_ok or fallback_tools),
            "tts_diagnostic": _voice_diagnostics(),
            "tts_playing": bool(_tts_is_playing()),
            "last_status": _VOICE_LAST_STATUS,
            **_tts_playback_state(),
            "ui_last_session_id": str(ui_last_sid or ""),
            "ui_last_seen_age_sec": (None if ui_last_age < 0.0 else float(ui_last_age)),
            **_bargein_status(),
            **stt_status,
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            raw = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if path == "/reader":
            raw = READER_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if path == "/api/reader":
            query = parse_qs(parsed.query)
            include = str(query.get("include_sessions", ["0"])[0]).strip().lower() in ("1", "true", "yes")
            self._json(200, _READER_STORE.summary(include_sessions=include))
            return

        if path == "/api/reader/books":
            self._json(200, _READER_LIBRARY.list_books())
            return

        if path == "/api/reader/session":
            query = parse_qs(parsed.query)
            sid = _safe_session_id(str(query.get("session_id", query.get("session", ["default"]))[0]))
            include_chunks = str(query.get("include_chunks", ["0"])[0]).strip().lower() in ("1", "true", "yes")
            out = _READER_STORE.get_session(sid, include_chunks=include_chunks)
            status = 200 if out.get("ok") else 404
            self._json(status, out)
            return

        if path == "/api/reader/session/next":
            query = parse_qs(parsed.query)
            sid = _safe_session_id(str(query.get("session_id", query.get("session", ["default"]))[0]))
            speak = str(query.get("speak", ["0"])[0]).strip().lower() in ("1", "true", "yes")
            autocommit = str(query.get("autocommit", ["0"])[0]).strip().lower() in ("1", "true", "yes")
            out = _READER_STORE.next_chunk(sid)
            if out.get("ok") and speak:
                chunk = out.get("chunk")
                stream_id = 0
                if isinstance(chunk, dict):
                    text = str(chunk.get("text", "")).strip()
                    if text:
                        stream_id = int(_speak_reply_async(text) or 0)
                        out["speak_started"] = stream_id > 0
                        out["tts_stream_id"] = stream_id
                    else:
                        out["speak_started"] = False
                        out["speak_detail"] = "reader_chunk_empty_text"
                    if autocommit and stream_id > 0:
                        _reader_autocommit_register(
                            stream_id=stream_id,
                            session_id=sid,
                            chunk_id=str(chunk.get("chunk_id", "")),
                            chunk_index=int(chunk.get("chunk_index", 0) or 0),
                            text_len=len(text),
                            start_offset_chars=int(chunk.get("offset_chars", 0) or 0),
                        )
                        out["autocommit_registered"] = True
                else:
                    out["speak_started"] = False
                    out["speak_detail"] = "reader_no_chunk"
                    if autocommit:
                        out["autocommit_registered"] = False
            status = 200 if out.get("ok") else 404
            self._json(status, out)
            return

        if path == "/api/history":
            query = parse_qs(parsed.query)
            sid = _safe_session_id((query.get("session", ["default"])[0]))
            model = str(query.get("model", [""])[0]).strip()
            model_backend = str(query.get("model_backend", [""])[0]).strip().lower()
            hist = _load_history(sid, model=model, backend=model_backend)
            self._json(
                200,
                {
                    "session_id": sid,
                    "model": model,
                    "model_backend": model_backend,
                    "history": hist,
                },
            )
            return

        if path == "/api/chat/poll":
            query = parse_qs(parsed.query)
            sid = _safe_session_id(str(query.get("session_id", query.get("session", ["default"]))[0]))
            _mark_ui_session_active(sid)
            try:
                after = int(str(query.get("after", ["0"])[0]).strip() or "0")
            except Exception:
                after = 0
            try:
                limit = int(str(query.get("limit", ["120"])[0]).strip() or "120")
            except Exception:
                limit = 120
            out = _chat_events_poll(sid, after_seq=after, limit=limit)
            self._json(200, {"ok": True, **out})
            return

        if path == "/api/metrics":
            self._json(200, self._metrics_payload())
            return

        if path == "/api/models":
            force = str(parse_qs(parsed.query).get("refresh", ["0"])[0]).strip().lower() in ("1", "true", "yes")
            catalog = _model_catalog(force_refresh=force)
            self._json(
                200,
                {
                    "default_model": str(catalog.get("default_model", "")),
                    "models": catalog.get("models", []),
                    "updated_ts": catalog.get("ts"),
                },
            )
            return

        if path == "/api/stt/poll":
            query = parse_qs(parsed.query)
            sid = _safe_session_id((query.get("session_id", ["default"])[0]))
            _mark_ui_session_active(sid)
            consumer = str(query.get("consumer", [""])[0]).strip().lower()
            try:
                limit = int(str(query.get("limit", ["3"])[0]).strip() or "3")
            except Exception:
                limit = 3
            stt_status = _STT_MANAGER.status()
            owner = str(stt_status.get("stt_owner_session_id", "")).strip()
            if owner and sid != owner:
                self._json(
                    409,
                    {
                        "ok": False,
                        "error": "stt_owner_mismatch",
                        "session_id": sid,
                        "items": [],
                        **stt_status,
                    },
                )
                return
            # When server-side chat bridge is active, UI polling must not drain
            # STT items or messages may be lost by double-consumption.
            if consumer == "ui" and _voice_server_chat_bridge_enabled() and _DIRECT_CHAT_HTTP_PORT > 0:
                items = []
            else:
                items = _STT_MANAGER.poll(session_id=sid, limit=limit)
            stt_status = _STT_MANAGER.status()
            self._json(
                200,
                {
                    "ok": True,
                    "session_id": sid,
                    "items": items,
                    **stt_status,
                },
            )
            return

        if path == "/api/stt/diag":
            query = parse_qs(parsed.query)
            sid = _safe_session_id((query.get("session_id", ["default"])[0]))
            _mark_ui_session_active(sid)
            stt_status = _STT_MANAGER.status()
            owner = str(stt_status.get("stt_owner_session_id", "")).strip()
            if owner and sid != owner:
                self._json(
                    409,
                    {
                        "ok": False,
                        "error": "stt_owner_mismatch",
                        "session_id": sid,
                        **stt_status,
                    },
                )
                return
            self._json(
                200,
                {
                    "ok": True,
                    "session_id": sid,
                    "state": _load_voice_state(),
                    "devices": _stt_list_input_devices(),
                    **stt_status,
                },
            )
            return

        if path == "/api/stt/level":
            query = parse_qs(parsed.query)
            sid = _safe_session_id((query.get("session_id", ["default"])[0]))
            _mark_ui_session_active(sid)
            stt_status = _STT_MANAGER.status()
            owner = str(stt_status.get("stt_owner_session_id", "")).strip()
            owner_mismatch = bool(owner and sid != owner)
            try:
                segment_threshold = max(
                    0.0005,
                    float(
                        stt_status.get(
                            "stt_segment_rms_threshold",
                            stt_status.get("stt_rms_threshold", 0.002),
                        )
                        or 0.002
                    ),
                )
            except Exception:
                segment_threshold = 0.002
            try:
                barge_threshold = max(
                    0.001,
                    float(
                        stt_status.get(
                            "stt_barge_rms_threshold",
                            stt_status.get("stt_rms_threshold", 0.012),
                        )
                        or 0.012
                    ),
                )
            except Exception:
                barge_threshold = 0.012
            self._json(
                200,
                {
                    "ok": True,
                    "session_id": sid,
                    "stt_owner_session_id": owner,
                    "owner_mismatch": owner_mismatch,
                    "rms": float(stt_status.get("stt_rms_current", 0.0) or 0.0),
                    "threshold": float(segment_threshold),
                    "threshold_effective": float(
                        stt_status.get("stt_effective_seg_thr", stt_status.get("stt_segment_rms_threshold", segment_threshold))
                        or segment_threshold
                    ),
                    "threshold_off": float(stt_status.get("stt_effective_seg_thr_off", 0.0) or 0.0),
                    "barge_threshold": float(barge_threshold),
                    "in_speech": bool(stt_status.get("stt_vad_active", False)),
                    "speech_hangover_ms": int(stt_status.get("stt_speech_hangover_ms", 0) or 0),
                    "vad_true_ratio": float(stt_status.get("stt_vad_true_ratio", 0.0) or 0.0),
                    "last_segment_ms": int(stt_status.get("stt_last_segment_ms", 0) or 0),
                    "min_segment_ms": int(stt_status.get("stt_effective_min_segment_ms", 0) or 0),
                    "silence_ms": int(stt_status.get("stt_silence_ms", 0) or 0),
                    "frames_seen": int(stt_status.get("stt_frames_seen", 0) or 0),
                    "last_audio_ts": float(stt_status.get("stt_last_audio_ts", 0.0) or 0.0),
                    "no_audio_input": bool(stt_status.get("stt_no_audio_input", False)),
                    "no_speech_detected": bool(stt_status.get("stt_no_speech_detected", False)),
                    "emit_count": int(stt_status.get("stt_emit_count", 0) or 0),
                    "voice_text_committed": int(stt_status.get("voice_text_committed", 0) or 0),
                    "stt_chat_commit_total": int(stt_status.get("stt_chat_commit_total", 0) or 0),
                    "stt_preamp_gain": float(stt_status.get("stt_preamp_gain", 1.0) or 1.0),
                    "stt_agc_enabled": bool(stt_status.get("stt_agc_enabled", False)),
                    "stt_agc_target_rms": float(stt_status.get("stt_agc_target_rms", 0.06) or 0.06),
                    "drop_count": int(stt_status.get("items_dropped", 0) or 0),
                    "drop_reason": str(stt_status.get("stt_drop_reason", "")),
                },
            )
            return

        if path == "/api/voice":
            state = _load_voice_state()
            self._json(200, self._voice_payload(state))
            return

        self.send_response(404)
        self.end_headers()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def _build_messages(self, message: str, history: list, mode: str, allowed_tools: set[str], attachments: list) -> list:
        clean = []
        if isinstance(history, list):
            for item in history[-60:]:
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                content = item.get("content")
                if role in ("user", "assistant") and isinstance(content, str):
                    clean.append({"role": role, "content": content})

        extra = ""
        if attachments:
            lines = []
            for a in attachments[:8]:
                if not isinstance(a, dict):
                    continue
                name = str(a.get("name", "adjunto"))
                typ = str(a.get("type", "file"))
                content = str(a.get("content", ""))
                lines.append(f"- {name} ({typ})")
                if content and typ == "text":
                    lines.append(content[:3000])
            if lines:
                extra = "\n\nContexto de adjuntos:\n" + "\n".join(lines)

        system = {
            "role": "system",
            "content": _build_system_prompt(mode, allowed_tools),
        }
        return [system] + clean + [{"role": "user", "content": message + extra}]

    def _call_gateway(self, payload: dict) -> dict:
        timeout_s = max(8.0, float(_int_env("DIRECT_CHAT_GATEWAY_TIMEOUT_SEC", 45)))
        req = Request(
            url=f"http://127.0.0.1:{self.server.gateway_port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.server.gateway_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if e.code in (400, 404) and _looks_missing_model_error(detail):
                raise _BackendCallError("MISSING_MODEL", detail, status=400) from e
            raise _BackendCallError("GATEWAY_HTTP_ERROR", f"HTTP {e.code}: {detail[:400]}", status=502) from e
        except URLError as e:
            raise _BackendCallError("GATEWAY_UNREACHABLE", str(e), status=502) from e
        except (socket.timeout, TimeoutError) as e:
            raise _BackendCallError("MODEL_TIMEOUT", f"gateway timeout after {timeout_s:.0f}s", status=504) from e

    def _call_ollama(self, payload: dict) -> dict:
        base = str(os.environ.get("DIRECT_CHAT_OLLAMA_URL", "http://127.0.0.1:11434")).strip().rstrip("/")
        timeout_s = max(10.0, float(_int_env("DIRECT_CHAT_OLLAMA_TIMEOUT_SEC", 120)))
        conn_timeout_s = max(2.0, float(_int_env("DIRECT_CHAT_OLLAMA_CONNECT_TIMEOUT_SEC", 4)))

        v1_payload = dict(payload)
        v1_payload["stream"] = False

        try:
            r = requests.post(f"{base}/v1/chat/completions", json=v1_payload, timeout=(conn_timeout_s, timeout_s))
            if r.status_code < 400:
                out = r.json() if r.content else {}
                if isinstance(out, dict):
                    return out
            detail = (r.text or "")[:300].replace("\n", " ")
            if r.status_code in (400, 404) and _looks_missing_model_error(detail):
                raise _BackendCallError("MISSING_MODEL", detail, status=400)
            if r.status_code not in (400, 404, 405):
                raise _BackendCallError("OLLAMA_HTTP_ERROR", f"HTTP {r.status_code}: {detail}", status=502)
        except requests.exceptions.Timeout as e:
            raise _BackendCallError("MODEL_TIMEOUT", f"ollama timeout after {timeout_s:.0f}s", status=504) from e
        except requests.exceptions.RequestException as e:
            # Fallback below to legacy Ollama API.
            last_err = str(e)
        else:
            last_err = ""

        legacy_payload = {
            "model": str(payload.get("model", "")).strip(),
            "messages": payload.get("messages", []),
            "stream": False,
        }
        temp = payload.get("temperature")
        if temp is not None:
            legacy_payload["options"] = {"temperature": temp}

        try:
            r2 = requests.post(f"{base}/api/chat", json=legacy_payload, timeout=(conn_timeout_s, timeout_s))
        except requests.exceptions.Timeout as e:
            raise _BackendCallError("MODEL_TIMEOUT", f"ollama timeout after {timeout_s:.0f}s", status=504) from e
        except requests.exceptions.RequestException as e:
            raise _BackendCallError("OLLAMA_UNREACHABLE", last_err or str(e), status=502) from e

        if r2.status_code >= 400:
            detail = (r2.text or "")[:320].replace("\n", " ")
            if r2.status_code in (400, 404) and _looks_missing_model_error(detail):
                raise _BackendCallError("MISSING_MODEL", detail, status=400)
            raise _BackendCallError("OLLAMA_HTTP_ERROR", f"HTTP {r2.status_code}: {detail}", status=502)

        raw = r2.json() if r2.content else {}
        content = _extract_reply_text(raw)
        if not content.strip():
            content = str(raw.get("response", "") if isinstance(raw, dict) else "")
        return {
            "id": raw.get("id", "ollama-local"),
            "model": str(payload.get("model", "")).strip(),
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "provider": "ollama",
            "raw": raw,
        }

    def _call_model_backend(self, backend: str, payload: dict) -> dict:
        if backend == "local":
            return self._call_ollama(payload)
        return self._call_gateway(payload)

    def do_POST(self):
        if self.path == "/api/reader/rescan":
            try:
                out = _READER_LIBRARY.rescan()
                self._json(200, out)
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if self.path == "/api/reader/session/start":
            try:
                payload = self._parse_payload()
                sid = _safe_session_id(str(payload.get("session_id", "default")))
                chunks = payload.get("chunks", [])
                text = str(payload.get("text", ""))
                reset = bool(payload.get("reset", True))
                metadata = payload.get("metadata")
                book_id = str(payload.get("book_id", "")).strip()
                if book_id:
                    loaded = _READER_LIBRARY.get_book_text(book_id)
                    if not loaded.get("ok"):
                        err = str(loaded.get("error", "reader_book_not_found"))
                        status = 404 if err in ("reader_book_not_found", "reader_book_cache_missing") else 400
                        self._json(status, loaded)
                        return
                    text = str(loaded.get("text", ""))
                    chunks = []
                    meta = {}
                    if isinstance(metadata, dict):
                        meta.update(metadata)
                    book_meta = loaded.get("book")
                    if isinstance(book_meta, dict):
                        meta["book_id"] = str(book_meta.get("book_id", ""))
                        meta["book_title"] = str(book_meta.get("title", ""))
                        meta["book_format"] = str(book_meta.get("format", ""))
                        meta["book_source_path"] = str(book_meta.get("source_path", ""))
                    metadata = meta
                out = _READER_STORE.start_session(sid, chunks=chunks, text=text, reset=reset, metadata=metadata)
                self._json(200, out)
            except ValueError as e:
                self._json(400, {"ok": False, "error": str(e)})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if self.path == "/api/reader/session/commit":
            try:
                payload = self._parse_payload()
                sid = _safe_session_id(str(payload.get("session_id", "default")))
                chunk_id = str(payload.get("chunk_id", "")).strip()
                chunk_index = payload.get("chunk_index")
                if chunk_index in ("", None):
                    chunk_index = None
                else:
                    chunk_index = int(chunk_index)
                reason = str(payload.get("reason", "")).strip()
                out = _READER_STORE.commit(sid, chunk_id=chunk_id, chunk_index=chunk_index, reason=reason)
                if out.get("ok"):
                    self._json(200, out)
                    return
                err = str(out.get("error", "")).strip()
                if err == "reader_session_not_found":
                    self._json(404, out)
                elif "mismatch" in err:
                    self._json(409, out)
                else:
                    self._json(400, out)
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if self.path == "/api/reader/progress":
            try:
                payload = self._parse_payload()
                sid = _safe_session_id(str(payload.get("session_id", "default")))
                chunk_id = str(payload.get("chunk_id", "")).strip()
                raw_offset = payload.get("offset_chars")
                try:
                    offset_chars = int(raw_offset if raw_offset is not None else 0)
                except Exception:
                    offset_chars = 0
                quality = str(payload.get("quality", "ui_live")).strip() or "ui_live"
                out = _READER_STORE.update_progress(
                    sid,
                    chunk_id=chunk_id,
                    offset_chars=offset_chars,
                    quality=quality,
                )
                if out.get("ok") and bool(out.get("progress_updated", False)):
                    self._json(200, out)
                    return
                detail = str(out.get("detail", "")).strip()
                if detail == "reader_no_pending_chunk":
                    self._json(409, out)
                    return
                if detail == "reader_progress_chunk_mismatch":
                    self._json(409, out)
                    return
                if str(out.get("error", "")) == "reader_session_not_found":
                    self._json(404, out)
                    return
                self._json(400, out)
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if self.path in ("/api/reader/session/barge_in", "/api/reader/session/barge-in"):
            try:
                payload = self._parse_payload()
                sid = _safe_session_id(str(payload.get("session_id", "default")))
                detail = str(payload.get("detail", "barge_in_triggered"))
                keyword = str(payload.get("keyword", ""))
                raw_offset = payload.get("offset_hint")
                offset_hint = None
                if raw_offset not in ("", None):
                    try:
                        offset_hint = int(raw_offset)
                    except Exception:
                        offset_hint = None
                raw_playback = payload.get("playback_ms")
                playback_ms = None
                if raw_playback not in ("", None):
                    try:
                        playback_ms = float(raw_playback)
                    except Exception:
                        playback_ms = None
                out = _READER_STORE.mark_barge_in(
                    sid,
                    detail=detail,
                    keyword=keyword,
                    offset_hint=offset_hint,
                    playback_ms=playback_ms,
                )
                status = 200 if out.get("ok") else 404
                self._json(status, out)
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if self.path == "/api/stt/inject":
            try:
                if not _env_flag("DIRECT_CHAT_STT_INJECT_ENABLED", True):
                    self._json(403, {"ok": False, "error": "stt_inject_disabled"})
                    return
                payload = self._parse_payload()
                sid = _safe_session_id(str(payload.get("session_id", "default")))
                text = str(payload.get("text", "")).strip()
                cmd = str(payload.get("cmd", "")).strip()
                out = _STT_MANAGER.inject(session_id=sid, text=text, cmd=cmd)
                status = 200 if bool(out.get("ok", False)) else 400
                if str(out.get("error", "")) == "stt_owner_mismatch":
                    status = 409
                self._json(status, {"session_id": sid, **out, **_STT_MANAGER.status()})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        if self.path == "/api/voice":
            try:
                payload = self._parse_payload()
                state = _load_voice_state()
                session_id = _safe_session_id(str(payload.get("session_id", "default")))
                requested_profile = None
                if "voice_mode_profile" in payload:
                    requested_profile = str(payload.get("voice_mode_profile", ""))
                    _apply_voice_mode_profile(state, requested_profile)

                requested_owner = None
                if "voice_owner" in payload:
                    requested_owner = _normalize_voice_owner(payload.get("voice_owner"))
                requested_reader_active = None
                if "reader_mode_active" in payload:
                    requested_reader_active = bool(payload.get("reader_mode_active"))
                requested_enabled = None
                if "enabled" in payload:
                    requested_enabled = bool(payload.get("enabled"))
                requested_owner_token = str(payload.get("reader_owner_token", "")).strip()[:120]

                current_owner = _normalize_voice_owner(state.get("voice_owner", "chat"))
                current_reader_active = bool(state.get("reader_mode_active", False))
                current_owner_token = str(state.get("reader_owner_token", "")).strip()[:120]
                ownership_locked = bool(current_owner == "reader" and current_reader_active and current_owner_token)
                release_requested = bool(
                    (requested_owner is not None and requested_owner != "reader")
                    or (requested_reader_active is not None and (not requested_reader_active))
                    or (requested_enabled is not None and (not requested_enabled))
                )
                token_matches = bool(
                    requested_owner_token
                    and current_owner_token
                    and requested_owner_token == current_owner_token
                )
                ownership_conflict = False
                if ownership_locked and release_requested and (not token_matches):
                    ownership_conflict = True
                    if requested_owner is not None and requested_owner != "reader":
                        requested_owner = None
                    if requested_reader_active is not None and not requested_reader_active:
                        requested_reader_active = None
                    if requested_enabled is not None and not requested_enabled:
                        requested_enabled = None

                if requested_owner is not None:
                    state["voice_owner"] = requested_owner
                if requested_reader_active is not None:
                    state["reader_mode_active"] = requested_reader_active
                reader_acquire_requested = bool((requested_owner == "reader") or (requested_reader_active is True))
                if reader_acquire_requested and requested_owner_token:
                    state["reader_owner_token"] = requested_owner_token
                elif requested_owner is not None and requested_owner != "reader":
                    state["reader_owner_token"] = ""
                elif requested_reader_active is not None and not requested_reader_active:
                    state["reader_owner_token"] = ""

                if requested_enabled is not None:
                    if (not requested_enabled) and _tts_is_playing():
                        _request_tts_stop(
                            reason="voice_disabled",
                            keyword="voice_off",
                            detail="triggered:voice_disabled",
                            session_id=session_id,
                        )
                    _set_voice_enabled(requested_enabled, session_id=session_id if requested_enabled else "")
                    state = _load_voice_state()
                    if requested_profile is not None:
                        _apply_voice_mode_profile(state, requested_profile)
                    if requested_owner is not None:
                        state["voice_owner"] = requested_owner
                    if requested_reader_active is not None:
                        state["reader_mode_active"] = requested_reader_active
                    if reader_acquire_requested and requested_owner_token:
                        state["reader_owner_token"] = requested_owner_token
                    elif requested_owner is not None and requested_owner != "reader":
                        state["reader_owner_token"] = ""
                    elif requested_reader_active is not None and not requested_reader_active:
                        state["reader_owner_token"] = ""
                elif bool(state.get("enabled", False) or state.get("stt_chat_enabled", False)) and session_id != "default":
                    _STT_MANAGER.enable(session_id=session_id)

                speaker = str(payload.get("speaker", "")).strip()
                if speaker:
                    state["speaker"] = speaker
                speaker_wav = str(payload.get("speaker_wav", "")).strip()
                if speaker_wav:
                    state["speaker_wav"] = speaker_wav
                if "stt_device" in payload:
                    state["stt_device"] = str(payload.get("stt_device", "")).strip()
                if "stt_command_only" in payload:
                    state["stt_command_only"] = bool(payload.get("stt_command_only"))
                if "stt_chat_enabled" in payload:
                    state["stt_chat_enabled"] = bool(payload.get("stt_chat_enabled"))
                if "stt_debug" in payload:
                    state["stt_debug"] = bool(payload.get("stt_debug"))
                if "stt_min_chars" in payload:
                    try:
                        state["stt_min_chars"] = max(1, int(payload.get("stt_min_chars", state.get("stt_min_chars", 3))))
                    except Exception:
                        pass
                if "stt_no_audio_timeout_sec" in payload:
                    try:
                        state["stt_no_audio_timeout_sec"] = max(
                            1.0, float(payload.get("stt_no_audio_timeout_sec", state.get("stt_no_audio_timeout_sec", 3.0)))
                        )
                    except Exception:
                        pass
                if "stt_rms_threshold" in payload:
                    try:
                        thr = max(0.001, float(payload.get("stt_rms_threshold", state.get("stt_rms_threshold", 0.012))))
                        # Backward-compatible payload: keep both thresholds aligned.
                        state["stt_rms_threshold"] = thr
                        state["stt_segment_rms_threshold"] = max(0.0005, thr)
                        state["stt_barge_rms_threshold"] = max(0.001, thr)
                    except Exception:
                        pass
                if "stt_segment_rms_threshold" in payload:
                    try:
                        state["stt_segment_rms_threshold"] = max(
                            0.0005,
                            float(payload.get("stt_segment_rms_threshold", state.get("stt_segment_rms_threshold", 0.002))),
                        )
                    except Exception:
                        pass
                if "stt_barge_rms_threshold" in payload:
                    try:
                        barge_thr = max(
                            0.001,
                            float(payload.get("stt_barge_rms_threshold", state.get("stt_barge_rms_threshold", 0.012))),
                        )
                        state["stt_barge_rms_threshold"] = barge_thr
                        state["stt_rms_threshold"] = barge_thr
                    except Exception:
                        pass
                if "stt_barge_any" in payload:
                    state["stt_barge_any"] = bool(payload.get("stt_barge_any"))
                if "stt_barge_any_cooldown_ms" in payload:
                    try:
                        state["stt_barge_any_cooldown_ms"] = max(
                            300, int(payload.get("stt_barge_any_cooldown_ms", state.get("stt_barge_any_cooldown_ms", 1200)))
                        )
                    except Exception:
                        pass
                if "stt_preamp_gain" in payload:
                    try:
                        state["stt_preamp_gain"] = max(0.05, float(payload.get("stt_preamp_gain", state.get("stt_preamp_gain", 1.0))))
                    except Exception:
                        pass
                if "stt_agc_enabled" in payload:
                    state["stt_agc_enabled"] = bool(payload.get("stt_agc_enabled"))
                if "stt_agc_target_rms" in payload:
                    try:
                        state["stt_agc_target_rms"] = max(
                            0.01,
                            min(0.30, float(payload.get("stt_agc_target_rms", state.get("stt_agc_target_rms", 0.06)))),
                        )
                    except Exception:
                        pass
                # Ensure requested profile wins over any partial runtime knobs.
                if requested_profile is not None:
                    _apply_voice_mode_profile(state, requested_profile)
                state["stt_rms_threshold"] = _stt_legacy_rms_threshold_from_state(state)
                state["stt_segment_rms_threshold"] = _stt_segment_rms_threshold_from_state(state)
                state["stt_barge_rms_threshold"] = _stt_barge_rms_threshold_from_state(state)
                state["voice_owner"] = _normalize_voice_owner(state.get("voice_owner", "chat"))
                state["reader_mode_active"] = bool(state.get("reader_mode_active", False))
                state["reader_owner_token"] = str(state.get("reader_owner_token", "")).strip()[:120]
                state["voice_mode_profile"] = _voice_mode_profile_from_state(state)
                _save_voice_state(state)
                os.environ["DIRECT_CHAT_STT_DEVICE"] = str(state.get("stt_device", "")).strip()
                should_run = bool(state.get("enabled", False) or state.get("stt_chat_enabled", False))
                _sync_stt_with_voice(
                    enabled=bool(state.get("enabled", False)),
                    session_id=(session_id if should_run and session_id != "default" else ""),
                )
                if should_run and (
                    "stt_device" in payload
                    or "stt_command_only" in payload
                    or "stt_chat_enabled" in payload
                    or "stt_debug" in payload
                    or "stt_min_chars" in payload
                    or "stt_rms_threshold" in payload
                    or "stt_segment_rms_threshold" in payload
                    or "stt_barge_rms_threshold" in payload
                    or "stt_barge_any" in payload
                    or "stt_barge_any_cooldown_ms" in payload
                    or "stt_preamp_gain" in payload
                    or "stt_agc_enabled" in payload
                    or "stt_agc_target_rms" in payload
                    or "voice_mode_profile" in payload
                ):
                    _STT_MANAGER.restart()
                self._json(
                    200,
                    {
                        "ok": True,
                        "ownership_conflict": bool(ownership_conflict),
                        **self._voice_payload(state),
                    },
                )
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if self.path == "/api/history":
            try:
                payload = self._parse_payload()
                sid = _safe_session_id(str(payload.get("session_id", "default")))
                model = str(payload.get("model", "")).strip()
                model_backend = str(payload.get("model_backend", "")).strip().lower()
                if model_backend not in ("cloud", "local"):
                    model_backend = ""
                history = payload.get("history", [])
                if not isinstance(history, list):
                    history = []
                safe = []
                for item in history[-200:]:
                    if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                        safe.append({"role": item["role"], "content": item["content"]})
                _save_history(sid, safe, model=model, backend=model_backend)
                if not safe:
                    _chat_events_reset(sid)
                self._json(200, {"ok": True, "session_id": sid, "model": model, "model_backend": model_backend})
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if self.path not in ("/api/chat", "/api/chat/stream"):
            self.send_response(404)
            self.end_headers()
            return

        try:
            payload = self._parse_payload()
            message = str(payload.get("message", "")).strip()
            session_id = _safe_session_id(str(payload.get("session_id", "default")))
            _mark_ui_session_active(session_id)
            allowed_tools = _extract_allowed_tools(payload)
            source_tag = str(payload.get("source", "")).strip().lower()
            voice_item_ts = 0.0
            if "voice_item_ts" in payload:
                try:
                    voice_item_ts = float(payload.get("voice_item_ts", 0.0) or 0.0)
                except Exception:
                    voice_item_ts = 0.0
            is_voice_origin = bool(source_tag.startswith("voice_") or voice_item_ts > 0.0)
            if source_tag:
                user_msg_source = source_tag
            else:
                user_msg_source = "stt_voice" if is_voice_origin else "ui_text"
            record_chat_events = (not source_tag.startswith("ui_auto_"))
            if is_voice_origin and message and (not _voice_chat_should_process(session_id, message, ts=voice_item_ts)):
                if self.path == "/api/chat/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    self.close_connection = True
                    return
                self._json(200, {"reply": "", "deduped": True, "source": source_tag or "voice"})
                return
            # allow_local_action_on_unknown_model
            reader_control_command = _is_reader_control_command(message) if message else False
            if message:
                st_reader = _READER_STORE.get_session(session_id, include_chunks=False)
                reader_state = str(st_reader.get("reader_state", "")).strip().lower() if st_reader.get("ok") else ""
                reader_active = bool(_READER_STORE.is_continuous(session_id) or reader_state == "reading")
                if (not reader_control_command) and reader_active:
                    _READER_STORE.set_continuous(session_id, False, reason="reader_user_interrupt")
                    _READER_STORE.set_reader_state(session_id, "commenting", reason="reader_user_interrupt")
                # Typed input should barge-in current TTS playback, even outside strict
                # reader "reading" state (for example while commenting in /reader).
                if (
                    user_msg_source == "ui_text"
                    and (not source_tag.startswith("ui_auto_"))
                    and _tts_is_playing()
                ):
                    _request_tts_stop(
                        reason=("reader_user_interrupt" if reader_active else "typed_interrupt"),
                        keyword="typed_interrupt",
                        detail="triggered:typed_interrupt",
                        session_id=session_id,
                    )

            model = str(payload.get("model", "openai-codex/gpt-5.1-codex-mini")).strip()
            requested_backend = str(payload.get("model_backend", "")).strip().lower()
            try:
                model_resolution = _resolve_model_request(model=model, model_backend=requested_backend)
            except _ModelSelectionError as e:
                # If the selected model is unknown/missing, still allow local actions.
                local_action = _maybe_handle_local_action(message, allowed_tools, session_id=session_id)
                if local_action is not None:
                    reply = str(local_action.get("reply", ""))
                    merged_local = []
                    raw_hist = payload.get("history", [])
                    if isinstance(raw_hist, list):
                        for item in raw_hist[-80:]:
                            if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                                merged_local.append({"role": item["role"], "content": item["content"]})
                    merged_local.append({"role": "user", "content": message})
                    merged_local.append({"role": "assistant", "content": reply})
                    _save_history(session_id, merged_local, model=model, backend=requested_backend)
                    if record_chat_events:
                        _chat_events_append(
                            session_id,
                            role="user",
                            content=message,
                            source=user_msg_source,
                            ts=voice_item_ts if is_voice_origin else time.time(),
                        )
                        _chat_events_append(session_id, role="assistant", content=reply, source="local_action", ts=time.time())
                    if self.path == "/api/chat/stream":
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        if (not _is_voice_control_command(message)) and (not bool(local_action.get("no_auto_tts"))):
                            _maybe_speak_reply(reply, allowed_tools)
                        event = {"token": reply}
                        if isinstance(local_action.get("reader"), dict):
                            event["reader"] = local_action.get("reader")
                        out = json.dumps(event, ensure_ascii=False).encode("utf-8")
                        try:
                            self.wfile.write(b"data: " + out + b"\n\n")
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()
                        except BrokenPipeError:
                            return
                        self.close_connection = True
                        return
                    if (not _is_voice_control_command(message)) and (not bool(local_action.get("no_auto_tts"))):
                        _maybe_speak_reply(reply, allowed_tools)
                    self._json(200, local_action)
                    return
                self._json(400, e.as_payload())
                return
            model = str(model_resolution.get("requested_model", "")).strip() or model
            routed_model = str(model_resolution.get("resolved_model", "")).strip() or model
            resolved_backend = str(model_resolution.get("resolved_backend", "")).strip() or "cloud"
            history = payload.get("history", [])
            mode = str(payload.get("mode", "operativo"))
            attachments = payload.get("attachments", [])
            # Local-only tools that should not be advertised to the upstream model.
            allowed_tools_for_prompt = set(allowed_tools)
            allowed_tools_for_prompt.discard("web_search")

            if not message:
                self._json(400, {"error": "Missing message"})
                return

            local_action = _maybe_handle_local_action(message, allowed_tools, session_id=session_id)
            if local_action is not None:
                reply = str(local_action.get("reply", ""))
                merged_local = []
                if isinstance(history, list):
                    for item in history[-80:]:
                        if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                            merged_local.append({"role": item["role"], "content": item["content"]})
                merged_local.append({"role": "user", "content": message})
                merged_local.append({"role": "assistant", "content": reply})
                _save_history(session_id, merged_local, model=model, backend=resolved_backend)
                if record_chat_events:
                    _chat_events_append(
                        session_id,
                        role="user",
                        content=message,
                        source=user_msg_source,
                        ts=voice_item_ts if is_voice_origin else time.time(),
                    )
                    _chat_events_append(session_id, role="assistant", content=reply, source="local_action", ts=time.time())
                if self.path == "/api/chat/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    if (not _is_voice_control_command(message)) and (not bool(local_action.get("no_auto_tts"))):
                        _maybe_speak_reply(reply, allowed_tools)
                    event = {"token": reply}
                    if isinstance(local_action.get("reader"), dict):
                        event["reader"] = local_action.get("reader")
                    out = json.dumps(event, ensure_ascii=False).encode("utf-8")
                    try:
                        self.wfile.write(b"data: " + out + b"\n\n")
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    self.close_connection = True
                    return

                if (not _is_voice_control_command(message)) and (not bool(local_action.get("no_auto_tts"))):
                    _maybe_speak_reply(reply, allowed_tools)
                self._json(200, local_action)
                return

            messages = self._build_messages(message, history, mode, allowed_tools_for_prompt, attachments)
            q = web_search.extract_web_search_query(message)
            if q and ("web_search" in allowed_tools):
                ok_g, gd = _guardrail_check(
                    session_id,
                    "web_search",
                    {"action": "search", "query": q[:500], "site": ""},
                )
                if not ok_g:
                    blocked = _guardrail_block_reply("web_search", gd)
                    if self.path == "/api/chat/stream":
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        out = json.dumps({"token": blocked}, ensure_ascii=False).encode("utf-8")
                        try:
                            self.wfile.write(b"data: " + out + b"\n\n")
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()
                        except BrokenPipeError:
                            return
                        self.close_connection = True
                        return
                    self._json(200, {"reply": blocked})
                    return
                sp = web_search.searxng_search(q)
                if not sp.get("ok"):
                    err = str(sp.get("error", "web_search_failed"))
                    if self.path == "/api/chat/stream":
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        out = json.dumps({"token": f"No pude buscar en SearXNG local: {err}"}, ensure_ascii=False).encode("utf-8")
                        try:
                            self.wfile.write(b"data: " + out + b"\n\n")
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()
                        except BrokenPipeError:
                            return
                        self.close_connection = True
                        return
                    self._json(200, {"reply": f"No pude buscar en SearXNG local: {err}"})
                    return

                context = web_search.format_results_for_prompt(sp)
                messages = [
                    messages[0],
                    {
                        "role": "system",
                        "content": (
                            "Se te proveen resultados de busqueda web desde SearXNG local. "
                            "Usalos como base. Si no alcanza para responder, deci que falta. "
                            "No intentes usar herramientas de busqueda externas. "
                            "Cita fuentes mencionando el numero de resultado (1,2,3...).\n\n" + context
                        ),
                    },
                ] + messages[1:]

            if self.path == "/api/chat/stream":
                # Robust pseudo-stream: avoids hanging when upstream SSE behavior
                # changes and still gives progressive UX.
                req_payload = {
                    "model": routed_model,
                    "messages": messages,
                    "temperature": 0.2,
                }
                response_data = self._call_model_backend(resolved_backend, req_payload)
                full = _extract_reply_text(response_data) or ""
                if not full.strip():
                    full = (
                        "No recibí texto del modelo en esta vuelta. "
                        "Reformulá en un paso más concreto (por ejemplo: "
                        "'buscá X en YouTube' o 'abrí Y')."
                    )
                merged = []
                if isinstance(history, list):
                    for item in history[-80:]:
                        if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                            merged.append({"role": item["role"], "content": item["content"]})
                merged.append({"role": "user", "content": message})
                merged.append({"role": "assistant", "content": full})
                _save_history(session_id, merged, model=model, backend=resolved_backend)
                if record_chat_events:
                    _chat_events_append(
                        session_id,
                        role="user",
                        content=message,
                        source=user_msg_source,
                        ts=voice_item_ts if is_voice_origin else time.time(),
                    )
                    _chat_events_append(session_id, role="assistant", content=full, source="model", ts=time.time())
                _maybe_speak_reply(full, allowed_tools)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                step = 18
                for i in range(0, len(full), step):
                    token = full[i:i + step]
                    out = json.dumps({"token": token}, ensure_ascii=False).encode("utf-8")
                    try:
                        self.wfile.write(b"data: " + out + b"\n\n")
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)
                try:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except BrokenPipeError:
                    return
                self.close_connection = True
                return

            req_payload = {
                "model": routed_model,
                "messages": messages,
                "temperature": 0.2,
            }
            response_data = self._call_model_backend(resolved_backend, req_payload)
            reply = _extract_reply_text(response_data)
            if not isinstance(reply, str) or not reply.strip():
                reply = (
                    "No recibí texto del modelo en esta vuelta. "
                    "Reformulá en un paso más concreto (por ejemplo: "
                    "'buscá X en YouTube' o 'abrí Y')."
                )
            _maybe_speak_reply(reply, allowed_tools)

            # Persist merged history server-side as fallback.
            merged = []
            if isinstance(history, list):
                for item in history[-80:]:
                    if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                        merged.append({"role": item["role"], "content": item["content"]})
            merged.append({"role": "user", "content": message})
            merged.append({"role": "assistant", "content": reply})
            _save_history(session_id, merged, model=model, backend=resolved_backend)
            if record_chat_events:
                _chat_events_append(
                    session_id,
                    role="user",
                    content=message,
                    source=user_msg_source,
                    ts=voice_item_ts if is_voice_origin else time.time(),
                )
                _chat_events_append(session_id, role="assistant", content=reply, source="model", ts=time.time())

            self._json(
                200,
                {
                    "reply": reply,
                    "raw": response_data,
                    "model": model,
                    "model_backend": resolved_backend,
                    "chat_seq": int(_chat_events_poll(session_id, after_seq=0, limit=1).get("seq", 0) or 0),
                },
            )
        except _ModelSelectionError as e:
            self._json(400, e.as_payload())
        except _BackendCallError as e:
            if e.code == "MISSING_MODEL":
                _model_catalog(force_refresh=True)
            self._json(e.status, e.as_payload())
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            self._json(e.code, {"error": f"Gateway HTTP {e.code}", "detail": detail})
        except URLError as e:
            self._json(502, {"error": "Cannot reach OpenClaw gateway", "detail": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        return


def main():
    global _DIRECT_CHAT_HTTP_HOST, _DIRECT_CHAT_HTTP_PORT
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--gateway-port", type=int, default=18789)
    args = parser.parse_args()

    _DIRECT_CHAT_HTTP_HOST = str(args.host or "127.0.0.1")
    _DIRECT_CHAT_HTTP_PORT = int(args.port or 0)
    token = load_gateway_token()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.gateway_token = token
    httpd.gateway_port = args.gateway_port
    try:
        boot_state = _load_voice_state()
        _sync_stt_with_voice(enabled=bool(boot_state.get("enabled", False)), session_id="")
    except Exception:
        pass
    print(f"Direct chat ready: http://{args.host}:{args.port}")
    print(f"Target gateway: http://127.0.0.1:{args.gateway_port}/v1/chat/completions")
    httpd.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
