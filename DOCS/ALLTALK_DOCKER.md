# AllTalk TTS por Docker

Migramos la voz de `Molbot Direct Chat` a **AllTalk TTS** en Docker.

## Stack de voz

- Compose: `apps/alltalk/compose.yaml`
- Imagen: `erew123/alltalk_tts:latest`
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
- `DIRECT_CHAT_ALLTALK_CHARACTER_VOICE` (default `ref_lucy.wav`)

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
