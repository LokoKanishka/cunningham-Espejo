# Lucy Gateway Contract v1

## Request: `lucy_input_v1.schema.json`
Required fields:
- `kind`: event type (`"text"`, `"voice"`, etc)
- `source`: producer id (`"cli"`, `"mobile"`, `"sensor"`)
- `ts`: RFC3339 timestamp

Optional fields:
- `text`: input text payload
- `meta`: free-form object
- `correlation_id`: caller-provided idempotency key

Example request:
```json
{
  "kind": "text",
  "source": "cli",
  "ts": "2026-02-13T03:00:00Z",
  "text": "hola lucy",
  "meta": {
    "lang": "es"
  }
}
```

## Response ACK: `lucy_ack_v1.schema.json`
Required fields:
- `ok`: processing admission result
- `correlation_id`: canonical id for this event
- `received_ts`: RFC3339 receive timestamp
- `status`: always `"accepted"`

Optional fields:
- `next`: pipeline hint
- `reason`: failure reason when `ok=false`

Example response:
```json
{
  "ok": true,
  "correlation_id": "6f3d18424f4f4ec4a9f2f0d8ecf8f8d2",
  "received_ts": "2026-02-13T03:00:01.234Z",
  "status": "accepted",
  "next": "ipc://inbox/6f3d18424f4f4ec4a9f2f0d8ecf8f8d2.json"
}
```

Validation helper:
- `python3 scripts/contract_validate.py contracts/lucy_input_v1.schema.json sample.json`

## Outbox Envelope: `lucy_output_v1.schema.json`
Required fields:
- `version`: always `"lucy_output_v1"`
- `ok`: execution result
- `correlation_id`: canonical id for this event
- `status`: `"ok" | "error" | "pending"`
- `response_ts`: RFC3339 timestamp

Optional fields:
- `result`: object with successful output
- `error`: structured error payload (`rc`, `message`, `stderr`, `stage`)

Outbox naming:
- source of truth: `ipc/outbox/<correlation_id>.json`
- legacy compatibility (temporary): `ipc/outbox/res_<correlation_id>.json`
