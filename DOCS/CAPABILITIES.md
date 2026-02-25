# Capacidades prácticas (desktop + web)

## Estado actual
- Herramientas habilitadas en `main`: `exec`, `read`, `write`, `edit`, `process`, `browser`, `web_fetch`, `web_search`, `lobster`, `llm-task`.
- Verificación automática: `./scripts/verify_capabilities.sh`.

## Ver escritorio (desde el agente)
Prompt recomendado:

```text
Usá la herramienta exec y corré: ls -la ~/Escritorio
```

## Navegar web (desde el agente)
Prompt recomendado:

```text
Usá la herramienta web_fetch para leer https://example.com y resumí el contenido.
```

Si la red DNS está caída, la tool devuelve error de red (`ENOTFOUND`/`EAI_AGAIN`).
Eso no implica falta de permisos, sino conectividad del host.

## Botón rojo
```bash
./scripts/verify_capabilities.sh
./scripts/verify_all.sh
```
