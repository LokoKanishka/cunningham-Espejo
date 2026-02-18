#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'USAGE'
Usage:
  scripts/api_youtube_isolated.sh [headless|visible] [seq|stress10]

Examples:
  scripts/api_youtube_isolated.sh headless seq
  scripts/api_youtube_isolated.sh visible seq
  ISOLATED_KEEP_UP=1 scripts/api_youtube_isolated.sh visible stress10

Notes:
  - Runs YouTube API tests inside an isolated display (no host workspace spill).
  - Uses DIRECT_CHAT_CHROME_USER_DATA_DIR (or ~/.openclaw/chrome_isolated/google-chrome).
  - visible mode requires ISO_ALLOW_UNSTABLE_VISIBLE=1.
USAGE
}

mode="${1:-headless}"
suite="${2:-seq}"

case "$mode" in
  headless|visible) ;;
  *)
    usage
    echo "ERROR: invalid mode '$mode'" >&2
    exit 2
    ;;
esac

if [[ "$mode" == "visible" && "${ISO_ALLOW_UNSTABLE_VISIBLE:-0}" != "1" ]]; then
  echo "ERROR: visible mode is disabled by default on this host (unstable backend)." >&2
  echo "Run with ISO_ALLOW_UNSTABLE_VISIBLE=1 to force it." >&2
  exit 1
fi

target_script=""
case "$suite" in
  seq)
    target_script="./scripts/api_youtube_play_pause_play_stop_close.sh"
    ;;
  stress10)
    target_script="./scripts/api_youtube_internal_10.sh"
    ;;
  *)
    usage
    echo "ERROR: invalid suite '$suite'" >&2
    exit 2
    ;;
esac

if [[ ! -x "$target_script" ]]; then
  echo "ERROR: target script is not executable: $target_script" >&2
  exit 1
fi

chrome_ud="${DIRECT_CHAT_CHROME_USER_DATA_DIR:-$HOME/.openclaw/chrome_isolated/google-chrome}"
mkdir -p "$chrome_ud"

profile_hint="${DIRECT_CHAT_PROFILE_HINT:-diego}"
profile_dir="$(python3 - "$profile_hint" <<'PY'
import json
import os
import sys

hint = (sys.argv[1] if len(sys.argv) > 1 else "diego").strip().lower()
root = os.path.expanduser("~/.config/google-chrome")
local_state = os.path.join(root, "Local State")

if os.path.exists(local_state):
    try:
        data = json.load(open(local_state, "r", encoding="utf-8"))
        info = data.get("profile", {}).get("info_cache", {})
        for key, value in info.items():
            if str(value.get("name", "")).strip().lower() == hint:
                print(key)
                raise SystemExit(0)
        for key in info.keys():
            if str(key).strip().lower() == hint:
                print(key)
                raise SystemExit(0)
    except Exception:
        pass

if os.path.isdir(os.path.join(root, hint)):
    print(hint)
else:
    print("Default")
PY
)"

src_root="$HOME/.config/google-chrome"
if [[ -d "$src_root/$profile_dir" && ! -d "$chrome_ud/$profile_dir" ]]; then
  cp -f "$src_root/Local State" "$chrome_ud/Local State" >/dev/null 2>&1 || true
  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude=Cache/ \
      --exclude='Code Cache/' \
      --exclude=GPUCache/ \
      --exclude=Crashpad/ \
      --exclude=BrowserMetrics/ \
      --exclude=SingletonCookie \
      --exclude=SingletonLock \
      --exclude=SingletonSocket \
      "$src_root/$profile_dir/" "$chrome_ud/$profile_dir/" >/dev/null 2>&1 || true
  else
    cp -a "$src_root/$profile_dir" "$chrome_ud/" >/dev/null 2>&1 || true
  fi
fi

echo "API_YOUTUBE_ISOLATED mode=$mode suite=$suite"
echo "API_YOUTUBE_ISOLATED env DIRECT_CHAT_CHROME_USER_DATA_DIR=$chrome_ud DIRECT_CHAT_PROFILE_HINT=$profile_hint profile_dir=$profile_dir"

./scripts/display_isolation.sh run "$mode" -- \
  env \
    DIRECT_CHAT_CHROME_USER_DATA_DIR="$chrome_ud" \
    "$target_script"
