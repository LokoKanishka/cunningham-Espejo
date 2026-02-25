# Interfaz de operacion del stack con Dockge

Dockge es una UI opcional para operar stacks Docker Compose en local.

## Principios

- Fuente de verdad: scripts + compose del repo (`./scripts/bringup_all.sh`, `./scripts/webhook_smoke.sh`, etc.).
- Dockge no reemplaza automatizaciones headless.
- Exposicion local-only: `http://127.0.0.1:5001`.
- El compose canonico de `infra` es `docker-compose.yml`.
- `compose.yaml` existe como symlink para que Dockge detecte el stack.

## Comandos UI (comando unico)

```bash
./scripts/ui_up.sh
./scripts/ui_status.sh
./scripts/ui_open.sh
./scripts/ui_down.sh
```

- `ui_up`: levanta Dockge y muestra `UI_URL=http://127.0.0.1:5001`
- `ui_status`: muestra estado de Dockge y servicios clave de `infra`
- `ui_open`: abre URL con `xdg-open` si existe; si no, solo imprime URL
- `ui_down`: baja Dockge

## Lucy UI Panel (funcional)

Panel funcional para enviar requests al Gateway v1 y navegar inbox/outbox/deadletter:

```bash
./scripts/ui_panel_up.sh
./scripts/verify_ui_panel.sh
./scripts/ui_panel_down.sh
```

- URL: `http://127.0.0.1:5100`
- Documentacion: `docs/LUCY_UI_PANEL.md`

## Levantar / apagar Dockge (bajo nivel)

```bash
./scripts/bringup_dockge.sh
./scripts/verify_dockge.sh
./scripts/teardown_dockge.sh
```

Tambien se puede usar compose directo:

```bash
docker compose --env-file apps/dockge/.env -f apps/dockge/compose.yaml up -d
docker compose --env-file apps/dockge/.env -f apps/dockge/compose.yaml down
```

Para compose de `infra`, usar helper y evitar warnings por doble archivo:

```bash
./scripts/compose_infra.sh ps
./scripts/compose_infra.sh up -d n8n
./scripts/compose_infra.sh down
```

## Requisito critico de paths

Dockge necesita que el directorio de stacks se monte con la misma ruta host==container y en ruta absoluta (FULL path).

- `apps/dockge/.env`: `WORKSPACE_DIR=/home/lucy-ubuntu/Lucy_Workspace`
- `apps/dockge/compose.yaml`: `${WORKSPACE_DIR}:${WORKSPACE_DIR}`
- `DOCKGE_STACKS_DIR=${WORKSPACE_DIR}`

## Como detectar stacks

Dockge espera stacks con layout:

- `<stacks_dir>/<stackName>/compose.yaml`

Para este caso:

- `WORKSPACE_DIR=/home/lucy-ubuntu/Lucy_Workspace`
- stack `infra` en `/home/lucy-ubuntu/Lucy_Workspace/infra/compose.yaml`

Si no aparece automaticamente en UI, usar `Scan Stacks Folder` en Dockge.

## Stack de voz (AllTalk)

- Stack path: `apps/alltalk/compose.yaml`
- Puerto esperado por Direct Chat: `127.0.0.1:7851`
- Referencia: `DOCS/ALLTALK_DOCKER.md`

## Seguridad

Dockge monta `/var/run/docker.sock`, por lo que tiene control total sobre Docker local.

- Mantener el bind solo en `127.0.0.1:5001`.
- No publicar en `0.0.0.0`.
