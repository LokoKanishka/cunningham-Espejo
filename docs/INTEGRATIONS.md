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

Nombre: community-mcp-20 (bundle)
Repo: 20 repos de GitHub (solo comunidad), ver `DOCS/community_mcp_catalog.json`
Licencia: mezcla de MIT / Apache-2.0 / BSD-3-Clause / MPL-2.0 (por repo)
Pin (tag/commit): commit pinneado por repo en `DOCS/community_mcp_catalog.json`
Qué aporta: fuentes MCP para ampliar autonomía/capacidades (web, github, notion, cloud, k8s, terraform, jupyter, búsqueda)
Riesgo / superficie: código de terceros; no se habilita automático; requiere revisión antes de activar como plugin/herramienta
Resultado de smoke test: `./scripts/community_mcp.sh check` => `COMMUNITY_MCP_OK catalog=20`
Fecha: 2026-02-12

Nombre: community-mcp-bridge-top10 (mcporter)
Repo: top10 del catálogo comunitario, vía `mcporter`
Licencia: según cada servidor MCP de origen
Pin (tag/commit): catálogo base en `DOCS/community_mcp_catalog.json`; bridge por nombre `community-*` en `~/.mcporter/mcporter.json`
Qué aporta: operación real de 10 MCP servers comunitarios dentro del runtime de skills de OpenClaw
Riesgo / superficie: depende de binarios externos (`mcporter`, `npx`, `uvx`) y de credenciales para algunos providers
Resultado de smoke test: `./scripts/community_mcp_bridge.sh probe` => `ok=10 fail=0`
Fecha: 2026-02-12
