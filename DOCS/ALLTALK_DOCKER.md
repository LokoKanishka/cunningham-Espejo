# AllTalk TTS por Docker

Migramos la voz de `Molbot Direct Chat` a **AllTalk TTS** en Docker.

## Stack de voz

- Compose: `apps/alltalk/compose.yaml`
- Base: `erew123/alltalk_tts:latest`
- Build local: `apps/alltalk/Dockerfile` (PyTorch/Torchaudio `2.7.1+cu128` + `ffmpeg` para RTX 5090)
- Compatibilidad checkpoints legacy: `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`
- Puerto local: `127.0.0.1:7851`

Levantar:

```bash
docker compose -f apps/alltalk/compose.yaml up -d
```

Bajar:

```bash
docker compose -f apps/alltalk/compose.yaml down
```

## Integracion con Direct Chat

`scripts/openclaw_direct_chat.py` usa AllTalk por HTTP. Variables opcionales:

- `DIRECT_CHAT_ALLTALK_URL` (default `http://127.0.0.1:7851`)
- `DIRECT_CHAT_ALLTALK_HEALTH_PATH` (default `/ready`)
- `DIRECT_CHAT_ALLTALK_TTS_PATH` (default `/api/tts-generate`)
- `DIRECT_CHAT_ALLTALK_TIMEOUT_SEC` (default `60`)
- `DIRECT_CHAT_ALLTALK_CHARACTER_VOICE` (si se define, fuerza esa voz)
- `DIRECT_CHAT_ALLTALK_DEFAULT_VOICE` (default `female_01.wav`)

## Nota de migracion

La arquitectura XTTS manual anterior fue eliminada del repo y la operacion de voz queda centralizada en Docker/Dockge.

Payload usado por Direct Chat contra AllTalk:

- `text_input`
- `character_voice_gen`
- `language`
- `text_filtering`
- `narrator_enabled`
- `narrator_voice_gen`
- `text_not_inside`
- `output_file_name`
- `output_file_timestamp`
- `autoplay`
- `autoplay_volume`
