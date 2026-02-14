# Contexto de Continuidad - Proyecto Actual

## En qué estamos
Estamos consolidando una interfaz local de operación llamada **Molbot Direct Chat** para hablar en lenguaje natural con el stack:
- OpenClaw gateway
- modelo `openai-codex/gpt-5.1-codex-mini`
- herramientas locales (firefox/escritorio)

## Qué funciona hoy
- UI en `http://127.0.0.1:8787/`
- Chat y streaming
- Acciones locales:
  - abrir firefox
  - listar escritorio real
- Comandos slash y export de chat
- Historial persistente por sesión

## Qué no está habilitado todavía
- `web_search` con internet en tiempo real

Motivo: faltan credenciales de proveedor de búsqueda en el entorno del gateway.

## Archivos clave
- `scripts/openclaw_direct_chat.py`
- `scripts/openclaw_direct_chat.sh`
- `DOCS/INFORME_MOLBOT_DIRECT_CHAT.md`

## Comandos útiles
```bash
systemctl --user status openclaw-direct-chat.service
systemctl --user restart openclaw-direct-chat.service
curl -i http://127.0.0.1:8787/
```

## Nota importante
Si vuelve a aparecer un 404 con parámetros (`/?v=...`), esta versión ya lo tolera.
Usar siempre URL base: `http://127.0.0.1:8787/`.
