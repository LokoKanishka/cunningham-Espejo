# Community MCP 20 (solo comunidad)

Catálogo pinneado: `DOCS/community_mcp_catalog.json`

Objetivo: incorporar 20 repositorios de GitHub mantenidos por la comunidad para ampliar herramientas/capacidades del agente sin desarrollar módulos propios en este repo.

## Comandos
- Listar catálogo: `./scripts/community_mcp.sh list`
- Validar catálogo: `./scripts/community_mcp.sh check`
- Descargar los 20 repos pinneados: `./scripts/community_mcp.sh sync`
- Configurar bridge MCP (top 10): `./scripts/community_mcp_bridge.sh setup`
- Verificar bridge MCP (top 10): `./scripts/community_mcp_bridge.sh check`
- Probar handshake de los 10: `./scripts/community_mcp_bridge.sh probe`
- Demo real (Cloudflare docs): `./scripts/community_mcp_bridge.sh demo`

## Ubicación de descargas
- Carpeta local: `community/mcp/repos/`
- Cada carpeta incluye `.community_source.json` con commit pinneado y URL de origen.

## Seguridad operativa
- No habilita plugins automáticamente.
- No modifica `allowlist_plugins.txt`.
- Solo descarga código fuente pinneado por commit para revisión/integración posterior.

## Bridge MCP (operación en OpenClaw)
- El bridge usa `mcporter` (skill oficial de OpenClaw) y configura 10 servidores `community-*` en `~/.mcporter/mcporter.json`.
- Esto permite usarlos desde el runtime de skills/comandos nativos del agente sin convertirlos a plugins OpenClaw.
