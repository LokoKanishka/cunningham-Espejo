from __future__ import annotations

import audioop
import dataclasses
import queue
import re
import threading
import time
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
    max_silence_ms: int = 1000
    max_segment_s: float = 20.0
    rms_speech_threshold: float = 0.002
    rms_min_frames: int = 2

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

        def emit_runtime_diag(extra: Optional[dict] = None) -> None:
            vad_true_ratio = (float(vad_true_frames) / float(frames_seen)) if frames_seen > 0 else 0.0
            payload = {
                "kind": "stt_diag",
                "frames_seen": int(frames_seen),
                "last_audio_ts": float(last_audio_ts or 0.0),
                "rms_current": float(rms_current),
                "vad_active": bool(in_speech_now),
                "in_speech": bool(in_speech),
                "vad_frames": int(vad_frames),
                "vad_true_frames": int(vad_true_frames),
                "vad_true_ratio": float(vad_true_ratio),
                "last_segment_ms": int(last_segment_ms),
                "silence_ms": int(current_silence_ms),
            }
            if isinstance(extra, dict):
                payload.update(extra)
            emit_diag(payload)

        def reset_segment():
            nonlocal in_speech, buf, speech_start_mono, last_voice_mono, current_silence_ms
            in_speech = False
            buf = bytearray()
            speech_start_mono = 0.0
            last_voice_mono = 0.0
            current_silence_ms = 0

        def maybe_emit_segment(pcm16: bytes):
            nonlocal last_segment_ms
            # Segment length check
            dur_ms = int(len(pcm16) / 2 / target_rate * 1000)  # 2 bytes per sample mono
            last_segment_ms = int(max(0, dur_ms))
            if dur_ms < cfg.min_speech_ms:
                emit_runtime_diag({"kind": "stt_drop", "reason": "segment_too_short", "dur_ms": int(dur_ms)})
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
            nonlocal current_silence_ms
            if not frame_pcm16:
                return
            frames_seen += 1
            last_audio_ts = time.time()
            try:
                rms_current = float(audioop.rms(frame_pcm16, 2) / 32768.0)
            except Exception:
                rms_current = 0.0

            try:
                vad_true = bool(vad.is_speech(frame_pcm16, target_rate))
            except Exception:
                vad_true = False
            if vad_true:
                vad_true_frames += 1
                rms_consecutive = 0
            elif rms_current >= max(0.0005, float(cfg.rms_speech_threshold)):
                rms_consecutive += 1
            else:
                rms_consecutive = 0

            speech_like = bool(vad_true or (rms_consecutive >= max(1, int(cfg.rms_min_frames))))
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
                buf.extend(frame_pcm16)
                last_voice_mono = now
                if (now - speech_start_mono) > cfg.max_segment_s:
                    maybe_emit_segment(bytes(buf))
                    reset_segment()
            else:
                if not in_speech:
                    current_silence_ms = int(min(60000, current_silence_ms + cfg.frame_ms))
                    emit_runtime_diag()
                    return
                silence_ms = int((now - last_voice_mono) * 1000)
                current_silence_ms = silence_ms
                if silence_ms >= cfg.max_silence_ms:
                    maybe_emit_segment(bytes(buf))
                    reset_segment()
            emit_runtime_diag()

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
                        frame_buffer = bytearray()
                        rms_consecutive = 0
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
