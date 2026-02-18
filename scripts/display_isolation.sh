#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${HOME}/.openclaw/display_isolation"
STATE_FILE="${STATE_DIR}/state.env"
LOG_DIR="${STATE_DIR}/logs"
mkdir -p "$STATE_DIR" "$LOG_DIR"

need_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing dependency '$1'" >&2
    exit 1
  }
}

usage() {
  cat <<'USAGE'
Usage:
  scripts/display_isolation.sh up <visible|headless>
  scripts/display_isolation.sh exec -- <command...>
  scripts/display_isolation.sh run <visible|headless> -- <command...>
  scripts/display_isolation.sh status
  scripts/display_isolation.sh down

Notes:
  - visible: starts Xephyr window + nested GNOME Shell (unstable in some hosts).
  - headless: starts Xvfb + nested GNOME Shell (no visible window).
  - run: starts, executes, and stops automatically.
  - Set ISOLATED_KEEP_UP=1 to keep the display up after run.
  - Set ISO_ALLOW_UNSTABLE_VISIBLE=1 to allow visible mode.
USAGE
}

is_pid_running() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

find_free_display() {
  local base="${ISO_DISPLAY_BASE:-110}"
  local max="${ISO_DISPLAY_MAX:-149}"
  local n
  for n in $(seq "$base" "$max"); do
    if [[ ! -S "/tmp/.X11-unix/X${n}" && ! -e "/tmp/.X${n}-lock" ]]; then
      echo ":$n"
      return 0
    fi
  done
  return 1
}

load_state() {
  if [[ ! -f "$STATE_FILE" ]]; then
    return 1
  fi
  # shellcheck disable=SC1090
  . "$STATE_FILE"
}

write_state() {
  local mode="$1"
  local display="$2"
  local server_pid="$3"
  local wm_pid="$4"
  local server_log="$5"
  local wm_log="$6"
  cat >"$STATE_FILE" <<EOF
STATE_MODE='$mode'
STATE_DISPLAY='$display'
STATE_SERVER_PID='$server_pid'
STATE_WM_PID='$wm_pid'
STATE_SERVER_LOG='$server_log'
STATE_WM_LOG='$wm_log'
STATE_STARTED_AT='$(date -Iseconds)'
EOF
}

clear_state() {
  rm -f "$STATE_FILE"
}

wait_wm_ready() {
  local display="$1"
  local tries=80
  while (( tries > 0 )); do
    if DISPLAY="$display" wmctrl -d >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.15
    tries=$((tries - 1))
  done
  return 1
}

start_display() {
  local mode="$1"
  need_bin wmctrl
  need_bin gnome-shell
  need_bin dbus-run-session

  if load_state; then
    if is_pid_running "${STATE_SERVER_PID:-}" && is_pid_running "${STATE_WM_PID:-}"; then
      echo "ISOLATED_DISPLAY_UP mode=${STATE_MODE} display=${STATE_DISPLAY} server_pid=${STATE_SERVER_PID} wm_pid=${STATE_WM_PID}"
      return 0
    fi
    clear_state
  fi

  local display="${ISO_DISPLAY:-}"
  if [[ -z "$display" ]]; then
    display="$(find_free_display || true)"
  fi
  if [[ -z "$display" ]]; then
    echo "ERROR: no free display found in range ${ISO_DISPLAY_BASE:-110}-${ISO_DISPLAY_MAX:-149}" >&2
    exit 1
  fi

  local width="${ISO_WIDTH:-1600}"
  local height="${ISO_HEIGHT:-900}"
  local stamp
  stamp="$(date +%s)"
  local server_log="${LOG_DIR}/${mode}_server_${stamp}.log"
  local wm_log="${LOG_DIR}/${mode}_wm_${stamp}.log"
  local server_pid=""
  local wm_pid=""

  case "$mode" in
    visible)
      if [[ "${ISO_ALLOW_UNSTABLE_VISIBLE:-0}" != "1" ]]; then
        echo "ERROR: visible mode is disabled by default on this host (unstable Xephyr backend)." >&2
        echo "Use headless mode, or set ISO_ALLOW_UNSTABLE_VISIBLE=1 to force visible mode." >&2
        exit 1
      fi
      need_bin Xephyr
      Xephyr "$display" -screen "${width}x${height}" -ac -br -reset -title "${ISO_TITLE:-Cunningham Isolated Display}" >"$server_log" 2>&1 &
      server_pid="$!"
      sleep 1.0
      ;;
    headless)
      need_bin Xvfb
      Xvfb "$display" -screen 0 "${width}x${height}x24" >"$server_log" 2>&1 &
      server_pid="$!"
      sleep 0.8
      ;;
    *)
      echo "ERROR: invalid mode '$mode' (use visible|headless)" >&2
      exit 2
      ;;
  esac

  DISPLAY="$display" dbus-run-session -- gnome-shell --x11 --replace >"$wm_log" 2>&1 &
  wm_pid="$!"

  if ! wait_wm_ready "$display"; then
    kill "$wm_pid" >/dev/null 2>&1 || true
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$wm_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    echo "ERROR: nested window manager not ready on $display" >&2
    echo "  server_log=$server_log" >&2
    echo "  wm_log=$wm_log" >&2
    exit 1
  fi

  write_state "$mode" "$display" "$server_pid" "$wm_pid" "$server_log" "$wm_log"
  echo "ISOLATED_DISPLAY_UP mode=$mode display=$display server_pid=$server_pid wm_pid=$wm_pid"
  echo "ISOLATED_DISPLAY_LOGS server_log=$server_log wm_log=$wm_log"
}

