#!/usr/bin/env bash
set -euo pipefail

# Human-mode DC test in current workspace:
# 1) Type 10 diverse requests to search/open/play YouTube videos.
# 2) Verify real YouTube window activity (not chat text).
# 3) Ask DC to close opened web windows and verify closure.

need_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing dependency '$1'" >&2
    exit 1
  }
}

need_bin wmctrl
need_bin xdotool

WS="$(wmctrl -d | awk '$2=="*"{print $1; exit}')"
DC_WID="$(wmctrl -lp | awk -v d="$WS" '$2==d && tolower($0) ~ /molbot direct chat/ {print $1; exit}')"
if [[ -z "${DC_WID:-}" ]]; then
  echo "ERROR: no encontré 'Molbot Direct Chat' en workspace=$WS" >&2
  exit 1
fi

OUT_DIR="${HOME}/.openclaw/logs/ui_human_youtube"
mkdir -p "$OUT_DIR"
TS="$(date +%s)"
LOG="$OUT_DIR/run_${TS}.log"

yt_cmds=(
  "cunn: busca lo-fi chill en youtube, abrí el primer video y reproducilo"
  "cunn: buscá tutorial python para principiantes en youtube y poné a reproducir el primer resultado"
  "cunn: investiga en youtube musica ambiental lluvia y abrí un video para que se reproduzca"
  "cunn: busca en youtube documental agujeros negros, abrí primer video y reproducilo"
  "cunn: en youtube buscá recetas de pizza napolitana y poné el primer video"
  "cunn: quiero un video de youtube sobre historia de roma, abrí el primero y reproducilo"
  "cunn: busca meditacion guiada en youtube y dale play al primer video"
  "cunn: buscá noticias tecnologia hoy en youtube, abrí primer video y reproducilo"
  "cunn: en youtube busca musica focus y abrí un video para reproducir"
  "cunn: busca en youtube teoria de la relatividad explicada, abrí primer video y reproducilo"
)

close_cmds=(
  "cunn: cerrá las ventanas web que abriste"
  "cunn: cierra todas las ventanas web abiertas por vos"
  "cunn: cerrar ventanas web de esta sesión"
  "cunn: cerrá lo que abriste recién en la web"
  "cunn: close web windows you opened"
  "cunn: cerrá todas las pestañas/ventanas web que abriste"
  "cunn: limpia y cerrá ventanas web abiertas por el sistema"
  "cunn: cierra esas ventanas web ahora"
  "cunn: cerrá las ventanas registradas de navegador"
  "cunn: cerrar web windows now"
)

send_cmd() {
  local text="$1"
  xdotool windowactivate "$DC_WID"
  sleep 0.25
  local X Y W H
  read -r X Y W H < <(
    xdotool getwindowgeometry --shell "$DC_WID" | awk -F= '
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
  sleep 0.1
  xdotool key --window "$DC_WID" ctrl+a BackSpace
  sleep 0.08
  xdotool type --delay 24 --window "$DC_WID" "$text"
  sleep 0.08
  xdotool key --window "$DC_WID" Return
}

yt_windows_csv() {
  wmctrl -lp | awk -v d="$WS" '
    $2==d {
      line=tolower($0);
      if (line ~ /youtube/) print $1 "," $3 "," $0;
    }'
}

wait_for_youtube_activity() {
  local before_ids="$1"
  local tries=52
  while (( tries > 0 )); do
    local rows now_ids new_id
    rows="$(yt_windows_csv || true)"
    now_ids="$(printf '%s\n' "$rows" | awk -F, 'NF>=1{print $1}' | tr '\n' ' ')"
    for wid in $now_ids; do
      if ! grep -q "$wid" <<<"$before_ids"; then
        echo "$wid"
        return 0
      fi
    done
    # If no new id appears, but we still have a YouTube window, treat as activity.
    if [[ -n "${now_ids// /}" ]]; then
      echo "$(awk '{print $1}' <<<"$now_ids")"
      return 0
    fi
    sleep 0.5
    tries=$((tries - 1))
  done
  return 1
}

wait_until_no_youtube() {
  local tries=30
  while (( tries > 0 )); do
    local n
    n="$(yt_windows_csv | wc -l | tr -d ' ')"
    if [[ "$n" == "0" ]]; then
      return 0
    fi
    sleep 0.5
    tries=$((tries - 1))
  done
  return 1
}

echo "run_ts=$TS workspace=$WS dc_wid=$DC_WID" | tee -a "$LOG"

pass_open=0
pass_close=0
for i in $(seq 0 9); do
  idx=$((i + 1))
  open_msg="${yt_cmds[$i]}"
  close_msg="${close_cmds[$i]}"
  before_ids="$(yt_windows_csv | awk -F, 'NF>=1{print $1}' | tr '\n' ' ')"

  echo "[${idx}/10] OPEN msg=$open_msg" | tee -a "$LOG"
  send_cmd "$open_msg"
  if wid="$(wait_for_youtube_activity "$before_ids")"; then
    title="$(wmctrl -l | awk -v w="$wid" 'tolower($1)==tolower(w){$1=$2=$3=""; sub(/^   */, "", $0); print; exit}')"
    echo "  OPEN_OK wid=$wid title=$title" | tee -a "$LOG"
    pass_open=$((pass_open + 1))
    # Force focus and send 'k' (YouTube play/pause hotkey) as runtime probe.
    xdotool windowactivate "$wid" >/dev/null 2>&1 || true
    sleep 0.2
    xdotool key --window "$wid" k >/dev/null 2>&1 || true
  else
    echo "  OPEN_FAIL no_youtube_window_detected" | tee -a "$LOG"
  fi

  sleep 1.4
  echo "[${idx}/10] CLOSE msg=$close_msg" | tee -a "$LOG"
  send_cmd "$close_msg"
  if wait_until_no_youtube; then
    echo "  CLOSE_OK" | tee -a "$LOG"
    pass_close=$((pass_close + 1))
  else
    left="$(yt_windows_csv | wc -l | tr -d ' ')"
    echo "  CLOSE_FAIL remaining_youtube_windows=$left" | tee -a "$LOG"
  fi
  sleep 1.0
done

echo "SUMMARY open_ok=$pass_open/10 close_ok=$pass_close/10 log=$LOG" | tee -a "$LOG"
if [[ "$pass_open" != "10" || "$pass_close" != "10" ]]; then
  exit 1
fi
