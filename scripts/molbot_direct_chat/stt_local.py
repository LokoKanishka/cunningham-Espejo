from __future__ import annotations

import dataclasses
import queue
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
    vad_mode: int = 2  # 0..3 (more aggressive -> fewer false positives)

    # Segmentation
    min_speech_ms: int = 350
    max_silence_ms: int = 900
    max_segment_s: float = 20.0

    # Transcription
    language: str = "es"
    model: str = "small"          # faster-whisper model name/path
    fw_device: str = "cpu"        # "cpu" or "cuda"
    fw_compute_type: str = "int8" # cpu-friendly default; for cuda usually "float16"
    initial_prompt: str = ""

    # Filtering
    min_chars: int = 3


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


def list_input_devices() -> list[dict]:
    """Utility for debugging. Returns a list of input-capable devices (best-effort)."""
    sd = _lazy_import_sounddevice()
    out = []
    try:
        devices = sd.query_devices()
    except Exception:
        return out
    for i, d in enumerate(devices):
        try:
            if int(d.get("max_input_channels", 0)) > 0:
                out.append({"index": i, "name": str(d.get("name", "")), "max_input_channels": int(d.get("max_input_channels", 0))})
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
    ):
        self.cfg = cfg
        self.out_queue = out_queue
        self.should_listen = should_listen
        self.log = logger

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
        try:
            sd = _lazy_import_sounddevice()
            webrtcvad = _lazy_import_webrtcvad()
        except Exception as e:
            self.last_error = str(e)
            self.log(f"[stt] deps error: {self.last_error}")
            return

        cfg = self.cfg
        vad = webrtcvad.Vad(int(cfg.vad_mode))

        frame_samples = int(cfg.sample_rate * cfg.frame_ms / 1000)
        if frame_samples <= 0:
            self.last_error = "invalid_frame_samples"
            return

        # We'll use RawInputStream to get PCM16 bytes directly.
        try:
            stream = sd.RawInputStream(
                samplerate=cfg.sample_rate,
                channels=cfg.channels,
                dtype="int16",
                blocksize=frame_samples,
                device=cfg.device,
            )
        except Exception as e:
            self.last_error = f"sounddevice_stream_open_failed:{e}"
            self.log(f"[stt] {self.last_error}")
            return

        in_speech = False
        buf = bytearray()
        speech_start_mono = 0.0
        last_voice_mono = 0.0

        def reset_segment():
            nonlocal in_speech, buf, speech_start_mono, last_voice_mono
            in_speech = False
            buf = bytearray()
            speech_start_mono = 0.0
            last_voice_mono = 0.0

        def maybe_emit_segment(pcm16: bytes):
            # Segment length check
            dur_ms = int(len(pcm16) / 2 / cfg.sample_rate * 1000)  # 2 bytes per sample mono
            if dur_ms < cfg.min_speech_ms:
                return
            try:
                engine = self._ensure_engine()
                text = engine.transcribe(pcm16)
            except Exception as e:
                self.last_error = f"transcribe_failed:{e}"
                self.log(f"[stt] {self.last_error}")
                return

            text = (text or "").strip()
            if len(text) < cfg.min_chars:
                return

            try:
                self.out_queue.put_nowait({"text": text, "ts": time.time()})
            except Exception:
                # If queue is full or consumer is slow, we drop silently to avoid blocking audio thread.
                return

        try:
            with stream:
                while not self._stop.is_set():
                    try:
                        data, overflowed = stream.read(frame_samples)
                        if overflowed:
                            # Keep going; overflow just means missed audio
                            pass
                    except Exception as e:
                        self.last_error = f"sounddevice_read_failed:{e}"
                        self.log(f"[stt] {self.last_error}")
                        break

                    if not self.should_listen():
                        # Anti-eco gating: drop everything and reset segments.
                        reset_segment()
                        time.sleep(0.02)
                        continue

                    if not data:
                        continue

                    # webrtcvad expects bytes of 16-bit PCM, mono
                    try:
                        is_speech = bool(vad.is_speech(data, cfg.sample_rate))
                    except Exception:
                        # On any VAD error, treat as non-speech to stay safe.
                        is_speech = False

                    now = time.monotonic()
                    if is_speech:
                        if not in_speech:
                            in_speech = True
                            speech_start_mono = now
                            last_voice_mono = now
                            buf = bytearray()
                        buf.extend(data)
                        last_voice_mono = now
                        # Hard cap segment length
                        if (now - speech_start_mono) > cfg.max_segment_s:
                            maybe_emit_segment(bytes(buf))
                            reset_segment()
                    else:
                        if not in_speech:
                            continue
                        # In speech: check silence duration
                        silence_ms = int((now - last_voice_mono) * 1000)
                        if silence_ms >= cfg.max_silence_ms:
                            maybe_emit_segment(bytes(buf))
                            reset_segment()
        finally:
            reset_segment()
