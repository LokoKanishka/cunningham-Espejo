# STT Memory Workflow

Objetivo: evitar que un ajuste en STT desacomode valores ya estabilizados.

## Regla

Antes y despues de tocar `scripts/molbot_direct_chat/stt_local.py`, correr:

```bash
./scripts/verify_stt_memory.sh
```

Este script valida:
- que los defaults de `STTConfig` no cambiaron accidentalmente (baseline JSON),
- y en modo estricto corre tests STT focalizados.

Modo estricto:

```bash
STT_MEMORY_STRICT=1 ./scripts/verify_stt_memory.sh
```

## Baseline actual

Archivo fuente de verdad:
- `DOCS/STT_BASELINE_CURRENT.json`

Se genera desde el codigo real con:

```bash
python3 scripts/stt_memory_snapshot.py snapshot --write
```

## Cuando SI actualizar baseline

Actualizar `DOCS/STT_BASELINE_CURRENT.json` solo si el cambio de defaults es intencional y probado.

Checklist minimo:
1. `./scripts/verify_stt_memory.sh`
2. `./scripts/verify_stt_barge_in_smoke.sh`
3. prueba humana en DC (VOZ ON/OFF y corte durante TTS).

## Bitacora corta por cambio

Agregar una entrada en `DOCS/DC_READER_GUARDRAILS_Y_BITACORA.md`:

```text
### YYYY-MM-DD
- Problema observado:
- Causa raiz:
- Parametros tocados:
- Verificacion automatica:
- Verificacion humana:
- Riesgo residual:
```
