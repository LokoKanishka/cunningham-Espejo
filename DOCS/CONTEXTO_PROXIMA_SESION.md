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
  - abrir/cerrar items del escritorio (seguro, sin borrar nada)
  - web_ask (experimental): preguntar/dialogar con ChatGPT/Gemini via web (sin API paga)
- Comandos slash y export de chat
- Historial persistente por sesión

## Qué no está habilitado todavía
- No hay `web_search` “nativo” del gateway configurado con proveedor externo.
- En su lugar, se está usando:
  - Atajos deterministas (abrir URLs directas)
  - SearXNG local (fuera de este handler)
  - `web_ask` (carril experimental) para ChatGPT/Gemini web sin APIs

## Archivos clave
- `scripts/openclaw_direct_chat.py`
- `scripts/openclaw_direct_chat.sh`
- `DOCS/INFORME_MOLBOT_DIRECT_CHAT.md`
 - `scripts/web_ask_playwright.js`
 - `scripts/web_ask_bootstrap.sh`

## Comandos útiles
```bash
systemctl --user status openclaw-direct-chat.service
systemctl --user restart openclaw-direct-chat.service
curl -i http://127.0.0.1:8787/
```

## Comandos útiles (en el chat)
- `login chatgpt` / `login gemini` (abre shadow profile para iniciar sesión)
- `preguntale a chatgpt: ...` / `preguntale a gemini: ...`
- `dialoga con chatgpt: ...` / `dialoga con gemini: ...` (2 turnos)
- `abrí <nombre> del escritorio`
- `cerrá las ventanas que abriste del escritorio`
- `reset ventanas escritorio`

## Nota importante
Si vuelve a aparecer un 404 con parámetros (`/?v=...`), esta versión ya lo tolera.
Usar siempre URL base: `http://127.0.0.1:8787/`.
