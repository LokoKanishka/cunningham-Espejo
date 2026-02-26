from __future__ import annotations

import audioop
import dataclasses
import queue
import re
import threading
import time
from collections import deque
from typing import Callable, Optional


class DependencyError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class STTConfig:
    # Audio
    sample_rate: int = 16000
    channels: int = 1
    device: Optional[int | str] = None  # sounddevice device index or name
    frame_ms: int = 30  # webrtcvad supports 10/20/30ms
    vad_mode: int = 1  # 0..3 (more aggressive -> fewer false positives)

    # Segmentation
    min_speech_ms: int = 220
    chat_min_speech_ms: int = 180
    max_silence_ms: int = 350
    max_segment_s: float = 2.0
    start_preroll_ms: int = 260
    rms_speech_threshold: float = 0.002
    rms_min_frames: int = 2
    segment_hysteresis_off_ratio: float = 0.65
    segment_hangover_ms: int = 250
    chat_mode: bool = False
    preamp_gain: float = 1.0
    agc_enabled: bool = False
    agc_target_rms: float = 0.06
    agc_max_gain: float = 6.0
    agc_attack: float = 0.35
    agc_release: float = 0.08

    # Transcription
    language: str = "es"
    model: str = "small"          # faster-whisper model name/path
    fw_device: str = "cpu"        # "cpu" or "cuda"
    fw_compute_type: str = "int8" # cpu-friendly default; for cuda usually "float16"
    initial_prompt: str = ""

    # Filtering
    min_chars: int = 3


ALLOW_SHORT = {
    "hola",
    "ok",
    "si",
    "sí",
    "no",
    "para",
    "pará",
    "pausa",
    "pauza",
    "posa",
    "poza",
    "detenete",
    "continuar",
    "eh",
    "ey",
    "aca",
    "acá",
    "dale",
    "listo",
    "bueno",
}


def _lazy_import_sounddevice():
    try:
        import sounddevice as sd  # type: ignore
    except Exception as e:
        raise DependencyError(f"sounddevice_unavailable:{e}")
    return sd


def _lazy_import_webrtcvad():
    try:
        import webrtcvad  # type: ignore
    except Exception as e:
        raise DependencyError(f"webrtcvad_unavailable:{e}")
    return webrtcvad


def _lazy_import_numpy():
    try:
        import numpy as np  # type: ignore
    except Exception as e:
        raise DependencyError(f"numpy_unavailable:{e}")
    return np


def _lazy_import_faster_whisper():
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:
        raise DependencyError(f"faster_whisper_unavailable:{e}")
    return WhisperModel


def _pcm16_to_float32(pcm: bytes):
    np = _lazy_import_numpy()
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if a.size == 0:
        return a
    a /= 32768.0
    return a


class FasterWhisperEngine:
    def __init__(self, cfg: STTConfig):
        WhisperModel = _lazy_import_faster_whisper()
        self.cfg = cfg
        # Model load can be heavy; caller should instantiate once per process.
        self.model = WhisperModel(cfg.model, device=cfg.fw_device, compute_type=cfg.fw_compute_type)

    def transcribe(self, pcm16: bytes) -> str:
        audio = _pcm16_to_float32(pcm16)
        if getattr(audio, "size", 0) == 0:
            return ""
        segments, _info = self.model.transcribe(
            audio,
            language=self.cfg.language or None,
            beam_size=1,
            vad_filter=False,  # we already do VAD
            initial_prompt=(self.cfg.initial_prompt or None),
        )
        parts = []
        for seg in segments:
            t = (getattr(seg, "text", "") or "").strip()
            if t:
                parts.append(t)
        return " ".join(parts).strip()


