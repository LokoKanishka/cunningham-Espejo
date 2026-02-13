# Interfaz de operacion del stack con Dockge

Dockge es una UI opcional para operar stacks Docker Compose en local.

## Principios

- Fuente de verdad: scripts + compose del repo (`./scripts/bringup_all.sh`, `./scripts/webhook_smoke.sh`, etc.).
- Dockge no reemplaza automatizaciones headless.
- Exposicion local-only: `http://127.0.0.1:5001`.

## Levantar / apagar Dockge

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

## Seguridad

Dockge monta `/var/run/docker.sock`, por lo que tiene control total sobre Docker local.

- Mantener el bind solo en `127.0.0.1:5001`.
- No publicar en `0.0.0.0`.
