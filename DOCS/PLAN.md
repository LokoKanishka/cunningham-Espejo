# Cunningham — Plan de trabajo (esqueleto)

## Principio rector
- Cero costos variables: no API keys pagas / no pay-per-token.
- Se permite: ChatGPT Plus (20 USD) + Codex por suscripción (OAuth).
- Siempre: scripts verificables ("botón rojo") y commits chicos.

## Estado actual (cerrado)
- OpenClaw instalado y en PATH.
- Provider externo sin API key: openai-codex (Codex CLI OAuth).
- Default model: openai-codex/gpt-5.1-codex-mini.
- Seguridad: 0 critical.
- Verificación:
  - ./scripts/verify_all.sh => ALL_OK
  - ./scripts/model_{mini,normal,max}.sh fuerzan /new

## Objetivo del proyecto
1) Entender y documentar cómo opera Moltbot/OpenClaw con IA externa por suscripción.
2) Extender capacidades usando aportes de la comunidad (plugins/skills/tools) sin costos.

## Roadmap por hitos (cada uno con botón rojo)
H2 — Observabilidad mínima
- Entregable: scripts para ver logs, estado, y health rápido.
- Botón rojo: scripts/verify_all.sh + scripts/verify_security_audit.sh OK.

H3 — “Skills” útiles y seguras (solo locales / offline cuando sea posible)
- Entregable: 2–3 skills/plugins comunitarios evaluados e integrados.
- Botón rojo: smoke + audit 0 critical + demo reproducible.

H4 — Tooling local potente
- Entregable: integración de herramientas locales (fs, git, shell) con sandbox ON.
- Botón rojo: demo de tarea real (ej: clonar repo, editar archivo, commit) sin intervención manual.

H5 — Interfaz / UX
- Entregable: comandos de “modo” (mini/normal/max), quickstart, y troubleshooting.
- Botón rojo: nueva máquina → instalación + verify_all en <10 min.

## Reglas de contribución
- Cada cambio: commit + push.
- Nada de secretos en repo.
- Si un comando no existe, se reemplaza por script.
