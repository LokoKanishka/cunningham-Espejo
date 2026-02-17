#!/usr/bin/env python3
import argparse
import fcntl
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from molbot_direct_chat import desktop_ops, web_ask, web_search
from molbot_direct_chat.ui_html import HTML as UI_HTML
from molbot_direct_chat.util import extract_url as _extract_url
from molbot_direct_chat.util import normalize_text as _normalize_text
from molbot_direct_chat.util import safe_session_id as _safe_session_id

_VRAM_CACHE = {"ts": 0.0, "data": None}


HISTORY_DIR = Path.home() / ".openclaw" / "direct_chat_histories"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_CONFIG_PATH = Path.home() / ".openclaw" / "direct_chat_browser_profiles.json"
DIRECT_CHAT_ENV_PATH = Path(os.environ.get("OPENCLAW_DIRECT_CHAT_ENV", str(Path.home() / ".openclaw" / "direct_chat.env")))
GUARDRAIL_SCRIPT_PATH = Path(__file__).resolve().parent / "guardrail_check.sh"

SITE_ALIASES = {
    "chatgpt": "https://chatgpt.com/",
    "chat gpt": "https://chatgpt.com/",
    "gemini": "https://gemini.google.com/app",
    "youtube": "https://www.youtube.com/",
    "you tube": "https://www.youtube.com/",
    "wikipedia": "https://es.wikipedia.org/",
    "wiki": "https://es.wikipedia.org/",
    "gmail": "https://mail.google.com/",
    "mail": "https://mail.google.com/",
}

SITE_SEARCH_TEMPLATES = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "wikipedia": "https://es.wikipedia.org/w/index.php?search={q}",
}

SITE_CANONICAL_TOKENS = {
    # Include common typos so simple "open X" doesn't fall back to the model.
    "chatgpt": ["chatgpt", "chat gpt", "chatgtp", "chat gtp"],
    "gemini": ["gemini", "gemni", "geminy", "gemin"],
    "youtube": ["youtube", "you tube", "ytube", "yutub", "youtbe", "youtub"],
    "wikipedia": ["wikipedia", "wiki"],
    "gmail": ["gmail", "mail"],
}

# Defaults can be overridden in ~/.openclaw/direct_chat_browser_profiles.json
DEFAULT_BROWSER_PROFILE_CONFIG = {
    "_default": {"browser": "chrome", "profile": "diego"},
    # Keep ChatGPT/Gemini in the same logged-in Chrome profile by default.
    "chatgpt": {"browser": "chrome", "profile": "diego"},
    "gemini": {"browser": "chrome", "profile": "diego"},
    "youtube": {"browser": "chrome", "profile": "diego"},
    "wikipedia": {"browser": "chrome", "profile": "diego"},
    "gmail": {"browser": "chrome", "profile": "diego"},
}
HTML = UI_HTML


# NOTE: UI HTML moved to scripts/molbot_direct_chat/ui_html.py
# Keeping the content embedded here made this file too large to maintain.

BROWSER_WINDOWS_PATH = Path.home() / ".openclaw" / "direct_chat_opened_browser_windows.json"
BROWSER_WINDOWS_LOCK_PATH = Path.home() / ".openclaw" / ".direct_chat_opened_browser_windows.lock"
TRUSTED_DC_ANCHOR_PATH = Path.home() / ".openclaw" / "direct_chat_trusted_anchor.json"


def _load_local_env_file(path: Path) -> None:
    try:
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if "=" not in raw:
                continue
            k, v = raw.split("=", 1)
            key = k.strip()
            if not key:
                continue
            val = v.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = val
    except Exception:
        return


_load_local_env_file(DIRECT_CHAT_ENV_PATH)


def _wmctrl_list() -> dict[str, str]:
    if not shutil.which("wmctrl"):
        return {}
    try:
        proc = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=3)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        win_id = parts[0].strip()
        title = parts[3].strip()
        if win_id and title:
            out[win_id] = title
    return out


