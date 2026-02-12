# Integrations log

Registrar cada integración comunitaria:

Nombre: lobster (plugin)
Repo: bundled with OpenClaw (`@openclaw/lobster`)
Licencia: OpenClaw bundled plugin
Pin (tag/commit): version `2026.2.9` (local install)
Qué aporta: workflows tipados, approvals/resume, envelope JSON estable
Riesgo / superficie: ejecuta subproceso local `lobster`; requiere allowlist estricta
Resultado de smoke test: `./scripts/verify_lobster.sh` => `LOBSTER_OK`
Fecha: 2026-02-12

Nombre: llm-task (plugin)
Repo: bundled with OpenClaw (`@openclaw/llm-task`)
Licencia: OpenClaw bundled plugin
Pin (tag/commit): version `2026.2.9` (local install)
Qué aporta: herramienta JSON-only para tareas estructuradas
Riesgo / superficie: permite invocaciones LLM; mantener allowlist por modelo/proveedor
Resultado de smoke test: `openclaw plugins list` muestra `llm-task loaded`
Fecha: 2026-02-12

Nombre: open-prose (plugin)
Repo: bundled with OpenClaw (`@openclaw/open-prose`)
Licencia: OpenClaw bundled plugin
Pin (tag/commit): version `2026.2.9` (local install)
Qué aporta: skill pack y comando `/prose` para flujos reutilizables
Riesgo / superficie: orquestación adicional; mantener plugin allowlist y gateway local
Resultado de smoke test: `openclaw plugins list` muestra `open-prose loaded`
Fecha: 2026-02-12
