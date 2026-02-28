# DC Reader Guardrails y Bitacora

Objetivo: evitar regresiones recurrentes en `Molbot Direct Chat` (DC) en modo lectura (texto + voz + comandos).

Este archivo es el punto unico a consultar **antes** de tocar:
- `scripts/molbot_direct_chat/ui_html.py`
- `scripts/openclaw_direct_chat.py`
- `scripts/molbot_direct_chat/stt_local.py`

## Orden de Bitacora (obligatorio)

- Orden por archivo/componente: alfabetico por nombre de archivo.
- Orden de entradas temporales: cronologico ascendente por fecha/hora (mas viejo -> mas nuevo).
- Formato de fecha/hora: `YYYY-MM-DD HH:MM:SS TZ (offset)` y, cuando aplique, UTC en la misma linea.

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

### 2026-02-27 (split chat vs reader en progreso)
- Objetivo:
  - separar pantalla principal de chat (escritura) y pantalla dedicada de lectura (`/reader`) para reducir interferencias de voz.
- Cambio aplicado:
  - backend: estado de voz extendido con `voice_owner` (`chat|reader|none`) y `reader_mode_active`.
  - backend: nueva ruta `GET /reader` con UI dedicada de lectura.
  - chat UI (`/`): boton `Modo lectura` que abre `/reader` y bloquea controles de voz en chat cuando lectura esta activa.
  - reader UI (`/reader`): activa ownership de voz, envia comandos locales de lectura y permite volver a chat.
- Verificacion automatica:
  - `pytest -q tests/test_reader_mode.py` -> OK (27 passed).
  - `python3 -m py_compile scripts/openclaw_direct_chat.py scripts/molbot_direct_chat/ui_html.py scripts/molbot_direct_chat/reader_ui_html.py` -> OK.
  - smoke UI con playwright:
    - al abrir `Modo lectura`, `/` muestra escritura-only y `voice_owner=reader`.
    - `/reader` ejecuta `biblioteca` y responde correctamente.
- Riesgo residual:
  - falta terminar el handoff fino al cerrar multiples tabs de `/reader` para evitar carreras de ownership.

### 2026-02-27 (controles de párrafo en reader)
- Cambio aplicado:
  - UI `/reader` agrega:
    - `párrafo anterior`
    - `párrafo siguiente`
    - mini teclado numérico `párrafo #` + botón `ir`
  - backend agrega comando local `ir al párrafo <n>` con salto directo al bloque solicitado.
- Verificacion:
  - `pytest -q tests/test_reader_mode.py` -> OK (28 passed).
  - smoke UI `/reader`: jump + prev + next -> OK.

### 2026-02-27 20:23:26 -03 (viernes) / 23:23:26 UTC - CIERRE DE SESION
- Estado catalogado para retomar:
  - push de trabajo funcional en `main`: `5f308cf` (`feat(reader): separate reader screen with voice ownership and paragraph controls`).
  - checkpoint de retorno previo a split reader: tag `restore/pre-reader-split-20260227`.
  - commit de checkpoint/doc asociado: `62185c7` y `4d3b9c4`.
- Alcance completado hoy:
  - selector de perfil de voz `stable/experimental`.
  - split de pantalla: chat (`/`) en escritura + reader dedicado (`/reader`).
  - ownership de voz: `voice_owner` + `reader_mode_active`.
  - bloqueo de voz en chat cuando reader esta activo.
  - controles de navegación en reader:
    - `párrafo anterior`
    - `párrafo siguiente`
    - `ir al párrafo <n>` con mini teclado numérico.
- Verificacion consolidada:
  - `pytest -q tests/test_reader_mode.py` -> OK (28 passed).
  - smoke UI:
    - activación `Modo lectura` en `/` -> escritura-only + owner `reader`.
    - comandos en `/reader` (`biblioteca`, jump/prev/next párrafo) -> OK.
- Pendiente para próxima sesión:
  - endurecer handoff al cerrar múltiples pestañas `/reader` (evitar carreras de ownership).
  - opcional: lock por `session_id`/`tab_id` para liberar voz solo por dueño actual.

### 2026-02-28 17:40:00 -03 (sábado) / 20:40:00 UTC
- Problema observado:
  - casos de lectura con texto visible pero voz no iniciada al coexistir acciones de cierre/ownership entre pestañas reader.
- Causa raíz:
  - release de voz sin identidad de pestaña (`beforeunload` podía competir con otra pestaña activa).
