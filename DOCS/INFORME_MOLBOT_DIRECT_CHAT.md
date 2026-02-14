# Informe - Molbot Direct Chat (2026-02-14)

## Objetivo
Tener una interfaz de chat local, simple y usable, conectada directo a OpenClaw (sin doble capa tipo OpenWebUI encima).

## Resultado
Se implementó y dejó funcionando una UI local llamada **Molbot Direct Chat** en:
- `http://127.0.0.1:8787/`

## Implementación
Archivos creados/actualizados en repo:
- `scripts/openclaw_direct_chat.py`
- `scripts/openclaw_direct_chat.sh`

Servicio de usuario (fuera de repo):
- `~/.config/systemd/user/openclaw-direct-chat.service`

## Funciones disponibles
- Chat directo al gateway OpenClaw (`/v1/chat/completions`)
- Streaming de respuesta en UI
- Historial por sesión (persistido en `~/.openclaw/direct_chat_histories/`)
- Herramientas locales activables por sesión:
  - `firefox`
  - `desktop` (listar contenido real de escritorio)
  - `model`
- Botones rápidos:
  - Abrir Firefox
  - Listar Escritorio
- Comandos slash:
  - `/new`
  - `/firefox [url]`
  - `/escritorio`
  - `/modo [conciso|operativo|investigacion]`
- Export de conversación:
  - MD
  - TXT
- Adjuntos (texto, imagen y archivo, con resumen de contexto)

## Bugs corregidos en esta sesión
1. `404` al abrir `/?v=2`
- Causa: el handler solo aceptaba ruta `/` exacta.
- Fix: parseo de URL por `urlparse`, ignorando query params en root.

2. Error JS `Invalid or unexpected token`
- Causa: el HTML embebido no era raw string y rompía escapes `\n` en JS.
- Fix: `HTML = r"""..."""`.

3. Acciones locales sin respuesta cuando `streaming` estaba activo
- Causa: `/api/chat/stream` esperaba SSE pero acciones locales devolvían JSON simple.
- Fix: acciones locales también emiten SSE (`data: {token...}` + `[DONE]`).

4. Timeout al abrir Firefox
- Causa: uso de `subprocess.run` esperando proceso interactivo.
- Fix: uso de `subprocess.Popen(..., start_new_session=True)` desacoplado.

5. Ruido en consola por `favicon.ico`
- Fix: handler explícito para `/favicon.ico` con `204`.

## Estado actual verificado
- Servicio `openclaw-direct-chat` activo
- Puerto `8787` escuchando en loopback
- `GET /` y `GET /?v=2` OK
- `POST /api/chat` OK
- `POST /api/chat/stream` OK
- Flujo UI probado con automatización (Playwright CLI)

## Limitación actual (esperada)
`web_search` falla por falta de proveedor/config de búsqueda web:
- No hay `BRAVE_API_KEY`
- No hay `OPENROUTER_API_KEY`
- No hay `PERPLEXITY_API_KEY`

Sin esas claves, el modelo responde pero no puede ejecutar búsqueda web real.

## Siguiente paso sugerido
Si se quiere búsqueda web real desde el chat:
1. Crear key de proveedor (Brave u otro)
2. Configurarla en OpenClaw (`openclaw configure --section web` o env de gateway)
3. Reiniciar gateway y validar tool `web_search`
