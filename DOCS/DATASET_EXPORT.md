# Dataset Export (JSONL) v0

Exporta conversaciones de Direct Chat desde `~/.openclaw/direct_chat_histories` a JSONL para entrenamiento.

## Entrada

Cada archivo de historial es un array JSON con items:

```json
{"role":"user|assistant","content":"..."}
```

## Limpieza aplicada

- Ignora `content` vacío/whitespace.
- Ignora roles distintos de `user` y `assistant`.
- Forma pares `user -> assistant` (assistant siguiente no vacío).
- Descarta users sin assistant posterior.
- Aplica `--min-chars` a prompt y completion.

## Salidas

`--mode pairs`:

```json
{"session_id":"...","backend":"cloud","model":"...","source_file":"...","prompt":"...","completion":"..."}
```

`--mode messages`:

```json
{"session_id":"...","backend":"cloud","model":"...","source_file":"...","messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

## Uso

```bash
python3 scripts/export_history_jsonl.py \
  --in ~/.openclaw/direct_chat_histories \
  --out ~/.openclaw/exports/dc_pairs.jsonl \
  --mode pairs \
  --min-chars 1 \
  --max-sessions 0
```

`--max-sessions 0` significa sin límite.

## Verificación rápida

```bash
./scripts/verify_history_export.sh
```