- Cambio aplicado:
  - `/reader` ahora envía `reader_owner_token` (token por pestaña) en `activate/release/beforeunload`.
  - backend `/api/voice` agrega lock de ownership por token:
    - ignora `enabled=false`/`voice_owner=chat`/`reader_mode_active=false` cuando el token no coincide con el dueño activo.
    - responde `ownership_conflict=true` cuando bloquea esa liberación.
  - al aceptar `enabled=false`, backend corta reproducción activa con `_request_tts_stop(reason=\"voice_disabled\")`.
  - payload de estado agrega `reader_owner_token_set` para diagnóstico.
- Verificación automatica:
  - `python3 -m py_compile scripts/openclaw_direct_chat.py scripts/molbot_direct_chat/reader_ui_html.py` -> OK.
  - `pytest -q tests/test_reader_mode.py` -> OK (28 passed).
  - smoke API ownership:
    - release con token incorrecto -> `ownership_conflict=true`, voz sigue `enabled=true`.
    - release con token correcto -> libera owner y desactiva voz.
- Riesgo residual:
  - cierre forzado del navegador/proceso puede no ejecutar `beforeunload`; en esos casos la liberación depende del siguiente ciclo de control o comando explícito.

### 2026-02-28 18:05:00 -03 (sábado) / 21:05:00 UTC
- Problema observado:
  - comandos humanos tipo `ok continua la lectura desde "..."` (incluyendo typos `contiuna`/`contionua`) podían caer a modelo remoto y terminar en timeout/`[sin respuesta]`.
  - al tipear durante TTS activo (sobre todo en estado `commenting`), no siempre se interrumpía reproducción en caliente.
- Causa raíz:
  - parser local de `continuar desde` demasiado estricto (solo variante `continuar ...`).
  - interrupción por texto tipiado estaba acotada a estado reader `reading/continuous`.
  - UI `/reader` mostraba fallback `[sin respuesta]` aunque la respuesta HTTP viniera con error explícito.
- Cambio aplicado:
  - parser reader robustecido para alias: `continua|contiuna|contionua` + `... la lectura desde ...` (con y sin comillas).
  - `_is_reader_control_command(...)` ahora reconoce esas variantes para evitar ruta remota.
  - typed barge-in: cualquier input `ui_text` interrumpe TTS activo (`typed_interrupt`), incluso fuera de `reading`.
  - UI `/reader` muestra `Error: <detalle>` cuando `/api/chat` retorna error HTTP, en vez de caer en `[sin respuesta]` silencioso.
- Verificación automatica:
  - `pytest -q tests/test_reader_mode.py tests/test_reader_command_stress.py` -> OK (32 passed).
  - smoke runtime:
    - `ok contiuna/contionua/continua ... desde ...` -> respuesta local reader (sin `MODEL_TIMEOUT`).
    - al tipear durante TTS activo -> `last_status.detail=typed_interrupt` y `tts_playing=false`.
- Riesgo residual:
  - si el modelo remoto se usa para consultas no-reader en paralelo con alta carga, puede seguir haber timeout remoto, pero ya no aplica al comando local de `continuar desde`.

### 2026-02-28 18:39:16 -03 (sábado) / 21:39:16 UTC
- Problema observado:
  - al ejecutar `leer libro N` con `reader_mode` en OFF podía retomar cursor de una sesión vieja del mismo libro (por ejemplo empezar en bloque 5) en lugar de iniciar desde bloque 1.
- Causa raíz:
  - la rama de resume para mismo libro no verificaba ownership vivo de reader; bastaba estado previo `paused/commenting/reading` para retomar.
- Cambio aplicado:
  - guardrail en `scripts/openclaw_direct_chat.py`:
    - `leer libro N` solo retoma sesión previa si `voice_owner=reader` y `reader_mode_active=true`.
    - con reader OFF cae a `start_session(..., reset=True)` e inicia lectura nueva desde bloque 1.
  - tests reforzados en `tests/test_reader_mode.py`:
    - caso ON + mismo libro pausado retoma siguiente bloque.
    - caso OFF + mismo libro inicia bloque 1 (sin `Retomo lectura`).
    - `continuar desde "frase"` salta a bloque futuro no leído (ej. bloque 10).
  - aislamiento de `VOICE_STATE_PATH` por test para evitar contaminación de estado entre corridas.
- Verificación automatica:
  - `pytest -q tests/test_reader_mode.py tests/test_reader_command_stress.py` -> OK (34 passed).
  - `python3 -m py_compile scripts/openclaw_direct_chat.py tests/test_reader_mode.py` -> OK.
- Commit/push:
  - `59fb3e8` (`reader: avoid stale same-book resume when mode is off`) en `main` y subido a `origin/main`.
- Riesgo residual:
  - el chunking depende del parser del libro (`1/1` vs `1/3`), pero el contrato funcional queda estable: en OFF inicia lectura nueva y en ON retoma.

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
