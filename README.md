# cunningham

Laboratorio desde cero para Moltbot upstream + modelos externos + cambio de modelo + extensiones comunitarias (con trazabilidad y seguridad).

## Documentación clave
- `PLAN.md` — objetivo, reglas, roadmap
- `docs/SECURITY_CHECKLIST.md` — checklist para integrar comunidad
- `docs/INTEGRATIONS.md` — registro de integraciones pinneadas

## Operación rápida
- Botón rojo: `./scripts/verify_all.sh`
- Modo amplio (más capacidad de tools): `./scripts/mode_full.sh`
- Modo seguro (allowlist reducida): `./scripts/mode_safe.sh`
- UI local opcional del stack (Dockge): `docs/INTERFAZ_STACK_DOCKGE.md`

## Stack autonomía+visión (10)
- Documento: `DOCS/AUTONOMY_VISION_STACK.md`
- Verificación del stack: `./scripts/verify_stack10.sh`
- Botón rojo base (estable): `./scripts/verify_all.sh`

## Stack autonomía+visión (next 10)
- Documento: `DOCS/AUTONOMY_VISION_STACK_NEXT10.md`
- Verificación: `./scripts/verify_next10.sh`
- Extras: `./scripts/goals_worker.sh check`, `./scripts/ops_alerts.sh check`, `./scripts/web_research.sh check`

## Comunidad GitHub (20 descargas, pinneadas)
- Catálogo: `DOCS/community_mcp_catalog.json`
- Guía: `DOCS/COMMUNITY_MCP.md`
- Validar: `./scripts/community_mcp.sh check`
- Descargar bundle comunitario: `./scripts/community_mcp.sh sync`
- Bridge MCP top10 (mcporter): `./scripts/community_mcp_bridge.sh setup`
- Verificar bridge: `./scripts/community_mcp_bridge.sh check`
- Probar 10/10: `./scripts/community_mcp_bridge.sh probe`

## UX (Consola + Español + Voz)
- Consola pro: `./scripts/console_pro.sh`
- Modo español persistente: `./scripts/set_spanish_mode.sh`
- Chat con salida por voz: `./scripts/chat_voice_es.sh "tu pregunta"`
- Doc: `DOCS/UX_SPANISH_VOICE.md`
