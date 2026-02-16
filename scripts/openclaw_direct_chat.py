#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
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


def _wmctrl_move_to_desktop(win_id: str, desktop_idx: int) -> bool:
    if not shutil.which("wmctrl"):
        return False
    try:
        subprocess.run(
            ["wmctrl", "-i", "-r", win_id, "-t", str(desktop_idx)],
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


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


def _wmctrl_current_desktop_site_windows(site_key: str) -> list[tuple[str, str]]:
    if not shutil.which("wmctrl"):
        return []
    desk = _wmctrl_current_desktop()
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
            win_id, desktop_raw, _pid, _host, title = parts
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
            out.append((win_id, title))
    except Exception:
        return []
    return out


def _close_recent_site_window_fallback(site_key: str) -> tuple[bool, str]:
    wins = _wmctrl_current_desktop_site_windows(site_key)
    if not wins:
        return False, "no_window_found_current_workspace"
    # wmctrl ordering is stable enough for "last listed" as a practical fallback.
    win_id, title = wins[-1]
    if _wmctrl_close_window(win_id):
        return True, title
    return False, "wmctrl_close_failed"


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


def _open_url_with_site_context(url: str, site_key: str | None, session_id: str | None = None) -> str | None:
    cfg = _load_browser_profile_config()
    site_cfg = cfg.get(site_key or "", {})
    if not site_cfg:
        site_cfg = cfg.get("_default", {})
    browser = str(site_cfg.get("browser", "")).lower().strip()
    profile = _resolve_chrome_profile_directory(str(site_cfg.get("profile", "")).strip())

    if browser == "chrome" and profile:
        chrome = _chrome_command()
        if not chrome:
            return "No pude abrir Chrome: comando no encontrado en el sistema."
        chrome_user_data = str(Path.home() / ".config" / "google-chrome")
        before = _wmctrl_list()
        target_desktop = _wmctrl_current_desktop()
        try:
            subprocess.Popen(
                [
                    chrome,
                    f"--user-data-dir={chrome_user_data}",
                    f"--profile-directory={profile}",
                    "--new-window",
                    url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            new_ids: list[str] = []
            after: dict[str, str] = {}
            for _ in range(8):
                time.sleep(0.25)
                after = _wmctrl_list()
                if not after:
                    continue
                new_ids = [wid for wid in after.keys() if wid not in before]
                if new_ids:
                    break

            if new_ids and (target_desktop is not None):
                for wid in new_ids:
                    _wmctrl_move_to_desktop(wid, target_desktop)
            if session_id and new_ids:
                _record_browser_windows(
                    session_id,
                    [
                        {"win_id": wid, "title": after.get(wid, ""), "url": url, "site_key": site_key, "ts": time.time()}
                        for wid in new_ids
                    ],
                )
            return None
        except Exception as e:
            return f"No pude abrir Chrome perfil '{profile}': {e}"

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
        error = _open_url_with_site_context(url, site_key, session_id=session_id)
        if error:
            return opened, error
        opened.append(url)
    return opened, None


def _open_gemini_client_flow(session_id: str | None = None) -> tuple[list[str], str | None]:
    # Deterministic "human-like" flow requested by user:
    # 1) open Google in the Gemini-configured client/profile
    # 2) open Gemini from that same client/profile
    entries = [
        ("gemini", "https://www.google.com/"),
        ("gemini", _site_url("gemini")),
    ]
    return _open_site_urls(entries, session_id=session_id)


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


def _maybe_handle_local_action(message: str, allowed_tools: set[str], session_id: str) -> dict | None:
    text = message.lower()
    normalized = _normalize_text(message)

    # Close browser windows opened by this system (tracked by session).
    # Examples:
    # - "cerrá las ventanas web que abriste"
    # - "reset ventanas web"
    if any(k in normalized for k in ("web", "navegador", "browser")) and any(k in normalized for k in ("ventan", "windows")):
        if any(k in normalized for k in ("reset", "reinic", "olvid", "limpia")):
            _reset_recorded_browser_windows(session_id=session_id)
            return {"reply": "Listo: limpié el registro de ventanas web abiertas por el sistema para esta sesión."}
        if any(k in normalized for k in ("cerr", "close", "cierra")):
            closed, errors = _close_recorded_browser_windows(session_id=session_id)
            if errors:
                return {"reply": f"Cerré {closed} ventana(s) web que abrí. Errores: {', '.join(errors)[:260]}"}
            return {"reply": f"Cerré {closed} ventana(s) web que abrí (solo las registradas por el sistema)."}

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

        # If no tracked windows, allow a safe fallback only for explicit Gemini mentions.
        if any(t in normalized for t in SITE_CANONICAL_TOKENS.get("gemini", [])):
            ok, detail = _close_recent_site_window_fallback("gemini")
            if ok:
                return {"reply": f"Cerré la ventana de Gemini más reciente en este workspace: {detail[:120]}"}
            return {"reply": "No veo ninguna ventana de Gemini abierta en este workspace."}

    # Safe local opens/closes for Desktop items (no deletion).
    # Examples:
    # - "abrí carpeta Lucy del escritorio"
    # - "abrí Moscu del escritorio"
    # - "cerrá las ventanas que abriste del escritorio"
    if any(k in normalized for k in ("escritorio", "desktop")):
        if any(k in normalized for k in ("reset", "reinic", "olvid", "limpia")) and any(k in normalized for k in ("ventan", "registro", "track")):
            if "desktop" not in allowed_tools:
                return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
            desktop_ops.reset_recorded_windows(session_id=session_id)
            return {"reply": "Listo: limpié el registro de ventanas abiertas por el sistema para esta sesión."}

        if any(k in normalized for k in ("cerr", "close", "cierra")):
            if "desktop" not in allowed_tools:
                return {"reply": "La herramienta local 'desktop' está deshabilitada en esta sesión."}
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
        provider = m_login.group(1).strip().lower()
        site_key = "chatgpt" if "chat" in provider else "gemini"
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

    web_req = web_ask.extract_web_ask_request(message)
    if web_req is not None:
        # web_ask is separate from opening URLs via firefox. Keep backward-compat:
        # if someone only enabled firefox (old UI), still allow web_ask.
        if ("web_ask" not in allowed_tools) and ("firefox" not in allowed_tools):
            return {"reply": "La herramienta local 'web_ask' está deshabilitada en esta sesión."}
        site_key, prompt, followups = web_req
        result = web_ask.run_web_ask(site_key, prompt, timeout_ms=60000, followups=followups)
        reply = web_ask.format_web_ask_reply(site_key, prompt, result)
        if str(result.get("status", "")).strip() in ("login_required", "captcha_required"):
            ok, info = web_ask.bootstrap_login(site_key)
            if ok:
                reply += (
                    "\n\nAcción automática: abrí una ventana de Chrome (shadow profile) para que inicies sesión. "
                    "Si aparece verificación humana/captcha, resolvela ahí. Luego cerrá esa ventana y repetí tu pedido."
                )
            else:
                reply += f"\n\nNo pude abrir ventana de login automáticamente: {info}"
        return {"reply": reply}

    if "firefox" in text and any(k in normalized for k in ("abr", "open", "lanz", "inici")):
        if "firefox" not in allowed_tools:
            return {"reply": "La herramienta local 'firefox' está deshabilitada en esta sesión."}
        url = _extract_url(message) or "about:blank"
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
        opened, error = _open_gemini_client_flow(session_id=session_id)
        if error:
            return {"reply": error}
        return {"reply": f"Abrí Gemini en el cliente configurado con flujo fijo: {' | '.join(opened)}"}

    m_site_search = re.search(r"(?:busca|buscar|search)\s+(.+?)\s+en\s+(youtube|wikipedia)", normalized, flags=re.IGNORECASE)
    if "firefox" in allowed_tools and m_site_search:
        query = m_site_search.group(1).strip()
        site = m_site_search.group(2).strip()
        url = _build_site_search_url(site, query)
        if url:
            opened, error = _open_site_urls([(site, url)], session_id=session_id)
            if error:
                return {"reply": error}
            return {"reply": f"Listo, busqué '{query}' en {site} y abrí: {opened[0]}"}

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
        opened, error = _open_site_urls([("youtube", url)], session_id=session_id) if url else ([], "No pude construir la búsqueda en YouTube.")
        if error:
            return {"reply": error}
        return {"reply": f"Abrí videos de YouTube sobre '{query}': {opened[0]}"}

    if "firefox" in allowed_tools and site_keys and wants_open and not wants_search and not wants_new_chat:
        entries = [(site_key, _site_url(site_key)) for site_key in site_keys]
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
            allowed_tools = set(payload.get("allowed_tools", []))
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
