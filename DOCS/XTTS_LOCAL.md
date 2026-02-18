# XTTS Local (Coqui) para Molbot Direct Chat

Instalacion:

```bash
scripts/install_xtts_local.sh
```

Arranque recomendado:

```bash
export DIRECT_CHAT_PYTHON="$HOME/.openclaw/venvs/xtts/bin/python"
export COQUI_TOS_AGREED=1
scripts/openclaw_direct_chat.sh 8787
```

Uso en UI:
- Activar checkbox `voz`.
- Comandos por chat:
  - `voz on`
  - `voz off`
  - `voz test`

Personalizacion (opcional):
- `DIRECT_CHAT_TTS_SPEAKER`: speaker builtin (default `Ana Florence`).
- `DIRECT_CHAT_TTS_SPEAKER_WAV`: ruta a `.wav` de referencia (clonacion).
- `DIRECT_CHAT_TTS_MODEL`: default `tts_models/multilingual/multi-dataset/xtts_v2`.

Notas:
- La primera carga de XTTS es pesada; luego queda en memoria.
- Reproductor local: `ffplay` (instalado en Ubuntu standard).
