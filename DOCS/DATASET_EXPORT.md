# Dataset Export (JSONL) v0.1

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

## CLI

```bash
python3 scripts/export_history_jsonl.py \
  --in ~/.openclaw/direct_chat_histories \
  --out ~/.openclaw/exports/dc_pairs.jsonl \
  --mode pairs \
  --min-chars 1 \
  --max-sessions 0 \
  --max-lines 0 \
  --since-days 0 \
  --max-completion-chars 0
```

- `--max-sessions 0`: sin límite.
- `--max-lines 0`: sin límite de líneas exportadas.
- `--since-days 0`: sin filtro temporal.
- `--max-completion-chars 0`: sin límite de largo para `completion`.

## Resumen de calidad

El script imprime JSON con métricas:

- `rows`, `sessions_scanned`, `sessions_with_rows`
- `files_invalid_json`
- `dropped.empty_dropped`
- `dropped.orphan_user_dropped`
- `dropped.user_overwritten`
- `dropped.assistant_without_user_dropped`
- `dropped.short_prompt_dropped`, `dropped.short_completion_dropped`
- `dropped.completion_truncated`
- `pairs_per_backend_model` (breakdown por backend/model)
- `top_sessions` (top 10 por cantidad de líneas exportadas)

## Verificación

Verificación sintética (CI/smoke):

```bash
./scripts/verify_history_export.sh
```

Verificación real no destructiva (solo resumen):

```bash
./scripts/verify_history_export_real.sh
```
