# Baselines de Audio/VOZ (STT)

## BASE SEGURA (no romper)
Tag: audio-safe-20260225
Branch: baseline/audio-safe
Commit: f251cb30c271a608b74c2a5b985f185786331ca3

Incluye:
- STT chat hands-free (voz -> mensaje -> respuesta)
- Bridge VOZ->CHAT server-side (no depende de UI/Chrome focus)
- chat_seq + /api/chat/poll + render incremental
- filtros anti "suscribite/subscribe"
- modo dictado con segmentacion tolerante
- preamp/AGC opt-in (stt ganancia / stt agc)

### Si un cambio de audio rompe la voz
Crear PR de rollback a baseline (sin reescribir historia):
1) git fetch --tags origin
2) git checkout -b hotfix/restore-audio-baseline
3) git reset --hard audio-safe-20260225
4) correr tests + smoke
5) abrir PR

## Regla operativa para cambios de audio/STT
- Todo cambio de audio/STT debe correr `pytest` y `./scripts/test_smoke.sh`.
- Si falla o "no escucha", restaurar desde `audio-safe-20260225` y volver a iterar.
