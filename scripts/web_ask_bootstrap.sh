#!/usr/bin/env bash
set -euo pipefail

SITE="${1:-chatgpt}"
PROFILE_NAME="${2:-diego}"

case "$SITE" in
  chatgpt) URL="https://chatgpt.com/" ;;
  gemini) URL="https://gemini.google.com/app" ;;
  *)
    echo "Uso: $0 [chatgpt|gemini] [profile_name]" >&2
    exit 2
    ;;
esac

SRC_ROOT="$HOME/.config/google-chrome"
DST_ROOT="$HOME/.openclaw/web_ask_shadow/google-chrome"
LOCAL_STATE="$SRC_ROOT/Local State"

PROFILE_DIR="$(python3 - "$PROFILE_NAME" <<'PY'
import json, os, sys
hint = sys.argv[1].strip().lower()
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
    except Exception:
        pass
if os.path.isdir(os.path.join(root, sys.argv[1])):
    print(sys.argv[1])
else:
    print("Default")
PY
)"

mkdir -p "$DST_ROOT/$PROFILE_DIR"
# Marker: if present, the web_ask runner won't overwrite this shadow profile.
# This allows one-time manual login in the shadow profile to persist.
touch "$DST_ROOT/$PROFILE_DIR/.web_ask_bootstrap_keep" || true
if [[ -f "$LOCAL_STATE" ]]; then
  cp -f "$LOCAL_STATE" "$DST_ROOT/Local State" || true
fi

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude=Cache/ \
    --exclude='Code Cache/' \
    --exclude=GPUCache/ \
    --exclude=GrShaderCache/ \
    --exclude=ShaderCache/ \
    --exclude='Service Worker/CacheStorage/' \
    --exclude=Crashpad/ \
    --exclude=BrowserMetrics/ \
    --exclude='Session Storage/' \
    --exclude=Sessions/ \
    "$SRC_ROOT/$PROFILE_DIR/" "$DST_ROOT/$PROFILE_DIR/" || true
fi

rm -f "$DST_ROOT/SingletonCookie" "$DST_ROOT/SingletonLock" "$DST_ROOT/SingletonSocket" "$DST_ROOT/LOCK" || true

CHROME_BIN="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium-browser || command -v chromium || true)"
if [[ -z "$CHROME_BIN" ]]; then
  echo "No encontré Chrome/Chromium en PATH." >&2
  exit 1
fi

# Best-effort: keep the login window on the current workspace so we don't spawn across desktops.
target_desktop=""
before_ids=""
if command -v wmctrl >/dev/null 2>&1; then
  target_desktop="$(wmctrl -d | awk '$2=="*"{print $1; exit}')"
  before_ids="$(wmctrl -l | awk '{print $1}')"
fi

"$CHROME_BIN" \
  --user-data-dir="$DST_ROOT" \
  --profile-directory="$PROFILE_DIR" \
  --new-window \
  --class=web_ask_shadow \
  "$URL" >/dev/null 2>&1 &

if command -v wmctrl >/dev/null 2>&1 && [[ -n "$target_desktop" ]]; then
  # Poll briefly for the new window id, then move it to the current desktop and focus it.
  for _ in {1..50}; do
    sleep 0.1
    after_ids="$(wmctrl -l | awk '{print $1}')"
    new_ids="$(comm -13 <(printf "%s\n" "$before_ids" | sort) <(printf "%s\n" "$after_ids" | sort) || true)"
    wid="$(wmctrl -l | awk -v site="$SITE" '
      BEGIN { IGNORECASE=1 }
      { id=$1; $1=$2=$3=""; title=$0 }
      (site=="chatgpt" && title ~ /chatgpt|chatgpt\\.com/) { print id; exit }
      (site=="gemini" && title ~ /gemini|gemini\\.google\\.com/) { print id; exit }
    ')"
    if [[ -z "$wid" ]]; then
      wid="$(printf "%s\n" "$new_ids" | head -n 1)"
    fi
    if [[ -n "$wid" ]]; then
      wmctrl -i -r "$wid" -t "$target_desktop" >/dev/null 2>&1 || true
      wmctrl -i -a "$wid" >/dev/null 2>&1 || true
      break
    fi
  done
fi

echo "WEB_ASK_BOOTSTRAP_OK site=$SITE profile_name=$PROFILE_NAME profile_dir=$PROFILE_DIR url=$URL"
echo "Iniciá sesión en esa ventana (si hace falta) y luego cerrala."
