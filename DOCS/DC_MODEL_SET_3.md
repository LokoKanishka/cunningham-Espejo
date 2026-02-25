# DC model set (3)

Fuente de verdad para `Molbot Direct Chat`:

1. `openai-codex/gpt-5.1-codex-mini` (cloud, default)
2. `dolphin-mixtral:latest` (local)
3. `huihui_ai/qwq-abliterated:32b-Q6_K` (local)

## Config

- `~/.openclaw/openclaw.json`
  - `agents.defaults.model.primary = openai-codex/gpt-5.1-codex-mini`
  - `agents.defaults.models` con entradas vacías `{}` para los modelos permitidos (sin claves extra no reconocidas).
- `~/.openclaw/direct_chat.env`
  - `DIRECT_CHAT_DEFAULT_MODEL=openai-codex/gpt-5.1-codex-mini`
  - `DIRECT_CHAT_CLOUD_MODELS=openai-codex/gpt-5.1-codex-mini`
  - `DIRECT_CHAT_OLLAMA_MODELS=dolphin-mixtral:latest,huihui_ai/qwq-abliterated:32b-Q6_K`

## Por qué deshabilitar failover a providers sin credenciales

Si el gateway enruta a un provider no autenticado (ej. `anthropic`/`google` sin auth efectiva), el request de chat queda en error y en UI se percibe como “spinner infinito” o sin respuesta útil.  
La corrección es sacar esos providers del camino para este flujo, no agregar claves nuevas.

## Verificación rápida

1. `curl -s http://127.0.0.1:8787/api/models | python3 -m json.tool`
2. `node scripts/verify_dc_ui_models.js` (usa UI real y valida los 3 modelos)
