# Cunningham Espejo

Repositorio operativo de `Direct Chat` (DC) y Cunningham (CUN/Lucy), con foco en voz local, routing de modelos y validación reproducible.

Glosario:
- `DC` = `Molbot Direct Chat`
- `CUN` / `Lucy` = IA Cunningham

## Estado actual
- Voz en DC integrada sin cambios visuales (STT local + TTS + anti-eco).
- Barge-in en modo **fluido por voz humana** durante TTS (no requiere keyword obligatoria).
- `GET /api/voice` es de solo lectura.
- El estado STT se gobierna con `POST /api/voice` y `GET /api/stt/poll`.
- Router con fallback local solo a modelos realmente instalados.

## Botón rojo (obligatorio)
Ejecutar:

```bash
./scripts/test_smoke.sh
```

Incluye:
- `py_compile`
- `unittest` focalizado
- `pytest` focalizado

Además, para cambios de voz/sesión/guardrails/workspace/router, ejecutar prueba humana en DC:
1. VOZ ON, hablar 5 frases.
2. Durante TTS: hablar encima y confirmar corte de playback (< 0.5s).
3. VOZ OFF, confirmar que no hay nuevas capturas.
4. Revisar `journalctl -f` sin errores críticos.

## Operación diaria
Servicios:
- `openclaw-direct-chat.service`
- `openclaw-gateway.service`

Runbook mínimo (3 comandos):

```bash
# 1) ¿está escuchando/hablando/barge-ineando?
curl -s http://127.0.0.1:8787/api/voice | python3 -m json.tool | sed -n "1,220p"

# 2) ¿está capturando/transcribiendo STT?
curl -s "http://127.0.0.1:8787/api/stt/poll?session_id=debug&limit=5" | python3 -m json.tool

# 3) ¿hay errores de servicios?
journalctl --user -u openclaw-direct-chat.service -u openclaw-gateway.service -n 120 --no-pager
```

## Preflight de voz (STT local)
Si VOZ ON habla pero no escucha micrófono:

1. Confirmar que Direct Chat corre desde este repo:
```bash
systemctl --user cat openclaw-direct-chat.service
```
`WorkingDirectory` y `ExecStart` deben apuntar a `cunningham-Espejo`.

2. Instalar dependencias STT:
```bash
python3 -m pip install --user --break-system-packages -r scripts/requirements-direct-chat-stt.txt
```

3. Reiniciar servicio:
```bash
systemctl --user daemon-reload
systemctl --user restart openclaw-direct-chat.service
```

4. Verificar endpoint STT:
```bash
curl -s 'http://127.0.0.1:8787/api/stt/poll?session_id=debug&limit=1'
```


## Barge-in (modo fluido)
Semántica operativa:
- Barge-in corta TTS por **actividad de voz humana** detectada durante playback.
- No depende de decir una keyword exacta para funcionar.
- `DIRECT_CHAT_BARGEIN_KEYWORDS` se usa para telemetría (`barge_in_last_keyword`) y trazabilidad.

Diagnóstico rápido:
```bash
curl -s http://127.0.0.1:8787/api/voice | python3 -m json.tool | sed -n '1,200p'
```
Buscar:
- `barge_in_mode: "speech"`
- `barge_in_last_detail` con detalle explícito (`vad`, `rms`, `threshold`, `frames`, `cooldown`).

## Configuración de barge-in
Variables útiles (opcionales):
- `DIRECT_CHAT_BARGEIN_ENABLED` (`true`/`false`, default `true`)
- `DIRECT_CHAT_BARGEIN_KEYWORDS` (lista CSV; para telemetría/intent)
- `DIRECT_CHAT_BARGEIN_SAMPLE_RATE` (default `16000`)
- `DIRECT_CHAT_BARGEIN_FRAME_MS` (default `30`)
- `DIRECT_CHAT_BARGEIN_VAD_MODE` (0..3, default `2`)
- `DIRECT_CHAT_BARGEIN_MIN_VOICE_FRAMES` (default `8`)
- `DIRECT_CHAT_BARGEIN_RMS_THRESHOLD` (default `0.012`)
- `DIRECT_CHAT_BARGEIN_COOLDOWN_SEC` (default `1.5`)

## Documentación clave
- `DOCS/PLAN.md` — roadmap operativo vigente (DC + Espejo-de-Lucy).
- `DOCS/VOICE_RUNBOOK.md` — runbook mínimo de operación/diagnóstico de voz.
- `docs/SECURITY_CHECKLIST.md` — checklist de seguridad.
- `docs/INTEGRATIONS.md` — integraciones/pinning.
- `DOCS/UX_SPANISH_VOICE.md` — guía de UX de voz.
- `docs/LUCY_UI_PANEL.md` — panel funcional del gateway.

## Scripts importantes
- `scripts/test_smoke.sh` — validación mínima obligatoria.
- `scripts/model_router.sh` — selección y fallback de modelo.
- `scripts/verify_all.sh` — verificación general legacy.
- `scripts/host_audit_full.sh` — snapshot de host.

## Seguridad
Por defecto, `exec`/`bash` deben mantenerse denegados en la política local de OpenClaw para evitar ejecución arbitraria.
