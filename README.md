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
- Reader Mode v0 disponible en `/api/reader/session/*` con cursor persistente y replay de pendiente tras reinicio.

## Botón rojo (obligatorio)
Ejecutar:

```bash
./scripts/test_smoke.sh
./scripts/verify_reader_mode.sh
```

Incluye:
- `py_compile`
- `unittest` focalizado
- `pytest` focalizado
- Flujo Reader Mode v0 (`session/start`, `session/next`, `session/commit`, `session/barge_in`) con prueba de reinicio.

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
- `DOCS/READER_MODE.md` — contrato Reader Mode v0 y verificador reproducible.
- `DOCS/DC_READER_GUARDRAILS_Y_BITACORA.md` — indice tecnico + reglas de no romper + bitacora viva de reader/voz/UI.
- `docs/SECURITY_CHECKLIST.md` — checklist de seguridad.
- `docs/INTEGRATIONS.md` — integraciones/pinning.
- `DOCS/UX_SPANISH_VOICE.md` — guía de UX de voz.
- `docs/LUCY_UI_PANEL.md` — panel funcional del gateway.

## Scripts importantes
- `scripts/test_smoke.sh` — validación mínima obligatoria.
- `scripts/verify_reader_mode.sh` — botón rojo de Reader Mode v0 (cursor + persistencia + reinicio + barge-in).
- `scripts/verify_stt_memory.sh` — guardarraíl de memoria STT (baseline de defaults + tests STT focalizados).
- `scripts/model_router.sh` — selección y fallback de modelo.
- `scripts/verify_all.sh` — verificación general legacy.
- `scripts/host_audit_full.sh` — snapshot de host.

## Memoria de ajustes STT
- Workflow: `DOCS/STT_MEMORY_WORKFLOW.md`
- Baseline vigente de defaults: `DOCS/STT_BASELINE_CURRENT.json`
- Regenerar baseline (solo si el cambio es intencional): `python3 scripts/stt_memory_snapshot.py snapshot --write`

## Seguridad
Por defecto, `exec`/`bash` deben mantenerse denegados en la política local de OpenClaw para evitar ejecución arbitraria.

Controles operativos:
- `./scripts/mode_safe.sh` aplica perfil seguro con `exec` fuera de `allow` y explícitamente en `deny`.
- `./scripts/policy_engine.sh check` falla si `mode_safe` vuelve a permitir `exec` o deja de denegarlo.

## Reverse proxy y trusted proxies (gateway)
- El gateway está configurado como **local-only** (`gateway.bind: loopback`) y autenticado por token.
- Por eso, `gateway.trustedProxies` puede quedar vacío sin riesgo práctico en el uso actual.
- Si se expone la UI/HTTP por **reverse proxy** (Caddy/Nginx/Traefik), se debe configurar `gateway.trustedProxies` con las IPs del/los proxy para evitar spoofing de headers.
