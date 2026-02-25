import json
import logging
import os
import string
import subprocess
import tempfile
import unicodedata
import wave

import numpy as np
import requests
import sounddevice as sd
import webrtcvad

# Configuracion (Rescatada del Legacy)
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"  # Webrtcvad necesita int16 puro
VAD_AGGRESSIVENESS = 3  # 0-3 (3 es el mas estricto para filtrar ruido)
FRAME_DURATION_MS = 30
WEBHOOK_URL = "http://localhost:5678/webhook/voice-input"

# Configuracion TTS
TTS_COMMAND = "/home/lucy-ubuntu/Lucy_Workspace/Proyecto-VSCode/.venv-lucy-voz/bin/mimic3"
TTS_VOICE = "es_ES/m-ailabs_low#karen_savage"

logging.basicConfig(level=logging.INFO, format='[lucy] %(message)s')


class VADAudio:
    """Clase envoltorio para el VAD legacy rescatado."""

    def __init__(self, aggressiveness=VAD_AGGRESSIVENESS, rate=SAMPLE_RATE):
        self.vad = webrtcvad.Vad(aggressiveness)
        self.rate = rate
        self.frame_duration_ms = FRAME_DURATION_MS
        # Calcular tamano del frame en bytes (PCM 16bit = 2 bytes)
        self.frame_size = int(rate * (self.frame_duration_ms / 1000.0) * 2)

    def is_speech(self, frame_bytes):
        try:
            return self.vad.is_speech(frame_bytes, self.rate)
        except Exception:
            return False


def record_until_silence(vad_wrapper, silence_seconds=1.5, max_seconds=15.0):
    """
    Logica original del Legacy: Graba hasta detectar silencio sostenido.
    """
    logging.info("Escuchando... (Hable ahora)")

    frames = []
    silence_threshold_frames = int(silence_seconds * 1000 / FRAME_DURATION_MS)
    max_frames = int(max_seconds * 1000 / FRAME_DURATION_MS)

    silence_counter = 0
    speech_detected = False

    # Abrir stream directo en int16 para webrtcvad
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=vad_wrapper.frame_size // 2,
    ) as stream:
        for _ in range(max_frames):
            data, overflow = stream.read(vad_wrapper.frame_size // 2)
            if overflow:
                continue

            frames.append(data)

            is_speech = vad_wrapper.is_speech(data)

            if is_speech:
                speech_detected = True
                silence_counter = 0
            else:
                if speech_detected:
                    silence_counter += 1

            if speech_detected and silence_counter >= silence_threshold_frames:
                logging.info("Silencio detectado. Procesando...")
                break

    if not speech_detected:
        return None

    return b"".join(frames)


def speak(text):
    """TTS limpio."""
    if not text:
        return
    try:
        logging.info(f"Hablando: {text}")
        process = subprocess.Popen(
            [TTS_COMMAND, "--voice", TTS_VOICE, "--stdout"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        wav_data, _ = process.communicate(input=text.encode("utf-8"))

        aplay = subprocess.Popen(["aplay", "-q"], stdin=subprocess.PIPE)
        aplay.communicate(input=wav_data)
    except Exception as exc:
        logging.error(f"Error TTS: {exc}")


def _load_asr_model():
    try:
        from faster_whisper import WhisperModel

        logging.info("Cargando Whisper (Small) via faster_whisper...")
        return ("faster_whisper", WhisperModel("small", device="cpu", compute_type="int8"))
    except Exception:
        import whisper

        logging.info("Cargando Whisper (Small) via whisper...")
        return ("whisper", whisper.load_model("small"))


def _transcribe(model_info, audio_path):
    backend, model = model_info
    if backend == "faster_whisper":
        segments, _ = model.transcribe(audio_path, language="es", beam_size=5)
        return " ".join([seg.text for seg in segments]).strip()
    result = model.transcribe(audio_path, language="es", fp16=False)
    return (result.get("text") or "").strip()


def main():
    vad = VADAudio()
    model_info = _load_asr_model()

    logging.info("Sistema LISTO. Presione Ctrl+C para salir.")

    try:
        while True:
            wav_bytes = record_until_silence(vad)

            if not wav_bytes:
                continue

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                with wave.open(tmp.name, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(wav_bytes)
                tmp_path = tmp.name

            text = _transcribe(model_info, tmp_path)
            os.unlink(tmp_path)

            if not text or len(text) < 2:
                continue

            text_lower = text.lower()
            normalized = unicodedata.normalize("NFKD", text_lower)
            normalized = normalized.encode("ascii", "ignore").decode("ascii")
            normalized = normalized.translate(str.maketrans("", "", string.punctuation)).strip()

            banned_keywords = [
                "amara.org",
                "subtitulos",
                "suscribete",
                "suip",
                "transcripcion",
                "gracias por ver",
            ]

            if any(keyword in text_lower for keyword in banned_keywords) or any(
                keyword in normalized for keyword in banned_keywords
            ):
                logging.info(f"Ignorando alucinacion de Whisper: '{text}'")
                continue

            logging.info(f"Oido: {text}")

            try:
                res = requests.post(WEBHOOK_URL, json={"text": text}, timeout=60)

                try:
                    payload = res.json()
                    respuesta_final = (
                        payload.get("response_text")
                        or payload.get("text")
                        or payload.get("output")
                    )
                    if not respuesta_final:
                        respuesta_final = str(payload)
                except json.JSONDecodeError:
                    respuesta_final = res.text

                if respuesta_final:
                    respuesta_final = (
                        respuesta_final.replace('"', "")
                        .replace("{", "")
                        .replace("}", "")
                    )
                    speak(respuesta_final)

            except Exception as exc:
                logging.error(f"Error conexion n8n: {exc}")
                speak("Error de conexion.")

    except KeyboardInterrupt:
        logging.info("Apagando.")


if __name__ == "__main__":
    main()
