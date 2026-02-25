# Lucy UI Panel (Gateway v1)

Panel local para operar funcionalmente el Gateway v1 sin depender de la UI de n8n.

## URL

- `http://127.0.0.1:5100`

## Levantar / bajar

```bash
./scripts/ui_panel_up.sh
./scripts/verify_ui_panel.sh
./scripts/ui_panel_down.sh
```

## Funcionalidades

- `GET /`: formulario para enviar request a `POST /webhook/lucy-input`
- `POST /send`: envia request y redirige a `/cid/<correlation_id>`
- `GET /cid/<cid>`: muestra ACK cacheado + inbox/outbox/deadletter
- `GET /browse/<box>`: lista archivos recientes de `inbox|outbox|deadletter|payloads`
- `POST /ops/smoke`: ejecuta allowlist (`webhook_smoke`, `n8n_gateway_e2e`)

## Contratos IPC

- ACK webhook: `contracts/lucy_ack_v1.schema.json`
- Outbox estructurado: `contracts/lucy_output_v1.schema.json`

Outbox source of truth:

- `ipc/outbox/<correlation_id>.json`

Compatibilidad temporal:

- `ipc/outbox/res_<correlation_id>.json`

## Seguridad / límites

- Exposición local-only: `127.0.0.1:5100`
- Runner de smoke con allowlist fija
- Mount de IPC en read-only para browsing
- El panel solo escribe por API al gateway
