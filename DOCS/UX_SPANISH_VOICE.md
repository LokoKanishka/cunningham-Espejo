# UX: Consola pro + Castellano + Voz

## 1) Consola profesional
Comando:

```bash
./scripts/console_pro.sh
```

Abre una vista tipo NOC (si hay tmux):
- verify gateway
- status general
- logs en vivo

## 2) Modo castellano persistente
Comando:

```bash
./scripts/set_spanish_mode.sh
```

Esto escribe `~/.openclaw/workspace/USER.md` para forzar respuestas en español.

## 3) Hablarle / escuchar respuesta
Comando:

```bash
./scripts/chat_voice_es.sh "tu pregunta"
```

- Envía mensaje al agente en castellano
- Intenta leer respuesta con `spd-say` o `espeak`

## Nota
Para dictado de voz a texto usá el dictado del sistema operativo (GNOME/VS Code), y este script te da salida por voz.
