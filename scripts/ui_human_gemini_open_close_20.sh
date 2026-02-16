#!/usr/bin/env bash
set -euo pipefail

# Human-mode UI test:
# - Uses visible Molbot Direct Chat window in current workspace.
# - Types commands like a person (xdotool) and sends with Enter.
# - 10 diverse "open Gemini" + 10 diverse "close windows" requests.

need_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing dependency '$1'" >&2
    exit 1
  }
}

need_bin wmctrl
need_bin xdotool

cur_workspace="$(wmctrl -d | awk '$2=="*"{print $1; exit}')"
molbot_wid="$(wmctrl -lp | awk -v d="$cur_workspace" '$2==d && tolower($0) ~ /molbot direct chat/ {print $1; exit}')"
if [[ -z "${molbot_wid:-}" ]]; then
  echo "ERROR: no encontré 'Molbot Direct Chat' en el workspace actual (${cur_workspace})." >&2
  exit 1
fi

opens=(
  "abrí gemini"
  "abrime gemini por favor"
  "quiero abrir gemini ahora"
  "abre gemini en chrome"
  "necesito que abras gemini"
  "abrir gemini"
  "abrí gemin"
  "podés abrir gemini?"
  "lanzá gemini"
  "ir a gemini"
)

closes=(
  "cerrá las ventanas web que abriste"
  "cerrar ventanas web abiertas por vos"
  "cierra todas las ventanas web que abriste"
  "close web windows you opened"
  "cerrá lo que abriste recien"
  "cerra las ventanas que abriste"
  "cerrar las ventanas web de esta sesion"
  "cierra esas ventanas por favor"
  "cerrá las ventanas abiertas por el sistema"
  "cerrar web windows now"
)

send_cmd() {
  local text="$1"
  xdotool windowactivate "$molbot_wid"
  sleep 0.30

  local X Y W H
  read -r X Y W H < <(
    xdotool getwindowgeometry --shell "$molbot_wid" | awk -F= '
      /^X=/{x=$2}
      /^Y=/{y=$2}
      /^WIDTH=/{w=$2}
      /^HEIGHT=/{h=$2}
      END{print x, y, w, h}
    '
  )

  local ix iy
  ix=$((X + (W * 40 / 100)))
  iy=$((Y + (H * 86 / 100)))

  xdotool mousemove "$ix" "$iy" click 1
  sleep 0.10
  xdotool key --window "$molbot_wid" ctrl+a BackSpace
  sleep 0.06
  xdotool type --delay 30 --window "$molbot_wid" "$text"
  sleep 0.10
  xdotool key --window "$molbot_wid" Return
}

n=0
for i in $(seq 0 9); do
  n=$((n + 1))
  echo "[$n/20] OPEN: ${opens[$i]}"
  send_cmd "${opens[$i]}"
  sleep 5.8

  n=$((n + 1))
  echo "[$n/20] CLOSE: ${closes[$i]}"
  send_cmd "${closes[$i]}"
  sleep 5.8
done

echo "DONE wid=${molbot_wid} workspace=${cur_workspace} total=20"
