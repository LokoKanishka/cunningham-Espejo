# Informe - Molbot Direct Chat (actualizado 2026-02-14)

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
  - `web_ask` (experimental: automatiza UI web de ChatGPT/Gemini sin APIs pagas)
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

## Capacidades nuevas (consolidación)
### 1) Perfil de Chrome fijo por sitio (determinismo)
- Config: `~/.openclaw/direct_chat_browser_profiles.json`
- Default: `_default` usa perfil `diego` (resuelto contra `~/.config/google-chrome/Local State`).
- Abrir sitios (ChatGPT/Gemini/YouTube/Wikipedia/Gmail) intenta respetar ese perfil para mantener sesión/cookies.

### 2) ask_chatgpt_web / ask_gemini_web (sin API paga)
Se agregó un carril experimental `web_ask` que permite:
- `preguntale a chatgpt: ...`
- `preguntale a gemini: ...`
- `dialoga con chatgpt: ...` (2 turnos: prompt + follow-up)
- `dialoga con gemini: ...` (2 turnos: prompt + follow-up)

Notas:
- Se ejecuta localmente con Playwright (Node) en `scripts/web_ask_playwright.js`.
- Usa un **shadow profile** en `~/.openclaw/web_ask_shadow/` para evitar locks del perfil real.
- Si falta login en shadow, responde `login_required` (fail-fast) con screenshot en `~/.openclaw/logs/web_ask_screens/`.
- Bootstrap de login: `scripts/web_ask_bootstrap.sh [chatgpt|gemini] [profile_name]` o desde la UI: `login chatgpt` / `login gemini`.

### 2.b) Gemini por API oficial (free tier)
- Para `preguntale a gemini:` y `dialoga con gemini:`, ahora se prioriza API oficial (sin automatización de clicks).
- Variables:
  - `GEMINI_API_ENABLED=1` (default)
  - `GEMINI_API_KEY=<tu_key_de_ai_studio>` (o `GOOGLE_API_KEY`)
  - `GEMINI_API_MODELS=gemini-2.5-flash,gemini-2.0-flash,gemini-1.5-flash`
  - `GEMINI_API_ALLOW_PAID=0` (default, evita modelos fuera de allowlist free)
  - `GEMINI_API_FREE_MODELS=...` (allowlist explícita de modelos gratuitos)
  - `GEMINI_API_DAILY_LIMIT=200` (hard cap diario local)
  - `GEMINI_API_PROMPT_CHAR_LIMIT=2500` (tope por prompt)
- Persistencia local recomendada:
  - `scripts/gemini_api_env.sh <GEMINI_API_KEY>`
  - reiniciar: `scripts/openclaw_direct_chat.sh 8787`

### 3) Escritorio: abrir/cerrar sin borrar nada
Acciones locales seguras (sin delete/move):
- `abrí <nombre> del escritorio`
  - Solo abre items existentes dentro de `~/Escritorio` o `~/Desktop`
  - Carpetas: usa `nautilus --new-window` (rastrea/permite cerrar)
  - Archivos: usa `xdg-open`
- `cerrá las ventanas que abriste del escritorio`
  - Cierra solo ventanas registradas por la sesión (usa `wmctrl`)
- `reset ventanas escritorio`
  - Limpia el registro de ventanas para esa sesión

### 4) No abrir en otro “escritorio virtual”
Al abrir items del escritorio, si la ventana es detectable, se mueve al workspace activo usando `wmctrl`.

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

## Limitaciones actuales (esperadas)
- `web_ask` depende de automatización de UI: puede romperse si cambia el DOM o aparece captcha/re-login.
- Requiere que el shadow-profile esté logueado (una vez) para ChatGPT/Gemini.
