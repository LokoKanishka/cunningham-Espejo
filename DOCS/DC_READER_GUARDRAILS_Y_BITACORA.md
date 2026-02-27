# DC Reader Guardrails y Bitacora

Objetivo: evitar regresiones recurrentes en `Molbot Direct Chat` (DC) en modo lectura (texto + voz + comandos).

Este archivo es el punto unico a consultar **antes** de tocar:
- `scripts/molbot_direct_chat/ui_html.py`
- `scripts/openclaw_direct_chat.py`
- `scripts/molbot_direct_chat/stt_local.py`

## 1) Indice Tecnico Rapido

### UI / render progresivo
- Archivo: `scripts/molbot_direct_chat/ui_html.py`
- Bloques clave:
  - `launchReaderLiveRender(...)`: render progresivo del bloque mientras suena TTS.
  - `_splitReaderReplyForLive(...)`: separa prefijo fijo vs cuerpo de bloque.
  - `pollChatFeedOnce(...)`: evita espejar mensajes duplicados del feed.
  - `stopReaderLiveRender()`: corta escritura en pausa/detener.

### Backend reader / comandos
- Archivo: `scripts/openclaw_direct_chat.py`
- Bloques clave:
  - `_maybe_handle_local_action(...)`: comandos reader (leer, seguir, pausa, detener, comentario).
  - `_reader_emit_chunk(...)`: emision de chunk + gate de TTS.
  - `_reader_meta(...)`: `chunk_text`, `tts_wait_stream_id`, `auto_continue`.
  - `ReaderSessionStore`: cursor/pending/bookmark/commit.

### STT / comandos de voz
- Archivos:
  - `scripts/openclaw_direct_chat.py` -> `_voice_command_kind(...)`, `STTManager.poll(...)`
  - `scripts/molbot_direct_chat/stt_local.py` -> VAD/segmentacion/transcripcion.

## 2) Invariantes (NO romper)

1. Lectura progresiva visible:
- Cuando hay `reader.chunk_text`, el texto del bloque debe desplegarse de a poco (no pegarse completo de entrada).

2. Sin duplicado de chat reader:
- No debe aparecer bloque completo fijo + bloque progresivo a la vez para el mismo chunk.

3. Respuestas de control exactas:
- `pausa lectura` -> `si como seguimos?`
- `detenete` -> `detenida`

4. Autopilot interno no debe contaminar feed:
- Mensajes internos (`segui`/`pausa` automáticos) deben ir con `source: "ui_auto_reader"` y no mostrarse como usuario.

5. Comando "leer libro N" idempotente:
- Repetir `leer libro 1` mientras ya lee el mismo libro **no** debe reiniciar ni duplicar Bloque 1.

6. Pregunta de comprension de bloque:
- `de que habla este bloque?` debe responder sobre el bloque activo (sin depender del modelo remoto).

## 3) Cosas que NO hacer

1. No bypass del render live:
- No forzar `push("assistant", reply)` cuando `launchReaderLiveRender(...)` ya se activo.

2. No volver a match fragil:
- No quitar fallbacks de `_splitReaderReplyForLive(...)` (BOM, normalizacion, fallback por `Bloque N/X`).

3. No desproteger feed:
- No eliminar filtro de `pollChatFeedOnce(...)` para mensajes espejados/duplicados.

4. No volver a parser de voz "substring libre":
- En `_voice_command_kind(...)`, no aceptar comandos por coincidencias sueltas en medio de frases largas.

5. No mezclar ventanas/workspaces en pruebas humanas:
- Nunca mover ventanas entre workspaces.
- Si DC esta en otro workspace, abrir nueva ventana en el workspace actual.

## 4) Checklist Obligatoria Antes de Editar

1. Leer este archivo completo.
2. Revisar cambios previos en:
- `scripts/molbot_direct_chat/ui_html.py`
- `scripts/openclaw_direct_chat.py`
3. Correr baseline rapido:
- `pytest -q tests/test_reader_mode.py tests/test_reader_command_stress.py`
4. Si tocaste `stt_local.py` o valores de voz:
- `./scripts/verify_stt_memory.sh`
5. Si tocaste reader/voz/UI:
- `node scripts/tmp_reader_human_sample.js`

## 5) Boton Rojo (post-cambio)

1. Tests:
```bash
pytest -q tests/test_reader_mode.py tests/test_reader_command_stress.py
```

2. Corrida humana:
```bash
node scripts/tmp_reader_human_sample.js
```

3. Stress 3 rondas:
```bash
node scripts/tmp_reader_flow_3runs.js
```

4. Si hubo cambios de parametros STT:
```bash
./scripts/verify_stt_memory.sh
```

## 6) Bitacora de Estado (resumen vivo)

### 2026-02-27
- Fix: idempotencia de `leer libro N` para mismo libro en lectura activa.
- Fix: respuestas de control reader:
  - pausa -> `si como seguimos?`
  - detener -> `detenida`
- Fix: filtro de feed para no duplicar burbujas reader.
- Fix: `source: ui_auto_reader` para pasos internos de autopilot.
- Fix: comando local `de que habla este bloque?` con resumen del bloque activo.
- Mejora: sincronizacion texto/voz en UI con CPS adaptativo y anclaje temporal.

### 2026-02-27 (modo de voz estable/experimental)
- Problema observado:
  - alta fragilidad en flujo fluido de voz+tipeo (ajuste de STT/VAD/TTS rompe comportamientos ya estabilizados).
- Causa raiz:
  - acoplamiento fuerte entre barge-in, bridge STT->chat, render/tipeo UI y estado de sesion en tiempo real.
- Cambio planificado:
  - agregar selector explicito de perfil de voz en DC (`estable` vs `experimental`) con boton UI.
  - `estable` prioriza robustez diaria (menos interrupciones agresivas y menos automatismos de chat por voz).
  - `experimental` conserva flujo fluido actual para pruebas.
- Criterio de exito:
  - poder alternar perfil en un click y ver estado activo en UI sin reiniciar servicios.
  - aislar pruebas de mejoras de voz sin romper el flujo diario.
- Verificacion automatica:
  - `pytest -q tests/test_reader_mode.py` -> OK (incluye test de `voice_mode_profile`).
  - `python3 -m py_compile scripts/openclaw_direct_chat.py` -> OK.
- Riesgo residual esperado:
  - si usuario cambia manualmente umbrales sueltos, puede desalinear el perfil hasta volver a seleccionar modo.

### Riesgo conocido
- Latencia de pausa puede variar por backend/player de audio (no siempre sub-segundo).
- El objetivo funcional se mantiene: pausa/detener cortan flujo y responden correcto.

## 7) Plantilla de nueva entrada de bitacora

Copiar/pegar:

```text
### YYYY-MM-DD
- Problema observado:
- Causa raiz:
- Cambio aplicado:
- Verificacion automatica:
- Verificacion humana:
- Riesgo residual:
```
