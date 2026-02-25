# Voice Runbook (DC)

## Objetivo
Diagnóstico diario en menos de 1 minuto para voz, TTS y barge-in.

## 3 comandos

```bash
# 1) Estado consolidado de voz y barge-in
curl -s http://127.0.0.1:8787/api/voice | python3 -m json.tool | sed -n '1,220p'

# 2) Cola/poll STT (actividad de escucha)
curl -s "http://127.0.0.1:8787/api/stt/poll?session_id=debug&limit=5" | python3 -m json.tool

# 3) Logs críticos de servicios
journalctl --user -u openclaw-direct-chat.service -u openclaw-gateway.service -n 120 --no-pager
```

## Qué mirar
- `/api/voice`
  - `enabled`, `stt_enabled`, `stt_running`
  - `barge_in_mode` (esperado: `speech`)
  - `barge_in_last_detail` (debe incluir `vad`, `rms`, `threshold`, `frames`, `cooldown`)
  - `last_status.ok=true` y `server_ok=true`
- `/api/stt/poll`
  - eventos recientes en `items` cuando VOZ ON
- logs
  - sin `model not found`
  - sin loops/restarts continuos