def _normalize_transcript_text(text: str) -> str:
    raw = str(text or "").replace("\r", " ").replace("\n", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    # Strip edge punctuation/noise but preserve inner punctuation naturally spoken.
    return raw.strip(" \t,.;:!?-_#|/\\`~^")


def _filter_transcript_text(text: str, min_chars: int = 3) -> tuple[str, str]:
    normalized = _normalize_transcript_text(text)
    clean = normalized.strip(" .,!¿?¡").lower()
    if clean in ALLOW_SHORT:
        return normalized, ""

    if len(normalized) < max(1, int(min_chars)):
        return "", "text_too_short"

    lowered = normalized.lower()
    letters = sum(1 for ch in lowered if ch.isalpha())
    digits = sum(1 for ch in lowered if ch.isdigit())
    symbols = sum(1 for ch in lowered if (not ch.isalnum()) and (not ch.isspace()))
    if letters <= 0:
        return "", "text_no_letters"
    if letters <= 2 and (digits + symbols) >= (letters + 2):
        return "", "text_noise_mostly_non_letters"

    tokens = [re.sub(r"[^a-z0-9]+", "", tok) for tok in lowered.split()]
    tokens = [tok for tok in tokens if tok]
    if not tokens:
        return "", "text_no_tokens"

    one_char_tokens = sum(1 for tok in tokens if len(tok) <= 1)
    if len(tokens) >= 3 and one_char_tokens >= len(tokens):
        return "", "text_noise_single_chars"

    if symbols >= 4 and symbols > letters:
        return "", "text_noise_symbols"

    return normalized, ""


def _effective_segment_threshold(config_threshold: float, noise_samples: list[float]) -> float:
    cfg_thr = max(0.0005, float(config_threshold or 0.0))
    clean_samples = [max(0.0, float(v)) for v in noise_samples if isinstance(v, (int, float))]
    if clean_samples:
        ordered = sorted(clean_samples)
        noise_floor = float(ordered[len(ordered) // 2])
    else:
        noise_floor = 0.0
    # Guardrail: avoid near-zero thresholds that keep speech_like latched forever.
    return max(0.004, cfg_thr, noise_floor * 2.8)


def _apply_preamp_agc_frame(
    pcm16: bytes,
    *,
    preamp_gain: float,
    agc_enabled: bool,
    agc_target_rms: float,
    agc_max_gain: float,
    agc_attack: float,
    agc_release: float,
    agc_gain_current: float,
) -> tuple[bytes, float, float, float, float]:
    if not pcm16:
        return pcm16, float(max(0.05, preamp_gain)), float(max(0.1, agc_gain_current)), 0.0, 0.0
    base_gain = max(0.05, float(preamp_gain or 1.0))
    try:
        raw_rms = float(audioop.rms(pcm16, 2) / 32768.0)
    except Exception:
        raw_rms = 0.0
    agc_gain = max(0.1, float(agc_gain_current or 1.0))
    if bool(agc_enabled):
        target = max(0.01, min(0.30, float(agc_target_rms or 0.06)))
        max_gain = max(1.0, min(24.0, float(agc_max_gain or 6.0)))
        desired = target / max(0.0001, raw_rms)
        desired = max(0.25, min(max_gain, float(desired)))
        attack = max(0.01, min(1.0, float(agc_attack or 0.35)))
        release = max(0.01, min(1.0, float(agc_release or 0.08)))
        rate = attack if desired >= agc_gain else release
        agc_gain = agc_gain + ((desired - agc_gain) * rate)
        agc_gain = max(0.1, min(max_gain, float(agc_gain)))
    total_gain = max(0.05, min(24.0, base_gain * (agc_gain if bool(agc_enabled) else 1.0)))
    try:
        out = audioop.mul(pcm16, 2, total_gain)
    except Exception:
        out = pcm16
    try:
        out_rms = float(audioop.rms(out, 2) / 32768.0)
    except Exception:
        out_rms = raw_rms
    return out, float(base_gain), float(agc_gain), float(total_gain), float(out_rms)


def _effective_min_segment_ms(cfg: STTConfig) -> int:
    base_ms = max(80, int(cfg.min_speech_ms))
    if not bool(cfg.chat_mode):
        return base_ms
    chat_ms = max(80, int(cfg.chat_min_speech_ms))
    return min(base_ms, chat_ms)


def _segment_speech_like_state(
    *,
    vad_true: bool,
    rms_current: float,
    threshold_on: float,
    in_speech: bool,
    rms_consecutive: int,
    rms_min_frames: int,
    hangover_left_ms: int,
    hangover_ms: int,
    frame_ms: int,
    off_ratio: float,
) -> tuple[bool, int, int, float]:
    thr_on = max(0.0005, float(threshold_on or 0.0))
    ratio = max(0.10, min(0.95, float(off_ratio or 0.65)))
    thr_off = max(0.0003, thr_on * ratio)
    if rms_current >= thr_on:
        rms_consecutive = min(1000000, int(rms_consecutive) + 1)
    else:
        rms_consecutive = 0
    raw_speech_like = bool((vad_true and rms_current >= thr_on) or (rms_consecutive >= max(1, int(rms_min_frames))))
    if raw_speech_like:
        return True, rms_consecutive, max(0, int(hangover_ms)), thr_off
    if in_speech:
        if rms_current >= thr_off:
            return True, rms_consecutive, max(0, int(hangover_left_ms)), thr_off
        if int(hangover_left_ms) > 0:
            dec_ms = max(1, int(frame_ms))
            return True, rms_consecutive, max(0, int(hangover_left_ms) - dec_ms), thr_off
    return False, rms_consecutive, 0, thr_off


def _simulate_segments_for_test(
    rms_values: list[float],
    *,
    cfg: STTConfig,
    vad_values: Optional[list[bool]] = None,
) -> tuple[list[int], list[str]]:
    if not isinstance(rms_values, list):
        return [], []
    vad_seq = list(vad_values) if isinstance(vad_values, list) else []
    seg_threshold = _effective_segment_threshold(float(cfg.rms_speech_threshold), [])
    seg_ms = 0
    silence_ms = 0
    in_speech = False
    rms_consecutive = 0
    hangover_left_ms = 0
    emitted: list[int] = []
    dropped: list[str] = []
    min_segment_ms = _effective_min_segment_ms(cfg)
    max_segment_ms = int(max(200, int(round(float(cfg.max_segment_s) * 1000.0))))
    for idx, rms in enumerate(rms_values):
        try:
            rms_current = max(0.0, float(rms))
        except Exception:
            rms_current = 0.0
        vad_true = bool(vad_seq[idx]) if idx < len(vad_seq) else bool(rms_current >= seg_threshold)
        speech_like, rms_consecutive, hangover_left_ms, _thr_off = _segment_speech_like_state(
            vad_true=vad_true,
            rms_current=rms_current,
            threshold_on=seg_threshold,
            in_speech=in_speech,
            rms_consecutive=rms_consecutive,
            rms_min_frames=int(cfg.rms_min_frames),
            hangover_left_ms=hangover_left_ms,
            hangover_ms=int(cfg.segment_hangover_ms),
            frame_ms=int(cfg.frame_ms),
            off_ratio=float(cfg.segment_hysteresis_off_ratio),
        )
        if speech_like:
            if not in_speech:
                in_speech = True
                seg_ms = 0
                silence_ms = 0
            seg_ms += int(cfg.frame_ms)
            if seg_ms >= max_segment_ms:
                if seg_ms < min_segment_ms:
                    dropped.append("segment_too_short")
                else:
                    emitted.append(seg_ms)
                in_speech = False
                seg_ms = 0
                silence_ms = 0
                hangover_left_ms = 0
            continue
        if not in_speech:
            continue
        silence_ms += int(cfg.frame_ms)
        if silence_ms >= int(cfg.max_silence_ms):
            if seg_ms < min_segment_ms:
                dropped.append("segment_too_short")
            else:
                emitted.append(seg_ms)
            in_speech = False
            seg_ms = 0
            silence_ms = 0
            hangover_left_ms = 0
    if in_speech and seg_ms > 0:
        if seg_ms < min_segment_ms:
            dropped.append("segment_too_short")
        else:
            emitted.append(seg_ms)
    return emitted, dropped


def list_input_devices() -> list[dict]:
    """Utility for debugging. Returns a list of input-capable devices (best-effort)."""
    sd = _lazy_import_sounddevice()
    out = []
    default_input = None
    try:
        default_pair = getattr(sd, "default", None)
        if default_pair is not None:
            default_device = getattr(default_pair, "device", None)
            if isinstance(default_device, (list, tuple)) and len(default_device) >= 1:
                default_input = int(default_device[0])
            elif isinstance(default_device, int):
                default_input = int(default_device)
    except Exception:
        default_input = None
    try:
        devices = sd.query_devices()
    except Exception:
        return out
    for i, d in enumerate(devices):
        try:
            if int(d.get("max_input_channels", 0)) > 0:
                out.append(
                    {
                        "index": i,
                        "name": str(d.get("name", "")),
                        "max_input_channels": int(d.get("max_input_channels", 0)),
                        "default": bool(default_input is not None and i == default_input),
                    }
                )
        except Exception:
            continue
    return out


class STTWorker:
    """
    Captura mic -> VAD (webrtcvad) -> segmento PCM16 -> transcribe (faster-whisper) -> queue de textos.

    Diseño:
    - Imports lazy para no romper DC si no están instaladas dependencias.
    - 'should_listen' permite gating (anti-eco): cuando False, descarta buffers y no emite texto.
    """
    def __init__(
        self,
        cfg: STTConfig,
        out_queue: "queue.Queue[dict]",
        *,
        should_listen: Callable[[], bool] = lambda: True,
        logger: Callable[[str], None] = lambda msg: None,
        telemetry: Callable[[dict], None] = lambda _evt: None,
    ):
        self.cfg = cfg
        self.out_queue = out_queue
        self.should_listen = should_listen
        self.log = logger
        self.telemetry = telemetry

        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None

        self._engine: Optional[FasterWhisperEngine] = None
        self.last_error: str = ""

    def start(self) -> None:
        if self._th and self._th.is_alive():
            return
        self._stop.clear()
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        th = self._th
        if th:
            th.join(timeout=timeout)

    def is_running(self) -> bool:
        return bool(self._th and self._th.is_alive())

    def _ensure_engine(self) -> FasterWhisperEngine:
        if self._engine is None:
            self._engine = FasterWhisperEngine(self.cfg)
        return self._engine

    def _run(self) -> None:
        def emit_diag(payload: dict) -> None:
            try:
                self.telemetry(payload)
            except Exception:
                return

        try:
            sd = _lazy_import_sounddevice()
            webrtcvad = _lazy_import_webrtcvad()
        except Exception as e:
            self.last_error = str(e)
            self.log(f"[stt] deps error: {self.last_error}")
            emit_diag({"kind": "stt_error", "detail": self.last_error})
            return

        cfg = self.cfg
        target_rate = int(cfg.sample_rate or 16000)
        if target_rate not in (8000, 16000, 32000, 48000):
            target_rate = 16000
            emit_diag({"kind": "stt_warn", "detail": f"unsupported_vad_rate_fallback:{cfg.sample_rate}->{target_rate}"})
        vad = webrtcvad.Vad(int(max(0, min(3, cfg.vad_mode))))

        frame_samples_target = int(target_rate * cfg.frame_ms / 1000)
        frame_bytes_target = int(frame_samples_target * 2)  # PCM16 mono
        if frame_samples_target <= 0 or frame_bytes_target <= 0:
            self.last_error = "invalid_frame_samples"
            emit_diag({"kind": "stt_error", "detail": self.last_error})
            return

        input_channels = 1
        input_rate = target_rate
        frame_samples_in = frame_samples_target

        def _device_default_rate() -> int | None:
            try:
                info = sd.query_devices(cfg.device, kind="input")
            except Exception:
                try:
                    info = sd.query_devices(cfg.device)
                except Exception:
                    return None
            try:
                rate = int(round(float(info.get("default_samplerate", 0.0) or 0.0)))
            except Exception:
                return None
            return rate if rate >= 8000 else None

        def _open_stream(rate: int):
            samples = int(rate * cfg.frame_ms / 1000)
            if samples <= 0:
                raise RuntimeError(f"invalid_input_frame_samples:{samples}")
            st = sd.RawInputStream(
                samplerate=rate,
                channels=input_channels,
                dtype="int16",
                blocksize=samples,
                device=cfg.device,
            )
            return st, samples

        stream = None
        first_error = ""
        sample_rate_fallback = False
        try:
            stream, frame_samples_in = _open_stream(target_rate)
            input_rate = target_rate
        except Exception as e:
            first_error = str(e)
            native_rate = _device_default_rate()
            if native_rate is None:
                self.last_error = f"sounddevice_stream_open_failed:{first_error}"
                self.log(f"[stt] {self.last_error}")
                emit_diag({"kind": "stt_error", "detail": self.last_error})
                return
            try:
                stream, frame_samples_in = _open_stream(native_rate)
                input_rate = int(native_rate)
                sample_rate_fallback = True
                emit_diag(
                    {
                        "kind": "stt_warn",
                        "detail": f"stream_rate_fallback:{target_rate}->{input_rate}",
                    }
                )
            except Exception as e2:
                self.last_error = f"sounddevice_stream_open_failed:{first_error};fallback:{e2}"
                self.log(f"[stt] {self.last_error}")
                emit_diag({"kind": "stt_error", "detail": self.last_error})
                return

        in_speech = False
        buf = bytearray()
        speech_start_mono = 0.0
        last_voice_mono = 0.0
        frames_seen = 0
        vad_frames = 0
        vad_true_frames = 0
        rms_current = 0.0
        last_audio_ts = 0.0
        in_speech_now = False
        last_segment_ms = 0
        current_silence_ms = 0
        resample_state = None
        frame_buffer = bytearray()
        rms_consecutive = 0
        noise_rms_samples: list[float] = []
        noise_window_max = max(10, int(1200 / max(10, int(cfg.frame_ms))))
        preroll_ms = max(0, min(1000, int(getattr(cfg, "start_preroll_ms", 0) or 0)))
        preroll_frames_cap = max(0, int(round(float(preroll_ms) / max(10.0, float(cfg.frame_ms)))))
        preroll_frames: deque[bytes] | None = deque(maxlen=preroll_frames_cap) if preroll_frames_cap > 0 else None
        noise_floor_current = 0.0
        effective_seg_thr_current = max(0.006, float(cfg.rms_speech_threshold))
        segment_thr_off_current = max(0.0003, effective_seg_thr_current * max(0.10, min(0.95, float(cfg.segment_hysteresis_off_ratio))))
        effective_min_segment_ms = _effective_min_segment_ms(cfg)
        hangover_left_ms = 0
        preamp_gain_current = max(0.05, float(cfg.preamp_gain or 1.0))
        agc_gain_current = 1.0
        input_gain_total_current = preamp_gain_current
        raw_rms_current = 0.0
        rms_after_gain_current = 0.0

        def emit_runtime_diag(extra: Optional[dict] = None) -> None:
            vad_true_ratio = (float(vad_true_frames) / float(frames_seen)) if frames_seen > 0 else 0.0
            speech_state = f"in_speech={1 if in_speech else 0},hangover_ms={int(max(0, hangover_left_ms))}"
            payload = {
                "kind": "stt_diag",
                "frames_seen": int(frames_seen),
                "last_audio_ts": float(last_audio_ts or 0.0),
                "raw_rms_current": float(raw_rms_current),
                "rms_current": float(rms_current),
                "rms_after_gain": float(rms_after_gain_current),
                "vad_active": bool(in_speech_now),
                "in_speech": bool(in_speech),
                "vad_frames": int(vad_frames),
                "vad_true_frames": int(vad_true_frames),
                "vad_true_ratio": float(vad_true_ratio),
                "last_segment_ms": int(last_segment_ms),
                "silence_ms": int(current_silence_ms),
                "segment_threshold": float(effective_seg_thr_current),
                "effective_seg_thr": float(effective_seg_thr_current),
                "segment_thr_on": float(effective_seg_thr_current),
                "segment_thr_off": float(segment_thr_off_current),
                "min_segment_ms": int(effective_min_segment_ms),
                "start_preroll_ms": int(preroll_ms),
                "speech_hangover_ms": int(max(0, hangover_left_ms)),
                "speech_state": speech_state,
                "stt_preamp_gain": float(preamp_gain_current),
                "stt_agc_enabled": bool(cfg.agc_enabled),
                "stt_agc_gain_current": float(agc_gain_current),
                "stt_input_gain_total": float(input_gain_total_current),
                "noise_floor": float(noise_floor_current),
            }
            if isinstance(extra, dict):
                payload.update(extra)
            emit_diag(payload)

        def reset_segment():
            nonlocal in_speech, buf, speech_start_mono, last_voice_mono, current_silence_ms, hangover_left_ms
            in_speech = False
            buf = bytearray()
            speech_start_mono = 0.0
            last_voice_mono = 0.0
            current_silence_ms = 0
            hangover_left_ms = 0

        def remember_preroll(frame_pcm16: bytes) -> None:
            if preroll_frames is None or (not frame_pcm16):
                return
            try:
                preroll_frames.append(frame_pcm16)
            except Exception:
                return

        def maybe_emit_segment(pcm16: bytes):
            nonlocal last_segment_ms
            # Segment length check
            dur_ms = int(len(pcm16) / 2 / target_rate * 1000)  # 2 bytes per sample mono
            last_segment_ms = int(max(0, dur_ms))
            if dur_ms < effective_min_segment_ms:
                emit_runtime_diag(
                    {
                        "kind": "stt_drop",
                        "reason": "segment_too_short",
                        "dur_ms": int(dur_ms),
                        "min_segment_ms": int(effective_min_segment_ms),
                    }
                )
                return
            try:
                engine = self._ensure_engine()
                raw_text = engine.transcribe(pcm16)
            except Exception as e:
                self.last_error = f"transcribe_failed:{e}"
                self.log(f"[stt] {self.last_error}")
                emit_runtime_diag({"kind": "stt_error", "detail": self.last_error})
                return

            text, drop_reason = _filter_transcript_text(raw_text, min_chars=int(cfg.min_chars))
            if drop_reason:
                emit_runtime_diag(
                    {
                        "kind": "stt_drop",
                        "reason": str(drop_reason),
                        "chars": int(len(str(raw_text or ""))),
                    }
                )
                return

            try:
                self.out_queue.put_nowait({"text": text, "ts": time.time()})
                emit_runtime_diag({"kind": "stt_emit", "chars": int(len(text))})
            except Exception:
                # If queue is full or consumer is slow, we drop silently to avoid blocking audio thread.
                emit_runtime_diag({"kind": "stt_drop", "reason": "queue_full"})
                return

        def process_frame(frame_pcm16: bytes) -> None:
            nonlocal frames_seen, vad_frames, vad_true_frames, rms_current, last_audio_ts
            nonlocal in_speech_now, rms_consecutive, in_speech, speech_start_mono, last_voice_mono, buf
            nonlocal current_silence_ms, noise_floor_current, effective_seg_thr_current, segment_thr_off_current
            nonlocal hangover_left_ms
            nonlocal preamp_gain_current, agc_gain_current, input_gain_total_current, raw_rms_current, rms_after_gain_current
            if not frame_pcm16:
                return
            raw_frame_pcm16 = frame_pcm16
            frames_seen += 1
            last_audio_ts = time.time()
            frame_pcm16, preamp_gain_current, agc_gain_current, input_gain_total_current, rms_after_gain = _apply_preamp_agc_frame(
                raw_frame_pcm16,
                preamp_gain=float(cfg.preamp_gain),
                agc_enabled=bool(cfg.agc_enabled),
                agc_target_rms=float(cfg.agc_target_rms),
                agc_max_gain=float(cfg.agc_max_gain),
                agc_attack=float(cfg.agc_attack),
                agc_release=float(cfg.agc_release),
                agc_gain_current=float(agc_gain_current),
            )
            try:
                raw_rms_current = float(audioop.rms(raw_frame_pcm16, 2) / 32768.0)
            except Exception:
                raw_rms_current = 0.0
            try:
                rms_after_gain_current = float(rms_after_gain)
            except Exception:
                rms_after_gain_current = raw_rms_current
            # Gate VAD/segmentation with raw mic level so AGC/preamp does not
            # inflate room noise into permanent speech.
            rms_current = float(raw_rms_current)

            try:
                vad_true = bool(vad.is_speech(raw_frame_pcm16, target_rate))
            except Exception:
                vad_true = False
            if not vad_true:
                noise_rms_samples.append(raw_rms_current)
                if len(noise_rms_samples) > noise_window_max:
                    del noise_rms_samples[: len(noise_rms_samples) - noise_window_max]
            if noise_rms_samples:
                ordered = sorted(noise_rms_samples)
                noise_floor_current = float(ordered[len(ordered) // 2])
            else:
                noise_floor_current = 0.0
            effective_seg_thr_current = _effective_segment_threshold(float(cfg.rms_speech_threshold), noise_rms_samples)
            if vad_true:
                vad_true_frames += 1

            # Treat VAD as advisory and avoid flicker by applying hysteresis + hangover.
            speech_like, rms_consecutive, hangover_left_ms, segment_thr_off_current = _segment_speech_like_state(
                vad_true=vad_true,
                rms_current=raw_rms_current,
                threshold_on=effective_seg_thr_current,
                in_speech=in_speech,
                rms_consecutive=rms_consecutive,
                rms_min_frames=int(cfg.rms_min_frames),
                hangover_left_ms=hangover_left_ms,
                hangover_ms=int(cfg.segment_hangover_ms),
                frame_ms=int(cfg.frame_ms),
                off_ratio=float(cfg.segment_hysteresis_off_ratio),
            )
            in_speech_now = speech_like

            now = time.monotonic()
            if speech_like:
                vad_frames += 1
                current_silence_ms = 0
                if not in_speech:
                    in_speech = True
                    speech_start_mono = now
                    last_voice_mono = now
                    buf = bytearray()
                    if preroll_frames:
                        for f in preroll_frames:
                            if f:
                                buf.extend(f)
                buf.extend(frame_pcm16)
                last_voice_mono = now
                if (now - speech_start_mono) > cfg.max_segment_s:
                    maybe_emit_segment(bytes(buf))
                    reset_segment()
            else:
                if not in_speech:
                    current_silence_ms = int(min(60000, current_silence_ms + cfg.frame_ms))
                    emit_runtime_diag()
                    remember_preroll(frame_pcm16)
                    return
                silence_ms = int((now - last_voice_mono) * 1000)
                current_silence_ms = silence_ms
                if silence_ms >= cfg.max_silence_ms:
                    maybe_emit_segment(bytes(buf))
                    reset_segment()
            emit_runtime_diag()
            remember_preroll(frame_pcm16)

        try:
            with stream:
                emit_runtime_diag(
                    {
                        "kind": "stt_started",
                        "device": str(cfg.device) if cfg.device is not None else "",
                        "sample_rate": int(target_rate),
                        "input_rate": int(input_rate),
                        "sample_rate_fallback": bool(sample_rate_fallback),
                        "frame_ms": int(cfg.frame_ms),
                    }
                )
                while not self._stop.is_set():
                    try:
                        data, overflowed = stream.read(frame_samples_in)
                        if overflowed:
                            # Keep going; overflow just means missed audio
                            emit_runtime_diag({"kind": "stt_drop", "reason": "overflowed"})
                    except Exception as e:
                        self.last_error = f"sounddevice_read_failed:{e}"
                        self.log(f"[stt] {self.last_error}")
                        emit_runtime_diag({"kind": "stt_error", "detail": self.last_error})
                        break

                    if not self.should_listen():
                        # Anti-eco gating: drop everything and reset segments.
                        emit_runtime_diag({"kind": "stt_drop", "reason": "should_listen_false"})
                        reset_segment()
                        if preroll_frames is not None:
                            preroll_frames.clear()
                        frame_buffer = bytearray()
                        rms_consecutive = 0
                        hangover_left_ms = 0
                        time.sleep(0.02)
                        continue

                    if not data:
                        continue

                    pcm = data
                    if input_rate != target_rate:
                        try:
                            pcm, resample_state = audioop.ratecv(data, 2, 1, input_rate, target_rate, resample_state)
                        except Exception as e:
                            emit_runtime_diag({"kind": "stt_drop", "reason": f"resample_failed:{e}"})
                            continue
                    if not pcm:
                        continue
                    frame_buffer.extend(pcm)
                    while len(frame_buffer) >= frame_bytes_target:
                        frame = bytes(frame_buffer[:frame_bytes_target])
                        del frame_buffer[:frame_bytes_target]
                        process_frame(frame)
                if in_speech and buf:
                    maybe_emit_segment(bytes(buf))
                    reset_segment()
                if (not in_speech_now) and int(vad_frames) <= 0 and int(frames_seen) > 0:
                    emit_runtime_diag({"kind": "stt_drop", "reason": "no_speech_detected"})
        finally:
            reset_segment()
            emit_runtime_diag({"kind": "stt_stopped"})
