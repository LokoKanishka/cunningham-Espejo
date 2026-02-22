# Cunningham — Plan de trabajo (esqueleto)

## Principio rector
- Cero costos variables: no API keys pagas / no pay-per-token.
- Se permite: ChatGPT Plus (20 USD) + Codex por suscripción (OAuth).
- Siempre: scripts verificables ("botón rojo") y commits chicos.

## Estado actual (cerrado)
- OpenClaw instalado y en PATH.
- Provider externo sin API key: openai-codex (Codex CLI OAuth).
- Default model: openai-codex/gpt-5.1-codex-mini.
- Seguridad: 0 critical.
- Verificación:
  - ./scripts/verify_all.sh => ALL_OK
  - ./scripts/model_{mini,normal,max}.sh fuerzan /new

## Objetivo del proyecto
1) Entender y documentar cómo opera Moltbot/OpenClaw con IA externa por suscripción.
2) Extender capacidades usando aportes de la comunidad (plugins/skills/tools) sin costos.

## Roadmap por hitos (cada uno con botón rojo)
H2 — Observabilidad mínima
- Entregable: scripts para ver logs, estado, y health rápido.
- Botón rojo: scripts/verify_all.sh + scripts/verify_security_audit.sh OK.

H3 — “Skills” útiles y seguras (solo locales / offline cuando sea posible)
- Entregable: 2–3 skills/plugins comunitarios evaluados e integrados.
- Botón rojo: smoke + audit 0 critical + demo reproducible.

H4 — Tooling local potente
- Entregable: integración de herramientas locales (fs, git, shell) con sandbox ON.
- Botón rojo: demo de tarea real (ej: clonar repo, editar archivo, commit) sin intervención manual.

H5 — Interfaz / UX
- Entregable: comandos de “modo” (mini/normal/max), quickstart, y troubleshooting.
- Botón rojo: nueva máquina → instalación + verify_all en <10 min.

## Reglas de contribución
- Cada cambio: commit + push.
- Nada de secretos en repo.
- Si un comando no existe, se reemplaza por script.

## Roadmap operativo vigente (DC / Cunningham)
Fase 0 — Cerrar voz en DC sin romper UI
- Objetivo: mergear `feat/voice-tts-playing-flag` en `main` con estabilidad.
- Botón rojo:
  - `./scripts/test_smoke.sh`
  - `python3 -m py_compile $(git ls-files '*.py')`
  - `python3 -m unittest tests.test_voice_stt_manager tests.test_openclaw_youtube_and_tools`
  - `pytest -q tests/test_openclaw_youtube_and_tools.py`
  - prueba humana VOZ ON/OFF en `Molbot Direct Chat`
- Auditoría:
  - no cambios visuales,
  - `GET /api/voice` puro,
  - `POST /api/voice` + `/api/stt/poll` gobiernan STT,
  - sin regresión de router de modelos.

Fase 1 — Operatividad de STT en host real
- Objetivo: que hablar sea tan confiable como tipear.
- Claves: dependencias instaladas, device correcto, ownership estable, logs claros.
- Botón rojo: 5 frases seguidas en DC con `journalctl -f` sin errores y sin eco durante TTS.

Fase 2 — Modelo/routing sin sorpresas
- Objetivo: cero `model not found` por drift de naming.
- Claves: catálogo real, selección determinista, fallback solo a modelos instalados, test de router.

Fase 3 — Test suite anti-flake
- Objetivo: separar tests dependientes de host (docker.sock/redis/workspace) de unit tests puros.
- Botón rojo: suite estable en ambiente mínimo.

## Regla transversal: stress humano en DC (cuando aplique)
- Es obligatorio correr stress humano en `Molbot Direct Chat` si el cambio toca voz, sesión, guardrails, workspace, router, polling o envío automático de STT.
- Si el cambio es solo documentación o refactor sin impacto funcional, este stress es opcional.
- Criterio mínimo de stress humano:
  - VOZ ON: 5 frases consecutivas enviadas por micrófono.
  - Durante TTS: sin auto-transcripción de eco.
  - VOZ OFF: sin nuevas capturas/envíos por micrófono.
  - Sin errores críticos en `journalctl -f`.

## Esqueleto a largo plazo (Espejo-de-Lucy)
Fase A — Contrato de audio offline
- Objetivo: entrada/salida de voz local reproducible sin red.
- Claves: VAD, STT, TTS, anti-eco, dispositivos, watchdog.

Fase B — Contrato de modelos
- Objetivo: catálogo/nombres únicos compartidos con DC.
- Resultado esperado: evitar modelos fantasma como `gpt-oss:20b`.

Fase C — Verify único
- Objetivo: `verify_all`/smoke que indique en ~30s el estado de salud.