stop_display() {
  if ! load_state; then
    echo "ISOLATED_DISPLAY_DOWN already_stopped"
    return 0
  fi

  local mode="${STATE_MODE:-unknown}"
  local display="${STATE_DISPLAY:-}"
  local server_pid="${STATE_SERVER_PID:-}"
  local wm_pid="${STATE_WM_PID:-}"

  if is_pid_running "$wm_pid"; then
    kill "$wm_pid" >/dev/null 2>&1 || true
    wait "$wm_pid" 2>/dev/null || true
  fi
  if is_pid_running "$server_pid"; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" 2>/dev/null || true
  fi

  clear_state
  echo "ISOLATED_DISPLAY_DOWN mode=$mode display=$display"
}

status_display() {
  if ! load_state; then
    echo "ISOLATED_DISPLAY_STATUS stopped"
    return 0
  fi
  local running="1"
  if ! is_pid_running "${STATE_SERVER_PID:-}"; then
    running="0"
  fi
  if ! is_pid_running "${STATE_WM_PID:-}"; then
    running="0"
  fi
  echo "ISOLATED_DISPLAY_STATUS running=$running mode=${STATE_MODE:-unknown} display=${STATE_DISPLAY:-} server_pid=${STATE_SERVER_PID:-} wm_pid=${STATE_WM_PID:-}"
  echo "ISOLATED_DISPLAY_LOGS server_log=${STATE_SERVER_LOG:-} wm_log=${STATE_WM_LOG:-}"
}

exec_in_display() {
  if ! load_state; then
    echo "ERROR: isolated display is not running" >&2
    exit 1
  fi
  if ! is_pid_running "${STATE_SERVER_PID:-}" || ! is_pid_running "${STATE_WM_PID:-}"; then
    echo "ERROR: isolated display state is stale; run 'scripts/display_isolation.sh down' first" >&2
    exit 1
  fi
  if [[ $# -lt 1 ]]; then
    echo "ERROR: missing command to execute" >&2
    exit 2
  fi
  DISPLAY="${STATE_DISPLAY}" "$@"
}

run_in_display() {
  local mode="$1"
  shift
  start_display "$mode"
  local rc=0
  set +e
  exec_in_display "$@"
  rc=$?
  set -e
  if [[ "${ISOLATED_KEEP_UP:-0}" != "1" ]]; then
    stop_display
  fi
  return "$rc"
}

cmd="${1:-}"
case "$cmd" in
  up)
    mode="${2:-}"
    if [[ -z "$mode" ]]; then
      usage
      exit 2
    fi
    start_display "$mode"
    ;;
  exec)
    shift
    if [[ "${1:-}" == "--" ]]; then
      shift
    fi
    exec_in_display "$@"
    ;;
  run)
    mode="${2:-}"
    if [[ -z "$mode" ]]; then
      usage
      exit 2
    fi
    shift 2
    if [[ "${1:-}" == "--" ]]; then
      shift
    fi
    run_in_display "$mode" "$@"
    ;;
  status)
    status_display
    ;;
  down)
    stop_display
    ;;
  *)
    usage
    exit 2
    ;;
esac
