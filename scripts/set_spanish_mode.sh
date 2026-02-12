#!/usr/bin/env bash
set -euo pipefail

ws="$HOME/.openclaw/workspace"
file="$ws/USER.md"
mkdir -p "$ws"

if [ -f "$file" ]; then
  cp "$file" "$file.bak.$(date +%Y%m%d_%H%M%S)"
fi

cat > "$file" <<'MD'
# Preferencias de Usuario

- Respondé siempre en castellano (español neutral, claro y directo).
- Si el usuario pide comandos, devolvelos listos para copiar/pegar.
- Priorizá soluciones prácticas y verificables.
- Si hay ambigüedad, proponé una opción recomendada y una alternativa.
MD

echo "SPANISH_MODE_OK:$file"
