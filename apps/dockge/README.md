# Dockge (UI operativa local)

Este stack de Dockge se administra por separado del stack `infra` para que la operación principal siga siendo headless por scripts.

- Infra sigue levantando por `./scripts/bringup_all.sh`.
- Dockge es opcional y se levanta por scripts dedicados.
- La UI queda solo en `127.0.0.1:5001`.
