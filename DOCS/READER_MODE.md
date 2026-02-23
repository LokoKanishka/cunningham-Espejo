# READER_MODE v0

Estado: activo en `scripts/openclaw_direct_chat.py`.

Persistencia:
- Archivo: `~/.openclaw/reading_sessions.json`
- Lock: `~/.openclaw/.reading_sessions.lock`

Objetivo v0:
- Cursor no avanza al pedir `session/next`; avanza sólo con `session/commit`.
- Si hay barge-in durante un chunk pendiente, ese chunk queda pendiente.
- Tras reinicio del proceso, `session/next` vuelve a entregar el pendiente (replay).

## Endpoints

- `POST /api/reader/session/start`
  - body: `{ "session_id": "s1", "chunks": ["a", "b"], "reset": true }`
- `GET /api/reader/session/next?session_id=s1`
- `POST /api/reader/session/commit`
  - body: `{ "session_id": "s1", "chunk_id": "chunk_001" }`
- `POST /api/reader/session/barge_in`
  - body: `{ "session_id": "s1", "detail": "speech_detected" }`
- `GET /api/reader/session?session_id=s1`

## Botón rojo

```bash
./scripts/verify_reader_mode.sh
```

Salida esperada final:

```text
READER_MODE_OK
```
