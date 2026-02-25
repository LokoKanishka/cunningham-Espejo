# Plugins — política y allowlist

## Principio
- Solo se permite **lo que está en allowlist**.
- Cualquier plugin opcional fuera de allowlist **no puede estar enabled**.
- Cambios de plugins requieren reinicio de gateway para aplicar.

## Allowlist (fuente de verdad)
Ver: `DOCS/allowlist_plugins.txt`

## Mods integrados (gratis)
- `lobster`: workflows tipados con aprobaciones/reanudación.
- `llm-task`: herramienta JSON-only para tareas estructuradas.
- `open-prose`: pack de skills/comandos `/prose` para flujos reutilizables.

## Reglas adicionales
- `lobster`, `llm-task` y `open-prose` deben estar **loaded**.
- WhatsApp debe estar **OFF** (canal deshabilitado), independientemente de si el plugin está instalado.