def _wmctrl_current_desktop() -> int | None:
    if not shutil.which("wmctrl"):
        return None
    try:
        proc = subprocess.run(["wmctrl", "-d"], capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "*":
            try:
                return int(parts[0])
            except Exception:
                return None
    return None


def _pid_cmd_args(pid_raw: str) -> list[str]:
    try:
        pid = int(str(pid_raw).strip())
    except Exception:
        return []
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except Exception:
        return []
    return [p.decode("utf-8", errors="ignore").strip() for p in raw.split(b"\x00") if p]


def _profile_directory_from_args(args: list[str]) -> str:
    for i, arg in enumerate(args):
        if arg.startswith("--profile-directory="):
            return arg.split("=", 1)[1].strip().strip("'\"")
        if arg == "--profile-directory" and (i + 1) < len(args):
            return args[i + 1].strip().strip("'\"")
    merged = " ".join(args)
    m = re.search(r"--profile-directory=(.+?)(?:\s--|$)", merged)
    if m:
        return m.group(1).strip().strip("'\"")
    m = re.search(r"--profile-directory\s+(.+?)(?:\s--|$)", merged)
    if m:
        return m.group(1).strip().strip("'\"")
    return ""


def _pid_profile_directory(pid_raw: str) -> str:
    args = _pid_cmd_args(pid_raw)
    if not args:
        return ""
    return _profile_directory_from_args(args)


def _window_matches_profile(pid_raw: str, expected_profile: str | None) -> bool:
    expected = str(expected_profile or "").strip().lower()
    if not expected:
        return True
    got = _pid_profile_directory(pid_raw).strip().lower()
    return bool(got) and got == expected


def _xdotool_command(args: list[str], timeout: float = 3.0) -> tuple[int, str]:
    if not shutil.which("xdotool"):
        return 127, ""
    try:
        proc = subprocess.run(
            ["xdotool", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except Exception:
        return 1, ""


def _xdotool_window_geometry(win_id: str) -> tuple[int, int, int, int] | None:
    rc, out = _xdotool_command(["getwindowgeometry", "--shell", win_id], timeout=2.0)
    if rc != 0 or not out:
        return None
    vals: dict[str, int] = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().upper()
        v = v.strip()
        if k in ("X", "Y", "WIDTH", "HEIGHT"):
            try:
                vals[k] = int(v)
            except Exception:
                return None
    if all(k in vals for k in ("X", "Y", "WIDTH", "HEIGHT")):
        return vals["X"], vals["Y"], vals["WIDTH"], vals["HEIGHT"]
    return None


def _xdotool_active_window() -> str:
    rc, out = _xdotool_command(["getactivewindow"], timeout=1.5)
    if rc != 0 or not out:
        return ""
    wid = out.strip().lower()
    if wid.startswith("0x"):
        return wid
    try:
        return f"0x{int(wid):08x}"
    except Exception:
        return ""


def _wmctrl_window_desktop(win_id: str) -> int | None:
    if not shutil.which("wmctrl"):
        return None
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            wid, desk_raw, _pid, _host, _title = parts
            if wid.strip().lower() != win_id.strip().lower():
                continue
            try:
                return int(desk_raw)
            except Exception:
                return None
    except Exception:
        return None
    return None


def _wait_window_title_contains(win_id: str, terms: list[str], timeout_s: float = 8.0) -> tuple[bool, str]:
    deadline = time.time() + max(0.5, timeout_s)
    last = ""
    needles = [str(t).lower().strip() for t in terms if str(t).strip()]
    while time.time() < deadline:
        title = str(_wmctrl_list().get(win_id, "")).lower().strip()
        if title:
            last = title
        if title and any(n in title for n in needles):
            return True, title
        time.sleep(0.2)
    return False, last


def _wmctrl_move_window_to_desktop(win_id: str, desktop_idx: int) -> bool:
    if not shutil.which("wmctrl"):
        return False
    try:
        subprocess.run(
            ["wmctrl", "-i", "-r", win_id, "-t", str(int(desktop_idx))],
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _find_new_profiled_chrome_window(
    before_ids: set[str], expected_profile: str | None, max_desktops: int = 16, timeout_s: float = 10.0
) -> tuple[str, int | None]:
    deadline = time.time() + max(0.8, timeout_s)
    while time.time() < deadline:
        for desk_idx in range(max_desktops):
            for wid, pid_raw, title in _wmctrl_windows_for_desktop(desk_idx):
                if wid in before_ids:
                    continue
                t = str(title).lower()
                if not any(tok in t for tok in ("chrome", "google", "gemini", "about:blank")):
                    continue
                if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
                    continue
                return wid, desk_idx
        time.sleep(0.12)
    return "", None


def _preferred_workspace_and_anchor(expected_profile: str | None = None) -> tuple[int | None, str]:
    active = _xdotool_active_window()
    if active:
        wins = _wmctrl_list()
        title = str(wins.get(active, "")).lower().strip()
        if "molbot direct chat" in title:
            desk = _wmctrl_window_desktop(active)
            if desk is not None:
                # Validate profile ownership when possible.
                if expected_profile:
                    for wid, pid_raw, _t in _wmctrl_windows_for_desktop(desk):
                        if wid.lower() == active.lower() and _window_matches_profile(pid_raw, expected_profile):
                            return desk, active
                else:
                    return desk, active

    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, ""
    return desk, ""


def _wmctrl_windows_for_desktop(desktop_idx: int) -> list[tuple[str, str, str]]:
    if not shutil.which("wmctrl"):
        return []
    out: list[tuple[str, str, str]] = []
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            wid, desk_raw, pid_raw, _host, title = parts
            try:
                desk = int(desk_raw)
            except Exception:
                continue
            if desk != desktop_idx:
                continue
            out.append((wid, pid_raw, title))
    except Exception:
        return []
    return out


def _open_gemini_in_current_workspace_via_ui(
    expected_profile: str | None = None, session_id: str | None = None
) -> tuple[bool, str]:
    # Workspace-safe open path using visible UI interactions only.
    workspace, _preferred_anchor = _preferred_workspace_and_anchor(expected_profile)
    if workspace is None:
        return False, "workspace_not_detected"

    wins = _wmctrl_windows_for_desktop(workspace)
    before_ids = {wid for wid, _, _ in wins}
    trusted_anchor, trusted_status = _trusted_or_autodetected_dc_anchor(expected_profile=expected_profile)
    anchor = trusted_anchor or ""
    if not anchor:
        return False, f"trusted_anchor_required ({trusted_status})"

    _xdotool_command(["windowactivate", anchor], timeout=2.5)
    time.sleep(0.22)
    _xdotool_command(["key", "--window", anchor, "ctrl+n"], timeout=2.0)

    target = ""
    for _ in range(80):
        now = _wmctrl_windows_for_desktop(workspace)
        for wid, pid_raw, title in now:
            if wid not in before_ids and ("chrome" in title.lower() or "google" in title.lower()):
                if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
                    continue
                target = wid
                break
        if target:
            break
        time.sleep(0.1)
    if not target:
        return False, "new_window_not_detected_from_anchor"

    _xdotool_command(["windowactivate", target], timeout=2.5)
    time.sleep(0.18)
    # Keep trained flow (Google -> Gemini), but verify Gemini actually loaded.
    for url in ("https://www.google.com/", "https://gemini.google.com/app"):
        _xdotool_command(["key", "--window", target, "ctrl+l"], timeout=2.0)
        time.sleep(0.08)
        _xdotool_command(
            ["type", "--delay", "18", "--clearmodifiers", "--window", target, url],
            timeout=8.0,
        )
        time.sleep(0.08)
        _xdotool_command(["key", "--window", target, "Return"], timeout=2.0)
        time.sleep(0.6)
        if "google.com" in url:
            _wait_window_title_contains(target, ["google"], timeout_s=4.0)
        if "gemini.google.com" in url:
            ok_title, _t = _wait_window_title_contains(target, ["gemini"], timeout_s=6.0)
            if not ok_title:
                cur_title = str(_wmctrl_list().get(target, ""))
                return False, f"gemini_not_loaded title={cur_title}"

    needs_login, snap = _gemini_window_requires_login(target)
    if needs_login:
        _wmctrl_close_window(target)
        return False, f"login_required workspace={workspace} target={target} snap={snap}"

    if session_id:
        title = _wmctrl_list().get(target, "")
        _record_browser_windows(
            session_id,
            [
                {
                    "win_id": target,
                    "title": title,
                    "url": "https://gemini.google.com/app",
                    "site_key": "gemini",
                    "ts": time.time(),
                }
            ],
        )
    return True, f"ui_open workspace={workspace} target={target}"


def _wmctrl_close_window(win_id: str) -> bool:
    if not shutil.which("wmctrl"):
        return False
    try:
        subprocess.run(
            ["wmctrl", "-ic", win_id],
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _gemini_window_requires_login(win_id: str) -> tuple[bool, str]:
    import_bin = shutil.which("import")
    if not import_bin:
        return False, ""
    snap_dir = Path.home() / ".openclaw" / "logs" / "gemini_write_screens"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = snap_dir / f"gemini_open_state_{int(time.time() * 1000)}.png"
    try:
        subprocess.run(
            [import_bin, "-window", win_id, str(snap)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
    except Exception:
        return False, ""
    needs_login = _ocr_contains_any(snap, ["iniciar sesión", "iniciar sesion", "sign in"])
    return needs_login, str(snap)


def _wmctrl_current_desktop_site_windows(
    site_key: str, expected_profile: str | None = None, desktop_idx: int | None = None
) -> list[tuple[str, str]]:
    if not shutil.which("wmctrl"):
        return []
    desk = desktop_idx if desktop_idx is not None else _wmctrl_current_desktop()
    if desk is None:
        return []
    token = "gemini" if site_key == "gemini" else ("chatgpt" if site_key == "chatgpt" else site_key)
    out: list[tuple[str, str]] = []
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            win_id, desktop_raw, pid_raw, _host, title = parts
            try:
                desktop_i = int(desktop_raw)
            except Exception:
                continue
            title_n = title.lower().strip()
            if desktop_i != desk:
                continue
            if token not in title_n:
                continue
            if "molbot direct chat" in title_n:
                continue
            if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
                continue
            out.append((win_id, title))
    except Exception:
        return []
    return out


def _wmctrl_window_pid(win_id: str) -> str | None:
    if not shutil.which("wmctrl"):
        return None
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=3)
        for line in (proc.stdout or "").splitlines():
            parts = line.split(None, 4)
            if len(parts) < 3:
                continue
            wid, _desktop_raw, pid_raw = parts[:3]
            if wid.lower().strip() == str(win_id).lower().strip():
                return pid_raw
    except Exception:
        return None
    return None


def _close_recent_site_window_fallback(site_key: str, expected_profile: str | None = None) -> tuple[bool, str]:
    prof = expected_profile if expected_profile is not None else _expected_profile_directory_for_site(site_key)
    wins = _wmctrl_current_desktop_site_windows(site_key, expected_profile=prof)
    if not wins:
        return False, "no_window_found_current_workspace"
    # wmctrl ordering is stable enough for "last listed" as a practical fallback.
    win_id, title = wins[-1]
    if _wmctrl_close_window(win_id):
        return True, title
    return False, "wmctrl_close_failed"


def _close_known_site_windows_in_current_workspace(max_windows: int = 12) -> tuple[int, list[str]]:
    closed = 0
    details: list[str] = []
    site_order = ("youtube", "chatgpt", "gemini", "wikipedia", "gmail")
    for _ in range(max(1, max_windows)):
        did_close = False
        for site_key in site_order:
            ok, detail = _close_recent_site_window_fallback(
                site_key, expected_profile=_expected_profile_directory_for_site(site_key)
            )
            if ok:
                closed += 1
                details.append(f"{site_key}:{detail[:90]}")
                did_close = True
                break
        if not did_close:
            break
    return closed, details


def _extract_youtube_transport_request(message: str) -> tuple[str, bool] | None:
    normalized = _normalize_text(message or "")
    if not any(t in normalized for t in SITE_CANONICAL_TOKENS.get("youtube", [])):
        return None
    # Keep search/open flows on the dedicated deterministic path.
    if any(t in normalized for t in ("busc", "search", "investig", "abr", "open", "primer video")):
        return None

    wants_pause = any(
        t in normalized
        for t in (
            "paus",
            "pause",
            "deten",
            "detener",
            "stop",
            "fren",
            "parar",
            "para el video",
            "detene",
        )
    )
    wants_play = any(
        t in normalized
        for t in (
            "reanuda",
            "reanudar",
            "resume",
            "continu",
            "seguir",
            "segui",
            "play",
            "reproduc",
            "ponelo",
            "ponela",
            "dale play",
        )
    )
    wants_close = any(t in normalized for t in ("cerr", "close", "cierra", "cerra")) and any(
        t in normalized for t in ("ventan", "window", "pestan", "tab")
    )

    if wants_play and not wants_pause:
        return "play", wants_close
    if wants_pause:
        return "pause", wants_close
    return None


def _pick_active_site_window_id(
    site_key: str, expected_profile: str | None = None
) -> tuple[str | None, str]:
    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, "workspace_not_detected"
    active = _xdotool_active_window()
    if not active:
        return None, "active_window_not_detected"
    token = "gemini" if site_key == "gemini" else ("chatgpt" if site_key == "chatgpt" else site_key)
    for wid, pid_raw, title in _wmctrl_windows_for_desktop(desk):
        if wid.lower() != active.lower():
            continue
        t = str(title).lower().strip()
        if token not in t:
            return None, "active_window_not_site"
        if "molbot direct chat" in t:
            return None, "active_window_is_dc"
        if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
            return None, "active_window_profile_mismatch"
        return wid, str(title)
    return None, "active_window_not_in_current_workspace"


def _youtube_transport_action(action: str, close_window: bool = False, session_id: str | None = None) -> tuple[bool, str]:
    _ = session_id  # Reserved for future per-session telemetry.
    if not shutil.which("wmctrl") or not shutil.which("xdotool"):
        return False, "missing_wmctrl_or_xdotool"

    expected_profile = _expected_profile_directory_for_site("youtube")
    win_id, detail = _pick_active_site_window_id("youtube", expected_profile=expected_profile)
    if not win_id:
        wins = _wmctrl_current_desktop_site_windows("youtube", expected_profile=expected_profile)
        if wins:
            win_id = wins[-1][0]
            detail = wins[-1][1]
    if not win_id:
        win_id, detail = _pick_active_site_window_id("youtube", expected_profile=None)
    if not win_id:
        wins = _wmctrl_current_desktop_site_windows("youtube", expected_profile=None)
        if wins:
            win_id = wins[-1][0]
            detail = wins[-1][1]
    if not win_id:
        return False, f"youtube_window_not_found_current_workspace profile={expected_profile}"

    rc_activate, _ = _xdotool_command(["windowactivate", win_id], timeout=2.5)
    if rc_activate != 0:
        return False, f"window_activate_failed win={win_id}"
    time.sleep(0.16)

    # YouTube keyboard control: 'k' toggles play/pause consistently across layouts.
    rc_key, _ = _xdotool_command(["key", "--window", win_id, "k"], timeout=2.0)
    if rc_key != 0:
        return False, f"youtube_key_toggle_failed win={win_id}"

    if close_window:
        time.sleep(0.15)
        if not _wmctrl_close_window(win_id):
            return False, f"youtube_close_failed win={win_id}"

    return True, f"ok action={action} close={int(close_window)} win={win_id} detail={detail[:120]}"


def _extract_gemini_write_request(message: str) -> str | None:
    msg = (message or "").strip()
    normalized = _normalize_text(msg)
    if not any(t in normalized for t in SITE_CANONICAL_TOKENS.get("gemini", [])):
        return None
    if not any(
        v in normalized
        for v in (
            "escrib",
            "deci",
            "decí",
            "pone",
            "poné",
            "manda",
            "envia",
            "enviá",
            "redact",
            "tipe",
            "coloc",
            "deja",
            "dejá",
            "mete",
            "carg",
            "public",
            "poste",
        )
    ):
        return None

    quoted = re.search(r"[\"“”'`]\s*([^\"“”'`]{1,320})\s*[\"“”'`]", msg)
    if quoted:
        text = quoted.group(1).strip()
        if text:
            return text[:320]

    # Pick the LAST writing verb in the phrase, so requests like
    # "decile a cunn que abra gemini y escriba hola gemini"
    # extract only "hola gemini".
    verb_pat = re.compile(
        r"\b(?:escrib\w*|dec[ií]\w*|pon[eé]\w*|manda\w*|envia\w*|envi[aá]\w*|redact\w*|tipe\w*|coloc\w*|deja\w*|dej[aá]\w*|mete\w*|carg\w*|public\w*|poste\w*)\b",
        flags=re.IGNORECASE,
    )
    matches = list(verb_pat.finditer(normalized))
    if not matches:
        return None
    text = normalized[matches[-1].end() :].strip()
    text = re.split(r"\s+y\s+(?:da\s+)?enter\b|\s+enter\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"[\n\r]", text, maxsplit=1)[0]
    text = re.sub(r"\ben\s+el\s+chat\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\ben\s+gemini\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpor\s+favor\b", "", text, flags=re.IGNORECASE)
    text = text.strip(" .,:;\"'`")
    if not text:
        return None
    return text[:320]


def _extract_gemini_ask_request(message: str) -> str | None:
    normalized = _normalize_text(message or "")
    if not any(t in normalized for t in SITE_CANONICAL_TOKENS.get("gemini", [])):
        return None
    if not any(v in normalized for v in ("pregunt", "consult", "pedi", "pedile", "decile", "dile", "busc", "busq")):
        return None

    # Variant: "busca <tema> en gemini"
    m = re.search(
        r"(?:^|\b)(?:que\s+)?(?:me\s+)?(?:busc\w*|busq\w*)\s+(.+?)\s+en\s+gemini\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if m:
        prompt = (m.group(1) or "").strip()
        prompt = re.sub(r"^(sobre|acerca de)\s+", "", prompt, flags=re.IGNORECASE).strip()
        prompt = prompt.strip(" .,:;\"'`")
        if prompt:
            return prompt[:320]

    m = re.search(
        r"(?:pregunt\w*|consult\w*|ped\w*|dec\w*|dile|busc\w*|busq\w*)\s+(?:en\s+)?(?:a\s+)?gemini\b[\s,:-]*(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"\bgemini\b.*?(?:pregunt\w*|consult\w*|ped\w*|dec\w*|dile|busc\w*|busq\w*)\b[\s,:-]*(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
    if not m:
        return None
    prompt = (m.group(1) or "").strip()
    prompt = re.sub(r"^(que|sobre|acerca de)\s+", "", prompt, flags=re.IGNORECASE).strip()
    prompt = prompt.strip(" .,:;\"'`")
    if not prompt:
        return None
    return prompt[:320]


def _ocr_read_text(image_path: Path) -> str:
    if not shutil.which("tesseract"):
        return ""
    try:
        proc = subprocess.run(
            ["tesseract", str(image_path), "stdout"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return re.sub(r"\s+", " ", (proc.stdout or "").lower()).strip()
    except Exception:
        return ""


def _ocr_contains_text(image_path: Path, expected: str) -> bool:
    try:
        txt = _ocr_read_text(image_path)
        if not txt:
            return False
        exp = re.sub(r"\s+", " ", expected.lower().strip()).strip()
        if not exp:
            return False
        # accept either full text or first token for short prompts
        if exp in txt:
            return True
        # For multi-word prompts, require contiguous phrase match to avoid false positives
        # from unrelated UI text (e.g., "Hola, diego" + "Gemini" in different places).
        if len(exp.split()) >= 2:
            return False
        parts = [p for p in re.split(r"\W+", exp) if len(p) >= 3]
        if not parts:
            first = exp.split()[0] if exp.split() else exp
            return len(first) >= 4 and first in txt
        hits = sum(1 for p in parts if p in txt)
        return hits >= max(1, len(parts) // 2)
    except Exception:
        return False


def _ocr_contains_any(image_path: Path, expected_terms: list[str]) -> bool:
    txt = _ocr_read_text(image_path)
    if not txt:
        return False
    for term in expected_terms:
        exp = re.sub(r"\s+", " ", term.lower().strip()).strip()
        if exp and exp in txt:
            return True
    return False


def _ocr_phrase_centers(image_path: Path, phrase: str) -> list[tuple[int, int]]:
    if not shutil.which("tesseract"):
        return []
    try:
        proc = subprocess.run(
            ["tesseract", str(image_path), "stdout", "hocr"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw = proc.stdout or ""
    except Exception:
        return []
    if not raw.strip():
        return []

    words: list[tuple[str, tuple[int, int, int, int]]] = []
    for m in re.finditer(
        r"<span[^>]*class=[\"']ocrx_word[\"'][^>]*title=[\"']([^\"']+)[\"'][^>]*>(.*?)</span>",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        title = m.group(1) or ""
        body = re.sub(r"<[^>]+>", "", m.group(2) or "")
        body = html.unescape(body).strip()
        if not body:
            continue
        bb = re.search(r"bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", title)
        if not bb:
            continue
        try:
            x1, y1, x2, y2 = [int(bb.group(i)) for i in range(1, 5)]
        except Exception:
            continue
        norm_word = re.sub(r"[^\wáéíóúüñ]+", "", _normalize_text(body))
        if not norm_word:
            continue
        words.append((norm_word, (x1, y1, x2, y2)))
    if not words:
        return None

    tokens = [w for w, _ in words]
    pnorm = _normalize_text(phrase)
    wanted = [re.sub(r"[^\wáéíóúüñ]+", "", t) for t in pnorm.split()]
    wanted = [t for t in wanted if t]
    if not wanted:
        return []

    n = len(wanted)
    out: list[tuple[int, int]] = []
    for i in range(0, len(tokens) - n + 1):
        if tokens[i : i + n] != wanted:
            continue
        xs = []
        ys = []
        for _w, (x1, y1, x2, y2) in words[i : i + n]:
            xs.extend([x1, x2])
            ys.extend([y1, y2])
        if not xs or not ys:
            continue
        cx = (min(xs) + max(xs)) // 2
        cy = (min(ys) + max(ys)) // 2
        out.append((cx, cy))
    return out


def _ocr_find_phrase_center(image_path: Path, phrases: list[str]) -> tuple[int, int] | None:
    for phrase in phrases:
        centers = _ocr_phrase_centers(image_path, phrase)
        if centers:
            return centers[0]
    return None


def _looks_like_phrase_still_in_composer(
    image_path: Path, phrase: str, win_h: int, threshold_pct: int = 72
) -> bool:
    pts = _ocr_phrase_centers(image_path, phrase)
    if not pts:
        return False
    threshold = int(win_h * threshold_pct / 100)
    return any(y >= threshold for _x, y in pts)


def _composer_send_click_point(
    image_path: Path, win_w: int, win_h: int, composer_center: tuple[int, int] | None
) -> tuple[int, int] | None:
    anchor = _ocr_find_phrase_center(
        image_path,
        [
            "pensar",
            "think",
            "herramientas",
            "tools",
        ],
    )
    if anchor:
        ax, ay = anchor
        # In Gemini layout, the send button sits to the right of "Pensar/Think".
        return min(win_w - 24, ax + int(win_w * 0.12)), ay
    if composer_center:
        cx, cy = composer_center
        # Fallback: right edge of composer row.
        return min(win_w - 24, cx + int(win_w * 0.38)), cy
    return None


def _composer_looks_empty(image_path: Path) -> bool:
    return _ocr_contains_any(
        image_path,
        [
            "preguntale a gemini",
            "pregúntale a gemini",
            "pregunta a gemini",
            "pregunta a gemini 3",
            "que quieres investigar",
            "¿qué quieres investigar?",
            "ask gemini",
        ],
    )


def _gemini_write_in_current_workspace(text: str, session_id: str | None = None) -> tuple[bool, str]:
    if not shutil.which("wmctrl") or not shutil.which("xdotool"):
        return False, "missing_wmctrl_or_xdotool"

    workspace, _anchor = _preferred_workspace_and_anchor()
    if workspace is None:
        return False, "workspace_not_detected"

    expected_profile = _expected_profile_directory_for_site("gemini")

    # Reuse Gemini in the current workspace when available.
    opened: list[str]
    existing = _wmctrl_current_desktop_site_windows(
        "gemini", expected_profile=expected_profile, desktop_idx=workspace
    )
    if existing:
        opened = ["reuse_existing_gemini_window"]
    else:
        ok_open, detail = _open_gemini_in_current_workspace_via_ui(
            expected_profile=expected_profile, session_id=session_id
        )
        if not ok_open:
            return False, detail
        opened = [detail]

    win_id = ""
    for _ in range(140):
        wins = _wmctrl_current_desktop_site_windows(
            "gemini", expected_profile=expected_profile, desktop_idx=workspace
        )
        if wins:
            win_id = wins[-1][0]
            break
        time.sleep(0.12)
    if not win_id:
        return False, f"gemini_window_not_found_current_workspace profile={expected_profile}"

    _xdotool_command(["windowactivate", win_id], timeout=2.5)
    time.sleep(0.65)
    geom = _xdotool_window_geometry(win_id)
    if not geom:
        return False, "gemini_geometry_not_found"
    gx, gy, gw, gh = geom

    screen_dir = Path.home() / ".openclaw" / "logs" / "gemini_write_screens"
    screen_dir.mkdir(parents=True, exist_ok=True)
    import_bin = shutil.which("import")
    if not import_bin:
        return False, "missing_import_for_visual_verification"

    snap_state = screen_dir / f"gemini_write_state_{int(time.time() * 1000)}.png"
    try:
        subprocess.run(
            [import_bin, "-window", win_id, str(snap_state)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
    except Exception:
        return False, "state_screenshot_failed"

    if _ocr_contains_any(snap_state, ["iniciar sesión", "iniciar sesion", "sign in"]):
        return False, f"login_required workspace={workspace} win={win_id} snap={snap_state}"

    composer_center = _ocr_find_phrase_center(
        snap_state,
        [
            "preguntale a gemini",
            "pregúntale a gemini",
            "pregunta a gemini",
            "pregunta a gemini 3",
            "que quieres investigar",
            "¿qué quieres investigar?",
            "ask gemini",
        ],
    )
    if not composer_center:
        tools_anchor = _ocr_find_phrase_center(
            snap_state,
            [
                "herramientas",
                "tools",
                "pensar",
                "think",
            ],
        )
        if tools_anchor:
            tx, ty = tools_anchor
            # When placeholder text is absent, anchors in the composer footer are usually visible.
            # Click a bit above that footer to focus the text input area.
            composer_center = (tx, max(12, ty - int(gh * 0.055)))
    if not composer_center:
        # OCR can miss dark-theme placeholders; use geometric fallback over the
        # central lower panel where Gemini composer usually lives.
        composer_center = (int(gw * 0.62), int(gh * 0.56))

    rel_x, rel_y = composer_center
    px = gx + rel_x
    py = gy + rel_y
    _xdotool_command(["mousemove", str(px), str(py)], timeout=2.0)
    _xdotool_command(["click", "1"], timeout=2.0)
    time.sleep(0.14)

    dirty_detected = False
    pre_clean = screen_dir / f"gemini_write_pre_clean_{int(time.time() * 1000)}.png"
    try:
        subprocess.run(
            [import_bin, "-window", win_id, str(pre_clean)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        if _looks_like_phrase_still_in_composer(pre_clean, text, gh) or not _composer_looks_empty(pre_clean):
            dirty_detected = True
    except Exception:
        pass

    # Self-heal: clear any leftover draft to avoid cascading failures.
    clean_ok = False
    clean_snap = None
    for _ in range(3):
        _xdotool_command(["key", "--window", win_id, "ctrl+a"], timeout=2.0)
        time.sleep(0.06)
        _xdotool_command(["key", "--window", win_id, "BackSpace"], timeout=2.0)
        time.sleep(0.10)
        clean_snap = screen_dir / f"gemini_write_clean_{int(time.time() * 1000)}.png"
        try:
            subprocess.run(
                [import_bin, "-window", win_id, str(clean_snap)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
            if not _looks_like_phrase_still_in_composer(clean_snap, text, gh):
                clean_ok = True
                break
        except Exception:
            continue
    if not clean_ok:
        return False, f"dirty_chat_not_cleaned workspace={workspace} win={win_id} snap={clean_snap}"

    tools_anchor = _ocr_find_phrase_center(
        snap_state,
        [
            "herramientas",
            "tools",
            "pensar",
            "think",
        ],
    )
    focus_candidates: list[tuple[int, int]] = [composer_center]
    if tools_anchor:
        tx, ty = tools_anchor
        focus_candidates.append((tx, max(12, ty - int(gh * 0.080))))
    focus_candidates.extend(
        [
            # Safe geometric fallbacks inside the upper half of the composer.
            (int(gw * 0.58), int(gh * 0.53)),
            (int(gw * 0.68), int(gh * 0.53)),
            (int(gw * 0.58), int(gh * 0.56)),
        ]
    )

    snap_pre = None
    pre_verified = False
    focus_ok = False
    for fx, fy in focus_candidates:
        # Keep focus attempts in a conservative region to avoid clicks below composer.
        fx = max(int(gw * 0.42), min(int(fx), int(gw * 0.95)))
        fy = max(int(gh * 0.46), min(int(fy), int(gh * 0.60)))
        px = gx + fx
        py = gy + fy
        _xdotool_command(["mousemove", str(px), str(py)], timeout=2.0)
        _xdotool_command(["click", "1"], timeout=2.0)
        time.sleep(0.08)
        _xdotool_command(["type", "--delay", "34", "--clearmodifiers", "--window", win_id, text], timeout=8.0)
        time.sleep(0.25)

        snap_try = screen_dir / f"gemini_write_pre_{int(time.time() * 1000)}.png"
        try:
            subprocess.run(
                [import_bin, "-window", win_id, str(snap_try)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
        except Exception:
            continue
        snap_pre = snap_try
        if _looks_like_phrase_still_in_composer(snap_try, text, gh):
            focus_ok = True
            pre_verified = True
            break

    if not focus_ok or not snap_pre:
        return False, f"composer_focus_failed workspace={workspace} win={win_id} snap={snap_pre or snap_state}"

    send_pt_rel = _composer_send_click_point(snap_pre, gw, gh, composer_center)
    send_attempts = [("enter", None), ("ctrl_enter", None), ("enter_kp", None)]
    if send_pt_rel:
        send_attempts.append(("click_send_ocr", send_pt_rel))
    # Crucial fallback: click on the right side of the SAME composer row, not near window bottom.
    if composer_center:
        send_attempts.extend(
            [
                ("click_send_row_right", (96, int((composer_center[1] * 100) / max(1, gh)))),
                ("click_send_row_right_alt", (93, int((composer_center[1] * 100) / max(1, gh)))),
            ]
        )
    send_attempts.extend([("click_send", (92, 95)), ("click_send_alt", (95, 95))])
    last_post = None
    for action, point in send_attempts:
        if action == "enter":
            _xdotool_command(["key", "--window", win_id, "Return"], timeout=2.0)
        elif action == "ctrl_enter":
            _xdotool_command(["key", "--window", win_id, "ctrl+Return"], timeout=2.0)
        elif action == "enter_kp":
            _xdotool_command(["key", "--window", win_id, "KP_Enter"], timeout=2.0)
        else:
            if action == "click_send_ocr":
                spx = gx + int(point[0])
                spy = gy + int(point[1])
            else:
                spx = gx + int(gw * point[0] / 100)
                spy = gy + int(gh * point[1] / 100)
            _xdotool_command(["mousemove", str(spx), str(spy)], timeout=2.0)
            _xdotool_command(["click", "1"], timeout=2.0)
        time.sleep(0.85)

        snap_post = screen_dir / f"gemini_write_post_{int(time.time() * 1000)}_{action}.png"
        try:
            subprocess.run(
                [import_bin, "-window", win_id, str(snap_post)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
            last_post = snap_post
            if not _looks_like_phrase_still_in_composer(snap_post, text, gh):
                # Stabilize verdict: verify again shortly after to avoid transient false positives.
                time.sleep(0.75)
                snap_post_confirm = screen_dir / f"gemini_write_post_{int(time.time() * 1000)}_{action}_confirm.png"
                try:
                    subprocess.run(
                        [import_bin, "-window", win_id, str(snap_post_confirm)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=4,
                    )
                    last_post = snap_post_confirm
                    if _looks_like_phrase_still_in_composer(snap_post_confirm, text, gh):
                        continue
                except Exception:
                    # If confirm capture fails, keep original optimistic sample.
                    snap_post_confirm = snap_post
                return True, (
                    f"verified workspace={workspace} win={win_id} click={px},{py} "
                    f"submit={action} dirty={int(dirty_detected)} "
                    f"pre_verified={int(pre_verified)} snap_pre={snap_pre} "
                    f"snap_post={snap_post_confirm} opened={' | '.join(opened)}"
                )
        except Exception:
            continue

    return False, (
        f"submit_failed_draft_present workspace={workspace} win={win_id} "
        f"pre_verified={int(pre_verified)} snap_pre={snap_pre} snap_post={last_post}"
    )


def _browser_windows_load() -> dict:
    BROWSER_WINDOWS_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with BROWSER_WINDOWS_LOCK_PATH.open("a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_SH)
            if BROWSER_WINDOWS_PATH.exists():
                try:
                    data = json.loads(BROWSER_WINDOWS_PATH.read_text(encoding="utf-8") or "{}")
                    return data if isinstance(data, dict) else {}
                except Exception:
                    return {}
            return {}
    except Exception:
        return {}


def _browser_windows_save(data: dict) -> None:
    try:
        BROWSER_WINDOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
        BROWSER_WINDOWS_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = BROWSER_WINDOWS_PATH.with_suffix(".json.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        with BROWSER_WINDOWS_LOCK_PATH.open("a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(BROWSER_WINDOWS_PATH)
    except Exception:
        return


def _load_trusted_dc_anchor() -> dict:
    try:
        if not TRUSTED_DC_ANCHOR_PATH.exists():
            return {}
        raw = json.loads(TRUSTED_DC_ANCHOR_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return {}
    return {}


def _save_trusted_dc_anchor(win_id: str, desktop: int, title: str) -> None:
    try:
        TRUSTED_DC_ANCHOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "win_id": str(win_id),
            "desktop": int(desktop),
            "title": str(title),
            "ts": int(time.time()),
        }
        TRUSTED_DC_ANCHOR_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _trusted_dc_anchor_for_current_workspace() -> tuple[str | None, str]:
    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, "workspace_not_detected"
    data = _load_trusted_dc_anchor()
    win_id = str(data.get("win_id", "")).strip()
    if not win_id:
        return None, "trusted_anchor_not_set"
    wins = _wmctrl_windows_for_desktop(desk)
    for wid, _pid_raw, title in wins:
        if wid.lower() != win_id.lower():
            continue
        t = str(title).lower()
        if "molbot direct chat" not in t:
            return None, "trusted_anchor_title_mismatch"
        if "chrome" not in t and "google" not in t:
            return None, "trusted_anchor_not_chrome"
        return wid, "ok"
    return None, "trusted_anchor_not_in_current_workspace"


def _active_dc_anchor_for_current_workspace(expected_profile: str | None = None) -> tuple[str | None, str]:
    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, "workspace_not_detected"
    active = _xdotool_active_window()
    if not active:
        return None, "active_window_not_detected"
    wins = _wmctrl_windows_for_desktop(desk)
    for wid, pid_raw, title in wins:
        if wid.lower() != active.lower():
            continue
        t = str(title).lower()
        if "molbot direct chat" not in t:
            return None, "active_window_not_dc"
        if "chrome" not in t and "google" not in t:
            return None, "active_window_not_chrome"
        if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
            return None, "active_window_profile_mismatch"
        _save_trusted_dc_anchor(wid, desk, str(title))
        return wid, "active_anchor_ok"
    return None, "active_window_not_in_current_workspace"


def _autodetect_dc_anchor_for_current_workspace(expected_profile: str | None = None) -> tuple[str | None, str]:
    desk = _wmctrl_current_desktop()
    if desk is None:
        return None, "workspace_not_detected"
    candidates: list[tuple[str, str]] = []
    for wid, pid_raw, title in _wmctrl_windows_for_desktop(desk):
        t = str(title).lower()
        if "molbot direct chat" not in t:
            continue
        if "chrome" not in t and "google" not in t:
            continue
        if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
            continue
        candidates.append((wid, str(title)))
    if len(candidates) == 1:
        wid, title = candidates[0]
        _save_trusted_dc_anchor(wid, desk, title)
        return wid, "auto_anchor_ok"
    if len(candidates) > 1:
        return None, "auto_anchor_ambiguous_multiple_windows"
    return None, "auto_anchor_not_found"


def _trusted_or_autodetected_dc_anchor(expected_profile: str | None = None) -> tuple[str | None, str]:
    active, active_status = _active_dc_anchor_for_current_workspace(expected_profile=expected_profile)
    if active:
        return active, active_status
    trusted, trusted_status = _trusted_dc_anchor_for_current_workspace()
    if trusted:
        return trusted, trusted_status
    auto, auto_status = _autodetect_dc_anchor_for_current_workspace(expected_profile=expected_profile)
    if auto:
        return auto, auto_status
    return None, f"{trusted_status}; {auto_status}"


def _record_browser_windows(session_id: str, items: list[dict]) -> None:
    data = _browser_windows_load()
    sess = data.get(session_id)
    if not isinstance(sess, dict):
        sess = {"items": []}
    if not isinstance(sess.get("items"), list):
        sess["items"] = []

    now = time.time()
    keep: list[dict] = []
    for it in sess["items"]:
        if not isinstance(it, dict):
            continue
        ts = float(it.get("ts", 0) or 0)
        if ts and (now - ts) < 30 * 60:
            keep.append(it)
    keep.extend(items)

    seen = set()
    deduped: list[dict] = []
    for it in reversed(keep):
        win_id = str(it.get("win_id", "")).strip()
        url = str(it.get("url", "")).strip()
        key = (win_id, url)
        if not win_id or key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    sess["items"] = list(reversed(deduped))[-40:]
    data[session_id] = sess
    _browser_windows_save(data)


def _close_recorded_browser_windows(session_id: str) -> tuple[int, list[str]]:
    data = _browser_windows_load()
    sess = data.get(session_id)
    if not isinstance(sess, dict):
        return 0, []
    items = sess.get("items", [])
    if not isinstance(items, list) or not items:
        return 0, []
    if not shutil.which("wmctrl"):
        return 0, ["wmctrl_missing"]

    closed = 0
    errors: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        win_id = str(it.get("win_id", "")).strip()
        if not win_id:
            continue
        try:
            subprocess.run(["wmctrl", "-ic", win_id], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            closed += 1
        except Exception as e:
            errors.append(str(e))

    data.pop(session_id, None)
    _browser_windows_save(data)
    return closed, errors


def _reset_recorded_browser_windows(session_id: str) -> None:
    data = _browser_windows_load()
    if session_id in data:
        data.pop(session_id, None)
        _browser_windows_save(data)


def _looks_like_open_request(normalized: str) -> bool:
    tokens = ("abr", "abri", "abir", "abrir", "open", "entra", "entrar", "ir a", "lanz", "inici")
    return any(t in normalized for t in tokens)


def _looks_like_direct_gemini_open(normalized: str) -> bool:
    has_gemini = any(t in normalized for t in SITE_CANONICAL_TOKENS.get("gemini", []))
    if not has_gemini:
        return False
    openish = _looks_like_open_request(normalized) or any(t in normalized for t in ("acceso directo", "shortcut"))
    return bool(openish)

def _read_meminfo() -> dict:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            parts = line.split(":")
            if len(parts) < 2:
                continue
            key = parts[0].strip()
            val = parts[1].strip().split()[0]
            if val.isdigit():
                out[key] = int(val)  # kB
    except Exception:
        return {}
    return out


def _proc_rss_mb(pid: int) -> float | None:
    try:
        statm = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8").split()
        if len(statm) < 2:
            return None
        rss_pages = int(statm[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (rss_pages * page_size) / (1024 * 1024)
    except Exception:
        return None


def _read_vram_nvidia() -> dict | None:
    # Cache for a few seconds to avoid hammering nvidia-smi.
    now = time.time()
    if (now - float(_VRAM_CACHE.get("ts", 0.0) or 0.0)) < 4.0:
        return _VRAM_CACHE.get("data")

    smi = shutil.which("nvidia-smi")
    if not smi:
        _VRAM_CACHE["ts"] = now
        _VRAM_CACHE["data"] = None
        return None
    try:
        proc = subprocess.run(
            [
                smi,
                "--query-gpu=memory.used,memory.total,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        line = (proc.stdout or "").strip().splitlines()[:1]
        if not line:
            raise RuntimeError("empty")
        parts = [p.strip() for p in line[0].split(",")]
        used = float(parts[0])
        total = float(parts[1])
        name = parts[2] if len(parts) > 2 else ""
        data = {"used_mb": used, "total_mb": total, "name": name}
        _VRAM_CACHE["ts"] = now
        _VRAM_CACHE["data"] = data
        return data
    except Exception:
        _VRAM_CACHE["ts"] = now
        _VRAM_CACHE["data"] = None
        return None



def _extract_topic(message: str) -> str | None:
    patterns = [
        r"iniciar (?:una )?conversacion(?: nueva)? sobre ([^.,;:\n]+)",
        r"conversacion(?: nueva)? sobre ([^.,;:\n]+)",
        r"chat nuevo sobre ([^.,;:\n]+)",
        r"sobre ([^.,;:\n]+)",
    ]
    text = _normalize_text(message)
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            topic = m.group(1).strip(" \"'").strip()
            if topic:
                return topic[:120]
    return None


def _canonical_site_keys(message: str) -> list[str]:
    text = _normalize_text(message)
    found = []
    for key, tokens in SITE_CANONICAL_TOKENS.items():
        if any(token in text for token in tokens):
            found.append(key)
    return found


def _open_firefox_urls(urls: list[str]) -> tuple[list[str], str | None]:
    opened = []
    for url in urls:
        try:
            subprocess.Popen(
                ["firefox", "--new-tab", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            opened.append(url)
        except FileNotFoundError:
            return opened, "No pude abrir Firefox: comando no encontrado en el sistema."
        except Exception as e:
            return opened, f"No pude abrir Firefox: {e}"
    return opened, None


def _load_browser_profile_config() -> dict:
    config = dict(DEFAULT_BROWSER_PROFILE_CONFIG)
    try:
        if PROFILE_CONFIG_PATH.exists():
            raw = json.loads(PROFILE_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(k, str) and isinstance(v, dict):
                        config[k] = v
    except Exception:
        pass
    return config


def _expected_profile_directory_for_site(site_key: str | None) -> str:
    cfg = _load_browser_profile_config()
    site_cfg = cfg.get(site_key or "", {})
    if not site_cfg:
        site_cfg = cfg.get("_default", {})
    hint = str(site_cfg.get("profile", "")).strip()
    return _resolve_chrome_profile_directory(hint)


def _chrome_command() -> str | None:
    for cmd in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        found = shutil.which(cmd)
        if found:
            return found
    return None


def _resolve_chrome_profile_directory(profile_hint: str) -> str:
    hint = profile_hint.strip()
    if not hint:
        hint = "Default"

    chrome_root = Path.home() / ".config" / "google-chrome"
    local_state = chrome_root / "Local State"
    known_keys: list[str] = []
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        info = data.get("profile", {}).get("info_cache", {})
        if isinstance(info, dict):
            known_keys = [k for k in info.keys() if isinstance(k, str)]
            hint_norm = hint.lower().strip()
            # Prefer a human profile-name match first ("diego" -> "Profile 1"),
            # then fall back to exact profile-directory key.
            for key, value in info.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                name = str(value.get("name", "")).lower().strip()
                if name == hint_norm:
                    return key
            for key in known_keys:
                if key.lower().strip() == hint_norm:
                    return key
    except Exception:
        pass

    if (chrome_root / hint).is_dir():
        return hint

    if (chrome_root / "Default").is_dir():
        return "Default"
    for key in known_keys:
        if (chrome_root / key).is_dir():
            return key
    return "Default"


def _fallback_profiled_chrome_anchor_for_workspace(
    desktop_idx: int, expected_profile: str | None
) -> tuple[str | None, str]:
    active = _xdotool_active_window()
    strict_candidates: list[str] = []
    lenient_candidates: list[str] = []
    for wid, pid_raw, title in _wmctrl_windows_for_desktop(desktop_idx):
        t = str(title).lower().strip()
        if "chrome" not in t and "google" not in t:
            continue
        lenient_candidates.append(wid)
        if expected_profile and not _window_matches_profile(pid_raw, expected_profile):
            continue
        if active and wid.lower() == active.lower():
            return wid, "fallback_active_profiled_chrome"
        strict_candidates.append(wid)
    if strict_candidates:
        return strict_candidates[-1], "fallback_recent_profiled_chrome"
    if active and any(w.lower() == active.lower() for w in lenient_candidates):
        return active, "fallback_active_chrome_unverified_profile"
    if lenient_candidates:
        return lenient_candidates[-1], "fallback_recent_chrome_unverified_profile"
    return None, "fallback_profiled_chrome_not_found"


def _spawn_profiled_chrome_anchor_for_workspace(
    desktop_idx: int, expected_profile: str | None
) -> tuple[str | None, str]:
    chrome_cmd = _chrome_command()
    if not chrome_cmd:
        return None, "chrome_command_missing"
    profile = str(expected_profile or "").strip()
    if not profile:
        profile = "Default"
    before_ids = set(_wmctrl_list().keys())
    try:
        subprocess.Popen(
            [chrome_cmd, f"--profile-directory={profile}", "--new-window", "about:blank"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return None, f"spawn_profiled_chrome_failed: {e}"
    win_id, desk = _find_new_profiled_chrome_window(before_ids, expected_profile=profile, timeout_s=8.0)
    if not win_id:
        win_id, desk = _find_new_profiled_chrome_window(before_ids, expected_profile=None, timeout_s=4.0)
        if win_id and desk is not None and int(desk) == int(desktop_idx):
            return win_id, "spawn_chrome_unverified_profile_ok"
    if not win_id:
        return None, "spawn_profiled_chrome_not_detected"
    if desk is None:
        return None, "spawn_profiled_chrome_workspace_unknown"
    if int(desk) != int(desktop_idx):
        # Workspace safety: never move windows across workspaces.
        return None, f"spawn_profiled_chrome_other_workspace={desk}"
    return win_id, "spawn_profiled_chrome_ok"


def _open_url_with_site_context(url: str, site_key: str | None, session_id: str | None = None) -> str | None:
    cfg = _load_browser_profile_config()
    site_cfg = cfg.get(site_key or "", {})
    if not site_cfg:
        site_cfg = cfg.get("_default", {})
    browser = str(site_cfg.get("browser", "")).lower().strip()
    profile = _expected_profile_directory_for_site(site_key)

    if browser == "chrome":
        # Strict: open only from the visible DC Chrome client in this workspace.
        desk = _wmctrl_current_desktop()
        if desk is None:
            return "No pude detectar el workspace actual."
        wins = _wmctrl_windows_for_desktop(desk)
        anchor, anchor_status = _trusted_or_autodetected_dc_anchor(expected_profile=profile)
        fallback_status = ""
        spawn_status = ""
        if not anchor:
            anchor, fallback_status = _fallback_profiled_chrome_anchor_for_workspace(desk, profile)
        if not anchor:
            anchor, spawn_status = _spawn_profiled_chrome_anchor_for_workspace(desk, profile)
        if not anchor:
            return (
                "No abrí nada para evitar mezclar clientes: no encontré cliente Chrome del perfil diego "
                "en este workspace. "
                f"(anchor={anchor_status}; fallback={fallback_status or 'n/a'}; spawn={spawn_status or 'n/a'})"
            )

        before_ids = {wid for wid, _, _ in wins}
        _xdotool_command(["windowactivate", anchor], timeout=2.5)
        time.sleep(0.18)
        _xdotool_command(["key", "--window", anchor, "ctrl+n"], timeout=2.0)

        target = ""
        for _ in range(80):
            now = _wmctrl_windows_for_desktop(desk)
            for wid, _pid_raw, title in now:
                t = str(title).lower()
                if wid in before_ids:
                    continue
                if "chrome" in t or "google" in t:
                    target = wid
                    break
            if target:
                break
            time.sleep(0.08)
        if not target:
            return "No abrí nada para evitar mezclar clientes: no se detectó una nueva ventana desde el cliente diego."

        _xdotool_command(["windowactivate", target], timeout=2.5)
        time.sleep(0.10)
        _xdotool_command(["key", "--window", target, "ctrl+l"], timeout=2.0)
        time.sleep(0.06)
        _xdotool_command(
            ["type", "--delay", "16", "--clearmodifiers", "--window", target, str(url)],
            timeout=8.0,
        )
        time.sleep(0.06)
        _xdotool_command(["key", "--window", target, "Return"], timeout=2.0)

        if session_id:
            title = _wmctrl_list().get(target, "")
            _record_browser_windows(
                session_id,
                [{"win_id": target, "title": title, "url": url, "site_key": site_key, "ts": time.time()}],
            )
        return None

    try:
        subprocess.Popen(
            ["firefox", "--new-tab", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return None
    except FileNotFoundError:
        return "No pude abrir Firefox: comando no encontrado en el sistema."
    except Exception as e:
        return f"No pude abrir Firefox: {e}"


def _open_site_urls(entries: list[tuple[str | None, str]], session_id: str | None = None) -> tuple[list[str], str | None]:
    opened = []
    for site_key, url in entries:
        if site_key == "gemini":
            gem_opened, gem_error = _open_gemini_client_flow(session_id=session_id)
            if gem_error:
                return opened, gem_error
            opened.extend(gem_opened)
            continue
        error = _open_url_with_site_context(url, site_key, session_id=session_id)
        if error:
            return opened, error
        opened.append(url)
    return opened, None


def _open_gemini_client_flow(session_id: str | None = None) -> tuple[list[str], str | None]:
    # Deterministic + workspace-safe "human-like" flow:
    # 1) from a Chrome window in the current workspace with expected profile
    # 2) open new window, then Google -> Gemini in that same client/profile
    expected_profile = _expected_profile_directory_for_site("gemini")
    ok, detail = _open_gemini_in_current_workspace_via_ui(
        expected_profile=expected_profile, session_id=session_id
    )
    if not ok:
        return (
            [],
            (
                "No pude abrir Gemini en el cliente configurado dentro de este workspace. "
                f"({detail}) "
                "Dejá visible una ventana de Chrome del perfil diego (Profile 1), por ejemplo Molbot Direct Chat, y repetí."
            ),
        )
    return ["https://www.google.com/", _site_url("gemini")], None


def _site_url(site_key: str) -> str:
    if site_key == "chatgpt":
        return SITE_ALIASES["chatgpt"]
    if site_key == "gemini":
        return SITE_ALIASES["gemini"]
    if site_key == "youtube":
        return SITE_ALIASES["youtube"]
    if site_key == "wikipedia":
        return SITE_ALIASES["wikipedia"]
    if site_key == "gmail":
        return SITE_ALIASES["gmail"]
    return SITE_ALIASES.get(site_key, "about:blank")


def _build_site_search_url(site_key: str, query: str) -> str | None:
    template = SITE_SEARCH_TEMPLATES.get(site_key)
    if not template:
        return None
    return template.format(q=quote_plus(query))


def _looks_like_youtube_play_request(normalized: str) -> bool:
    if "youtube" not in normalized and "you tube" not in normalized:
        return False
    playish = any(
        t in normalized
        for t in (
            "reproduc",
            "play",
            "pone",
            "ponelo",
            "ponela",
            "primer video",
            "abrí un video",
            "abri un video",
            "abrir un video",
        )
    )
    return playish


def _sanitize_youtube_query(query: str) -> str:
    q = (query or "").strip().strip("\"'").strip()
    if not q:
        return q
    # Cut trailing action clauses ("y abrí...", "y reproducilo...", "y dale play...")
    q = re.sub(
        r"\s+(?:y|e)\s+(?:abri|abr[ií]|abrir|abre|reproduc\w*|pon(?:e|é)\w*|dale\s+play|play)\b.*$",
        "",
        q,
        flags=re.IGNORECASE,
    ).strip()
    # Keep query compact and deterministic for SearXNG/yt-dlp.
    q = re.sub(r"\s+", " ", q).strip(" ,.;:-")
    return q


def _is_direct_youtube_video_url(url: str) -> bool:
    u = str(url or "").strip()
    if not u:
        return False
    p = urlparse(u)
    host = (p.netloc or "").lower()
    if "youtu.be" in host:
        return bool((p.path or "").strip("/"))
    if "youtube.com" not in host:
        return False
    path = (p.path or "").strip()
    if path.startswith("/watch"):
        q = parse_qs(p.query)
        v = str((q.get("v", [""])[0] or "")).strip()
        return bool(v)
    if path.startswith("/shorts/") or path.startswith("/live/"):
        return bool(path.split("/", 2)[-1].strip())
    return False


def _pick_first_youtube_video_url(query: str) -> tuple[str | None, str]:
    clean_query = _sanitize_youtube_query(query) or (query or "").strip()

    def from_ytdlp() -> str | None:
        ytdlp = shutil.which("yt-dlp")
        if not ytdlp:
            return None
        try:
            proc = subprocess.run(
                [
                    ytdlp,
                    "--no-playlist",
                    "--get-id",
                    "--default-search",
                    "ytsearch",
                    f"ytsearch1:{clean_query}",
                ],
                capture_output=True,
                text=True,
                timeout=14,
            )
            vid = (proc.stdout or "").strip().splitlines()
            if not vid:
                return None
            v = vid[0].strip()
            if not v:
                return None
            return f"https://www.youtube.com/watch?v={v}"
        except Exception:
            return None

    def normalize_candidate(raw_url: str) -> str:
        u = str(raw_url or "").strip()
        if not u:
            return ""
        p = urlparse(u)
        host = (p.netloc or "").lower()
        if "youtube.com" in host or "youtu.be" in host:
            return u
        # Some engines wrap destination in query param (e.g., ?url=...)
        try:
            q = parse_qs(p.query)
            for key in ("url", "target", "u"):
                vals = q.get(key, [])
                if not vals:
                    continue
                cand = str(vals[0]).strip()
                cp = urlparse(cand)
                ch = (cp.netloc or "").lower()
                if "youtube.com" in ch or "youtu.be" in ch:
                    return cand
        except Exception:
            return ""
        return ""

    results: list[dict] = []
    sp = web_search.searxng_search(clean_query, site_key="youtube", max_results=10)
    if sp.get("ok") and isinstance(sp.get("results"), list):
        results.extend([r for r in sp.get("results", []) if isinstance(r, dict)])
    # Fallback: some SearXNG setups don't keep YouTube engine/domain filter stable.
    sp2 = web_search.searxng_search(clean_query, site_key=None, max_results=12)
    if sp2.get("ok") and isinstance(sp2.get("results"), list):
        results.extend([r for r in sp2.get("results", []) if isinstance(r, dict)])
    if not results:
        yd = from_ytdlp()
        if yd:
            chosen = yd
            if "autoplay=" not in chosen:
                chosen = chosen + ("&" if "?" in chosen else "?") + "autoplay=1"
            return chosen, "ok_ytdlp"
        return None, "no_results"

    preferred: str | None = None
    for r in results:
        if not isinstance(r, dict):
            continue
        url = normalize_candidate(str(r.get("url", "")).strip())
        if not url:
            continue
        if not _is_direct_youtube_video_url(url):
            continue
        preferred = url
        break
    chosen = preferred
    if not chosen:
        yd = from_ytdlp()
        if yd:
            chosen = yd
        else:
            return None, "no_youtube_video_url"
    if "autoplay=" not in chosen:
        chosen = chosen + ("&" if "?" in chosen else "?") + "autoplay=1"
    return chosen, "ok"

def _history_path(session_id: str) -> Path:
    return HISTORY_DIR / f"{_safe_session_id(session_id)}.json"


def _load_history(session_id: str) -> list:
    p = _history_path(session_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            out = []
            for item in data:
                if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                    out.append({"role": item["role"], "content": item["content"]})
            return out[-200:]
    except Exception:
        return []
    return []


def _save_history(session_id: str, history: list) -> None:
    p = _history_path(session_id)
    payload = history[-200:]
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _guardrail_check(session_id: str, tool_name: str, params: dict | None = None) -> tuple[bool, str]:
    if str(os.environ.get("GUARDRAIL_ENABLED", "1")).strip().lower() not in ("1", "true", "yes"):
        return True, "guardrail_disabled"
    fail_closed = str(os.environ.get("GUARDRAIL_FAIL_CLOSED", "0")).strip().lower() in ("1", "true", "yes")
    if not GUARDRAIL_SCRIPT_PATH.exists():
        return True, "guardrail_script_missing"
    payload = params or {}
    try:
        proc = subprocess.run(
            [str(GUARDRAIL_SCRIPT_PATH), str(session_id), str(tool_name), json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=6.0,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
    except Exception as e:
        if fail_closed:
            return False, f"guardrail_exec_error: {e}"
        return True, f"guardrail_bypass_exec_error: {e}"
    detail = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        if (not fail_closed) and detail.startswith("GUARDRAIL_ERROR:"):
            return True, f"guardrail_bypass_infra_error: {detail}"
        return False, detail or f"guardrail_denied rc={proc.returncode}"
    return True, detail or "guardrail_ok"


def _guardrail_block_reply(tool_name: str, detail: str) -> str:
    reason = str(detail or "").strip()[:280]
    return (
        f"Bloqueado por guardrail ({tool_name}). "
        f"Detalle: {reason if reason else 'policy_denied'}"
    )


def _normalize_allowed_tool_name(name: str) -> str:
    t = str(name or "").strip().lower()
    alias = {
        "escritorio": "desktop",
        "modelo": "model",
    }
    return alias.get(t, t)


def _extract_allowed_tools(payload: dict) -> set[str]:
    out: set[str] = set()

    raw = payload.get("allowed_tools")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if v:
                out.add(_normalize_allowed_tool_name(str(k)))
    elif isinstance(raw, (list, tuple, set)):
        for item in raw:
            if isinstance(item, str):
                t = _normalize_allowed_tool_name(item)
                if t:
                    out.add(t)

    # Backward compatibility with legacy clients/scripts that still send {"tools": {...}}.
    legacy = payload.get("tools")
    if isinstance(legacy, dict):
        for k, v in legacy.items():
            if v:
                t = _normalize_allowed_tool_name(str(k))
                if t:
                    out.add(t)
    elif isinstance(legacy, (list, tuple, set)):
        for item in legacy:
            if isinstance(item, str):
                t = _normalize_allowed_tool_name(item)
                if t:
                    out.add(t)

    return out


def _maybe_handle_local_action(message: str, allowed_tools: set[str], session_id: str) -> dict | None:
    text = message.lower()
    normalized = _normalize_text(message)
    shadow_explicit = any(k in normalized for k in ("shadow", "experimental", "modo shadow"))

    if (
        ("cliente" in normalized and "diego" in normalized and any(k in normalized for k in ("fij", "usar", "set")))
        or ("este cliente es diego" in normalized)
    ):
        active = _xdotool_active_window()
        if not active:
            return {"reply": "No pude detectar la ventana activa. Activá DC en Chrome y repetí."}
        title = str(_wmctrl_list().get(active, ""))
        t = title.lower()
        if "molbot direct chat" not in t or ("chrome" not in t and "google" not in t):
            return {"reply": "La ventana activa no es Molbot Direct Chat en Chrome. Activala y repetí."}
        desk = _wmctrl_window_desktop(active)
        if desk is None:
            return {"reply": "No pude detectar el workspace de la ventana activa."}
        _save_trusted_dc_anchor(active, desk, title)
        return {"reply": f"Listo. Fijé este cliente como diego (anchor={active}, workspace={desk})."}

    yt_transport = _extract_youtube_transport_request(message)
    if yt_transport:
        if "firefox" not in allowed_tools:
            return {"reply": "La herramienta local 'firefox' está deshabilitada en esta sesión."}
        action, close_window = yt_transport
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {
                "action": f"youtube_transport_{action}",
                "site": "youtube",
                "url": "https://www.youtube.com/",
                "close_window": int(close_window),
            },
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        ok, detail = _youtube_transport_action(action, close_window=close_window, session_id=session_id)
        if not ok:
            return {"reply": f"No pude controlar YouTube en este workspace. ({detail})"}
        if close_window:
            return {"reply": f"Listo: detuve YouTube y cerré la ventana en este workspace. ({detail})"}
        if action == "play":
            return {"reply": f"Listo: reanudé YouTube en este workspace. ({detail})"}
        return {"reply": f"Listo: pausé YouTube en este workspace. ({detail})"}

    # Close browser windows opened by this system (tracked by session).
    # Examples:
    # - "cerrá las ventanas web que abriste"
    # - "reset ventanas web"
    if any(k in normalized for k in ("web", "navegador", "browser")) and any(k in normalized for k in ("ventan", "windows")):
        if any(k in normalized for k in ("cerr", "close", "cierra")):
            closed, errors = _close_recorded_browser_windows(session_id=session_id)
            if closed == 0 and not errors:
                fallback_closed, _fallback_details = _close_known_site_windows_in_current_workspace(max_windows=12)
                if fallback_closed > 0:
                    return {"reply": f"Cerré {fallback_closed} ventana(s) web en este workspace por fallback de sitio."}
            if errors:
                return {"reply": f"Cerré {closed} ventana(s) web que abrí. Errores: {', '.join(errors)[:260]}"}
            return {"reply": f"Cerré {closed} ventana(s) web que abrí (solo las registradas por el sistema)."}
        if any(k in normalized for k in ("reset", "reinic", "olvid", "limpia")):
            _reset_recorded_browser_windows(session_id=session_id)
            return {"reply": "Listo: limpié el registro de ventanas web abiertas por el sistema para esta sesión."}

    # Human variant fallback:
    # "cerrá la ventana que abriste recién" (without explicit "web/browser")
    if any(k in normalized for k in ("cerr", "close", "cierra")) and any(
        k in normalized for k in ("ventan", "window", "pestañ", "tab")
    ):
        closed, errors = _close_recorded_browser_windows(session_id=session_id)
        if closed > 0 or errors:
            if errors:
                return {"reply": f"Cerré {closed} ventana(s) web que abrí. Errores: {', '.join(errors)[:260]}"}
            return {"reply": f"Cerré {closed} ventana(s) web que abrí (solo las registradas por el sistema)."}
        fallback_closed, _fallback_details = _close_known_site_windows_in_current_workspace(max_windows=12)
        if fallback_closed > 0:
            return {"reply": f"Cerré {fallback_closed} ventana(s) web en este workspace por fallback de sitio."}

        return {"reply": "No veo ventanas registradas por esta sesión para cerrar."}

    # Safe local opens/closes for Desktop items (no deletion).
    # Examples:
    # - "abrí carpeta Lucy del escritorio"
    # - "abrí Moscu del escritorio"
    # - "cerrá las ventanas que abriste del escritorio"
    if any(k in normalized for k in ("escritorio", "desktop")):
        if any(k in normalized for k in ("reset", "reinic", "olvid", "limpia")) and any(k in normalized for k in ("ventan", "registro", "track")):
            if "desktop" not in allowed_tools:
                return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
            ok_g, gd = _guardrail_check(session_id, "desktop", {"action": "reset_windows"})
            if not ok_g:
                return {"reply": _guardrail_block_reply("desktop", gd)}
            desktop_ops.reset_recorded_windows(session_id=session_id)
            return {"reply": "Listo: limpié el registro de ventanas abiertas por el sistema para esta sesión."}

        if any(k in normalized for k in ("cerr", "close", "cierra")):
            if "desktop" not in allowed_tools:
                return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
            ok_g, gd = _guardrail_check(session_id, "desktop", {"action": "close_windows"})
            if not ok_g:
                return {"reply": _guardrail_block_reply("desktop", gd)}
            closed, errors = desktop_ops.close_recorded_windows(session_id=session_id)
            if errors:
                return {"reply": f"Cerré {closed} ventana(s) que abrí. Errores: {', '.join(errors)[:260]}"}
            return {"reply": f"Cerré {closed} ventana(s) que abrí (solo las registradas por el sistema)."}

        m_open = re.search(
            r"(?:abr[ií]|abrir|open)\s+(?:la\s+)?(?:carpeta|archivo|documento)?\s*([^\n\r]+?)\s+(?:del|en|de)\s+(?:mi\s+)?(?:escritorio|desktop)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if m_open:
            if "desktop" not in allowed_tools:
                return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
            name = m_open.group(1).strip(" \"'").strip()
            ok_g, gd = _guardrail_check(session_id, "desktop", {"action": "open_item", "name": name})
            if not ok_g:
                return {"reply": _guardrail_block_reply("desktop", gd)}
            res = desktop_ops.open_desktop_item(name, session_id=session_id)
            if not res.get("ok"):
                return {"reply": str(res.get("error", "No pude abrir el item del escritorio."))}
            tracked = int(res.get("tracked_windows", 0) or 0)
            verify = " (verificado por ventana)" if tracked else " (no pude verificar ventana; lo abrí igualmente)"
            return {
                "reply": f"Listo: abrí {res.get('kind')} '{res.get('name')}'.{verify} Ruta: {res.get('path')}"
            }

    # One-time helper: open a shadow-profile Chrome window so the user can login manually.
    # This avoids brittle automation failures like "login_required" for ChatGPT/Gemini.
    m_login = re.search(
        r"(?:login|loguea|logueate|inicia\s+sesion|iniciar\s+sesion)\s+(?:en\s+)?(chatgpt|chat\s*gpt|gemini)\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if m_login:
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'web_ask' está deshabilitada en esta sesión."}
        if not shadow_explicit:
            return {
                "reply": (
                    "Bloqueado por política de cliente: login web_ask usa shadow profile. "
                    "Si querés ejecutarlo explícitamente, pedilo con 'login shadow gemini' o 'login shadow chatgpt'."
                )
            }
        provider = m_login.group(1).strip().lower()
        site_key = "chatgpt" if "chat" in provider else "gemini"
        login_url = _site_url(site_key) or f"https://{site_key}.com/"
        ok_g, gd = _guardrail_check(session_id, "browser_vision", {"action": "bootstrap_login", "url": login_url, "site": site_key})
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        ok, info = web_ask.bootstrap_login(site_key)
        if not ok:
            return {"reply": f"No pude lanzar bootstrap de login para {site_key}: {info}"}
        return {
            "reply": (
                f"Abrí una ventana de Chrome (shadow profile) para loguearte en {site_key}. "
                "Iniciá sesión ahí y luego cerrá esa ventana. Después probá de nuevo: "
                f"dialoga con {site_key}: <tu pregunta>"
            )
        }

    gemini_ask_text = _extract_gemini_ask_request(message)
    if gemini_ask_text:
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'gemini write' está deshabilitada en esta sesión."}
        ok_g, gd = _guardrail_check(
            session_id,
            "web_ask",
            {"site": "gemini", "prompt": gemini_ask_text[:500], "action": "ask"},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("web_ask", gd)}
        result = web_ask.run_web_ask("gemini", gemini_ask_text, timeout_ms=60000, followups=None)
        reply = web_ask.format_web_ask_reply("gemini", gemini_ask_text, result)
        return {"reply": reply}

    gemini_write_text = _extract_gemini_write_request(message)
    if gemini_write_text:
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'gemini write' está deshabilitada en esta sesión."}
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "gemini_write", "url": "https://gemini.google.com/app", "text": gemini_write_text[:500]},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        ok, detail = _gemini_write_in_current_workspace(gemini_write_text, session_id=session_id)
        if ok:
            return {"reply": f"Listo: escribí en Gemini \"{gemini_write_text}\" y di Enter. ({detail})"}
        return {"reply": f"No pude escribir en Gemini automáticamente (no verificado). ({detail})"}

    web_req = web_ask.extract_web_ask_request(message)
    if web_req is not None:
        # web_ask is separate from opening URLs via firefox. Keep backward-compat:
        # if someone only enabled firefox (old UI), still allow web_ask.
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'web_ask' está deshabilitada en esta sesión."}
        site_key, prompt, followups = web_req
        site_url = _site_url(site_key) or f"https://{site_key}.com/"
        ok_g, gd = _guardrail_check(
            session_id,
            "web_ask",
            {"site": site_key, "url": site_url, "prompt": prompt[:500], "action": "dialog"},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("web_ask", gd)}

        result = web_ask.run_web_ask(site_key, prompt, timeout_ms=60000, followups=followups)
        reply = web_ask.format_web_ask_reply(site_key, prompt, result)
        if str(result.get("status", "")).strip() in ("login_required", "captcha_required"):
            reply += (
                "\n\nNo abrí shadow profile automáticamente (política estricta de cliente). "
                "Si querés hacerlo, pedí explícitamente: 'login shadow gemini' o 'login shadow chatgpt'."
            )
        return {"reply": reply}

    if "firefox" in text and any(k in normalized for k in ("abr", "open", "lanz", "inici")):
        if "firefox" not in allowed_tools:
            return {"reply": "La herramienta local 'firefox' está deshabilitada en esta sesión."}
        url = _extract_url(message) or "about:blank"
        ok_g, gd = _guardrail_check(session_id, "browser_vision", {"action": "open_url", "url": url})
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        opened, error = _open_site_urls([(None, url)], session_id=session_id)
        if error:
            return {"reply": error}
        return {"reply": f"Listo, abrí Firefox en: {opened[0]}"}

    site_keys = _canonical_site_keys(message)
    wants_open = _looks_like_open_request(normalized)
    wants_search = ("busc" in normalized) or any(k in normalized for k in ("search", "investiga", "investigar"))
    wants_new_chat = any(k in normalized for k in ("chat nuevo", "nuevo chat", "iniciar una conversacion", "iniciar conversacion"))
    topic = _extract_topic(message)

    # Hard rule: "open Gemini" (or close variants) always executes the same deterministic flow.
    if "firefox" in allowed_tools and _looks_like_direct_gemini_open(normalized) and not wants_search and not wants_new_chat:
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "open_site", "site": "gemini", "url": "https://gemini.google.com/app"},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        opened, error = _open_gemini_client_flow(session_id=session_id)
        if error:
            return {"reply": error}
        return {"reply": "Abrí Gemini en el cliente correcto con el flujo entrenado (Google -> Gemini)."}

    search_req = web_search.extract_web_search_request(message)
    if "firefox" in allowed_tools and search_req and search_req[1] == "youtube" and _looks_like_youtube_play_request(normalized):
        query = search_req[0]
        ok_g, gd = _guardrail_check(
            session_id,
            "web_search",
            {"action": "search_video", "query": query[:500], "site": "youtube"},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("web_search", gd)}
        video_url, reason = _pick_first_youtube_video_url(query)
        if not video_url:
            return {"reply": f"No pude encontrar un video reproducible en YouTube para '{query}'. ({reason})"}
        ok_g2, gd2 = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "open_video", "site": "youtube", "url": video_url},
        )
        if not ok_g2:
            return {"reply": _guardrail_block_reply("browser_vision", gd2)}
        opened, error = _open_site_urls([("youtube", video_url)], session_id=session_id)
        if error:
            return {"reply": error}
        return {"reply": f"Abrí y reproduzco un video de YouTube sobre '{query}': {opened[0]}"}

    if search_req and ("web_search" in allowed_tools):
        query, site_key = search_req
        ok_g, gd = _guardrail_check(
            session_id,
            "web_search",
            {"action": "search", "query": query[:500], "site": (site_key or "")},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("web_search", gd)}
        sp = web_search.searxng_search(query, site_key=site_key)
        if not sp.get("ok"):
            err = str(sp.get("error", "web_search_failed"))
            return {"reply": f"No pude buscar en SearXNG local: {err}"}
        return {"reply": web_search.format_results_for_user(sp)}

    if "firefox" in allowed_tools and wants_new_chat and topic and ("chatgpt" in site_keys or "gemini" in site_keys):
        entries = []
        if "chatgpt" in site_keys:
            entries.append(("chatgpt", _site_url("chatgpt")))
        if "gemini" in site_keys:
            entries.append(("gemini", _site_url("gemini")))
        if "youtube" in site_keys:
            yt_url = _build_site_search_url("youtube", topic)
            if yt_url:
                entries.append(("youtube", yt_url))
        if "wikipedia" in site_keys:
            wiki_url = _build_site_search_url("wikipedia", topic)
            if wiki_url:
                entries.append(("wikipedia", wiki_url))

        if entries:
            urls = [u for _k, u in entries if u]
            ok_g, gd = _guardrail_check(
                session_id,
                "browser_vision",
                {"action": "open_multiple", "url": (urls[0] if urls else ""), "urls": urls},
            )
            if not ok_g:
                return {"reply": _guardrail_block_reply("browser_vision", gd)}
            opened, error = _open_site_urls(entries, session_id=session_id)
            if error:
                return {"reply": error}
            prompt = (
                "Prompt sugerido para pegar en ChatGPT/Gemini: "
                f"'Iniciemos una conversación sobre {topic}. "
                "Dame contexto geopolítico actual, actores clave, riesgos y escenarios probables.'"
            )
            return {"reply": f"Abrí recursos para el tema '{topic}': {' | '.join(opened)}\n{prompt}"}

    m_yt_about = re.search(r"(?:video|videos)\s+de\s+youtube\s+sobre\s+(.+)", normalized, flags=re.IGNORECASE)
    if "firefox" in allowed_tools and m_yt_about:
        query = m_yt_about.group(1).strip(" .")
        if query in ("el tema", "ese tema", "este tema") and topic:
            query = topic
        url = _build_site_search_url("youtube", query)
        if not url:
            return {"reply": "No pude construir la búsqueda en YouTube."}
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "open_site_search", "site": "youtube", "url": url},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        opened, error = _open_site_urls([("youtube", url)], session_id=session_id)
        if error:
            return {"reply": error}
        return {"reply": f"Abrí videos de YouTube sobre '{query}': {opened[0]}"}

    if "firefox" in allowed_tools and site_keys and wants_open and not wants_search and not wants_new_chat:
        entries = [(site_key, _site_url(site_key)) for site_key in site_keys]
        urls = [u for _k, u in entries if u]
        ok_g, gd = _guardrail_check(
            session_id,
            "browser_vision",
            {"action": "open_sites", "url": (urls[0] if urls else ""), "urls": urls},
        )
        if not ok_g:
            return {"reply": _guardrail_block_reply("browser_vision", gd)}
        opened, error = _open_site_urls(entries, session_id=session_id)
        if error:
            return {"reply": error}
        listing = " | ".join(opened)
        return {"reply": f"Abrí estos sitios: {listing}"}

    wants_desktop = any(k in text for k in ("escritorio", "desktop"))
    asks_dirs = any(k in text for k in ("carpeta", "carpetas", "folder", "folders", "directorio", "directorios"))
    asks_files = any(k in text for k in ("archivo", "archivos", "file", "files"))
    asks_list = any(k in text for k in ("listar", "lista", "mostrar", "decir", "cuales", "cuáles", "que hay", "qué hay"))
    if wants_desktop and (asks_dirs or asks_files or asks_list):
        if "desktop" not in allowed_tools:
            return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
        ok_g, gd = _guardrail_check(session_id, "desktop", {"action": "list_desktop"})
        if not ok_g:
            return {"reply": _guardrail_block_reply("desktop", gd)}
        home = Path.home()
        candidates = [home / "Escritorio", home / "Desktop"]
        desktop = next((p for p in candidates if p.exists() and p.is_dir()), None)
        if desktop is None:
            return {"reply": "No encontré carpeta de escritorio en ~/Escritorio ni ~/Desktop."}

        entries = sorted(desktop.iterdir(), key=lambda p: p.name.lower())
        dirs = [p.name for p in entries if p.is_dir()]
        files = [p.name for p in entries if p.is_file()]

        if asks_dirs and not asks_files:
            content = ", ".join(dirs) if dirs else "(ninguna)"
            return {"reply": f"Carpetas reales en {desktop}: {content}"}

        if asks_files and not asks_dirs:
            content = ", ".join(files) if files else "(ninguno)"
            return {"reply": f"Archivos reales en {desktop}: {content}"}

        return {
            "reply": (
                f"Contenido real de {desktop} | carpetas: "
                + (", ".join(dirs) if dirs else "(ninguna)")
                + " | archivos: "
                + (", ".join(files) if files else "(ninguno)")
            )
        }

    return None


def _build_system_prompt(mode: str, allowed_tools: set[str]) -> str:
    base = [
        "Habla en español claro.",
        "No inventes resultados.",
        "Si una acción falla, decilo explícitamente.",
    ]
    if mode == "conciso":
        base.append("Respuesta breve (1-3 líneas salvo que pidan detalle).")
    elif mode == "investigacion":
        base.append("Respuesta más detallada y estructurada.")
    else:
        base.append("Modo operativo: directo, preciso, sin relleno.")

    base.append(
        "Herramientas locales habilitadas en esta sesión: " + (", ".join(sorted(allowed_tools)) if allowed_tools else "ninguna")
    )
    return " ".join(base)


def load_gateway_token() -> str:
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    if not cfg_path.exists():
        raise RuntimeError(f"Missing OpenClaw config: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
    if not token:
        raise RuntimeError("Missing gateway.auth.token in ~/.openclaw/openclaw.json")
    return token


class Handler(BaseHTTPRequestHandler):
    server_version = "MolbotDirectChat/2.0"

    def _metrics_payload(self) -> dict:
        pid = os.getpid()
        rss_mb = _proc_rss_mb(pid)
        mem = _read_meminfo()
        mem_total_mb = (mem.get("MemTotal", 0) / 1024.0) if mem else None
        mem_avail_mb = (mem.get("MemAvailable", 0) / 1024.0) if mem else None
        mem_used_mb = (mem_total_mb - mem_avail_mb) if (mem_total_mb is not None and mem_avail_mb is not None) else None
        vram = _read_vram_nvidia()

        return {
            "ts": time.time(),
            "proc": {"pid": pid, "rss_mb": rss_mb},
            "sys": {"ram_total_mb": mem_total_mb, "ram_used_mb": mem_used_mb, "ram_avail_mb": mem_avail_mb},
            "gpu": {"vram": vram},
        }

    def _json(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except BrokenPipeError:
            # Client disconnected; avoid noisy tracebacks and "Empty reply" symptoms.
            return

    def _parse_payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8") or "{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            raw = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if path == "/api/history":
            query = parse_qs(parsed.query)
            sid = _safe_session_id((query.get("session", ["default"])[0]))
            self._json(200, {"session_id": sid, "history": _load_history(sid)})
            return

        if path == "/api/metrics":
            self._json(200, self._metrics_payload())
            return

        self.send_response(404)
        self.end_headers()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def _build_messages(self, message: str, history: list, mode: str, allowed_tools: set[str], attachments: list) -> list:
        clean = []
        if isinstance(history, list):
            for item in history[-60:]:
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                content = item.get("content")
                if role in ("user", "assistant") and isinstance(content, str):
                    clean.append({"role": role, "content": content})

        extra = ""
        if attachments:
            lines = []
            for a in attachments[:8]:
                if not isinstance(a, dict):
                    continue
                name = str(a.get("name", "adjunto"))
                typ = str(a.get("type", "file"))
                content = str(a.get("content", ""))
                lines.append(f"- {name} ({typ})")
                if content and typ == "text":
                    lines.append(content[:3000])
            if lines:
                extra = "\n\nContexto de adjuntos:\n" + "\n".join(lines)

        system = {
            "role": "system",
            "content": _build_system_prompt(mode, allowed_tools),
        }
        return [system] + clean + [{"role": "user", "content": message + extra}]

    def _call_gateway(self, payload: dict) -> dict:
        req = Request(
            url=f"http://127.0.0.1:{self.server.gateway_port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.server.gateway_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def do_POST(self):
        if self.path == "/api/history":
            try:
                payload = self._parse_payload()
                sid = _safe_session_id(str(payload.get("session_id", "default")))
                history = payload.get("history", [])
                if not isinstance(history, list):
                    history = []
                safe = []
                for item in history[-200:]:
                    if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                        safe.append({"role": item["role"], "content": item["content"]})
                _save_history(sid, safe)
                self._json(200, {"ok": True})
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if self.path not in ("/api/chat", "/api/chat/stream"):
            self.send_response(404)
            self.end_headers()
            return

        try:
            payload = self._parse_payload()
            message = str(payload.get("message", "")).strip()
            model = str(payload.get("model", "openai-codex/gpt-5.1-codex-mini")).strip()
            history = payload.get("history", [])
            session_id = _safe_session_id(str(payload.get("session_id", "default")))
            mode = str(payload.get("mode", "operativo"))
            attachments = payload.get("attachments", [])
            allowed_tools = _extract_allowed_tools(payload)
            # Local-only tools that should not be advertised to the upstream model.
            allowed_tools_for_prompt = set(allowed_tools)
            allowed_tools_for_prompt.discard("web_search")

            if not message:
                self._json(400, {"error": "Missing message"})
                return

            local_action = _maybe_handle_local_action(message, allowed_tools, session_id=session_id)
            if local_action is not None:
                if self.path == "/api/chat/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    reply = str(local_action.get("reply", ""))
                    out = json.dumps({"token": reply}, ensure_ascii=False).encode("utf-8")
                    try:
                        self.wfile.write(b"data: " + out + b"\n\n")
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    self.close_connection = True
                    return

                self._json(200, local_action)
                return

            messages = self._build_messages(message, history, mode, allowed_tools_for_prompt, attachments)
            q = web_search.extract_web_search_query(message)
            if q and ("web_search" in allowed_tools):
                ok_g, gd = _guardrail_check(
                    session_id,
                    "web_search",
                    {"action": "search", "query": q[:500], "site": ""},
                )
                if not ok_g:
                    blocked = _guardrail_block_reply("web_search", gd)
                    if self.path == "/api/chat/stream":
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        out = json.dumps({"token": blocked}, ensure_ascii=False).encode("utf-8")
                        try:
                            self.wfile.write(b"data: " + out + b"\n\n")
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()
                        except BrokenPipeError:
                            return
                        self.close_connection = True
                        return
                    self._json(200, {"reply": blocked})
                    return
                sp = web_search.searxng_search(q)
                if not sp.get("ok"):
                    err = str(sp.get("error", "web_search_failed"))
                    if self.path == "/api/chat/stream":
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        out = json.dumps({"token": f"No pude buscar en SearXNG local: {err}"}, ensure_ascii=False).encode("utf-8")
                        try:
                            self.wfile.write(b"data: " + out + b"\n\n")
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()
                        except BrokenPipeError:
                            return
                        self.close_connection = True
                        return
                    self._json(200, {"reply": f"No pude buscar en SearXNG local: {err}"})
                    return

                context = web_search.format_results_for_prompt(sp)
                messages = [
                    messages[0],
                    {
                        "role": "system",
                        "content": (
                            "Se te proveen resultados de busqueda web desde SearXNG local. "
                            "Usalos como base. Si no alcanza para responder, deci que falta. "
                            "No intentes usar herramientas de busqueda externas. "
                            "Cita fuentes mencionando el numero de resultado (1,2,3...).\n\n" + context
                        ),
                    },
                ] + messages[1:]

            if self.path == "/api/chat/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                # Robust pseudo-stream: avoids hanging when upstream SSE behavior
                # changes and still gives progressive UX.
                req_payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2,
                }
                response_data = self._call_gateway(req_payload)
                full = response_data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                if not full.strip():
                    full = (
                        "No recibí texto del modelo en esta vuelta. "
                        "Reformulá en un paso más concreto (por ejemplo: "
                        "'buscá X en YouTube' o 'abrí Y')."
                    )
                step = 18
                for i in range(0, len(full), step):
                    token = full[i:i + step]
                    out = json.dumps({"token": token}, ensure_ascii=False).encode("utf-8")
                    try:
                        self.wfile.write(b"data: " + out + b"\n\n")
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)
                try:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except BrokenPipeError:
                    return
                self.close_connection = True
                return

            req_payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
            }
            response_data = self._call_gateway(req_payload)
            reply = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not isinstance(reply, str) or not reply.strip():
                reply = (
                    "No recibí texto del modelo en esta vuelta. "
                    "Reformulá en un paso más concreto (por ejemplo: "
                    "'buscá X en YouTube' o 'abrí Y')."
                )

            # Persist merged history server-side as fallback.
            merged = []
            if isinstance(history, list):
                for item in history[-80:]:
                    if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
                        merged.append({"role": item["role"], "content": item["content"]})
            merged.append({"role": "user", "content": message})
            merged.append({"role": "assistant", "content": reply})
            _save_history(session_id, merged)

            self._json(200, {"reply": reply, "raw": response_data})
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            self._json(e.code, {"error": f"Gateway HTTP {e.code}", "detail": detail})
        except URLError as e:
            self._json(502, {"error": "Cannot reach OpenClaw gateway", "detail": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--gateway-port", type=int, default=18789)
    args = parser.parse_args()

    token = load_gateway_token()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.gateway_token = token
    httpd.gateway_port = args.gateway_port
    print(f"Direct chat ready: http://{args.host}:{args.port}")
    print(f"Target gateway: http://127.0.0.1:{args.gateway_port}/v1/chat/completions")
    httpd.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
