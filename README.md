# Cunningham Espejo

Repositorio operativo de `Direct Chat` (DC) y Cunningham (CUN/Lucy), con foco en voz local, routing de modelos y validación reproducible.

Glosario:
- `DC` = `Molbot Direct Chat`
- `CUN` / `Lucy` = IA Cunningham

## Estado actual
- Voz en DC integrada sin cambios visuales (STT local + TTS + anti-eco).
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
2. Confirmar que durante TTS no se autocapture eco.
3. VOZ OFF, confirmar que no hay nuevas capturas.
4. Revisar `journalctl -f` sin errores críticos.

## Operación diaria
Servicios:
- `openclaw-direct-chat.service`
- `openclaw-gateway.service`

Comandos útiles:

```bash
systemctl --user status openclaw-direct-chat.service --no-pager
systemctl --user status openclaw-gateway.service --no-pager
systemctl --user restart openclaw-direct-chat.service openclaw-gateway.service
journalctl --user -u openclaw-direct-chat.service -n 200 --no-pager
journalctl --user -u openclaw-gateway.service -n 200 --no-pager
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

## Documentación clave
- `DOCS/PLAN.md` — roadmap operativo vigente (DC + Espejo-de-Lucy).
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
