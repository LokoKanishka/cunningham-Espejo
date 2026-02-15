from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote_plus

from .util import normalize_text, parse_json_object


# Web automation runner (Node + Playwright)
SCRIPTS_ROOT = Path(__file__).resolve().parents[1]  # .../scripts
WEB_ASK_SCRIPT_PATH = SCRIPTS_ROOT / "web_ask_playwright.js"
WEB_ASK_BOOTSTRAP_PATH = SCRIPTS_ROOT / "web_ask_bootstrap.sh"

WEB_ASK_LOG_PATH = Path.home() / ".openclaw" / "logs" / "web_ask.log"
WEB_ASK_LOCK_PATH = Path.home() / ".openclaw" / "web_ask_shadow" / ".web_ask.lock"
WEB_ASK_THREAD_DIR = Path.home() / ".openclaw" / "web_ask_shadow" / "threads"

PROFILE_CONFIG_PATH = Path.home() / ".openclaw" / "direct_chat_browser_profiles.json"

DEFAULT_BROWSER_PROFILE_CONFIG = {
    "_default": {"browser": "chrome", "profile": "diego"},
    "chatgpt": {"browser": "chrome", "profile": "diego"},
    "gemini": {"browser": "chrome", "profile": "diego"},
    "youtube": {"browser": "chrome", "profile": "diego"},
}

SITE_ALIASES = {
    "chatgpt": "https://chatgpt.com/",
    "gemini": "https://gemini.google.com/app",
}

SITE_SEARCH_TEMPLATES = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "wikipedia": "https://es.wikipedia.org/w/index.php?search={q}",
}


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


def _resolve_chrome_profile_directory(profile_hint: str) -> str:
    hint = profile_hint.strip()
    if not hint:
        return hint

    chrome_root = Path.home() / ".config" / "google-chrome"
    local_state = chrome_root / "Local State"
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        info = data.get("profile", {}).get("info_cache", {})
        if isinstance(info, dict):
            hint_norm = hint.lower().strip()
            for key, value in info.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                name = str(value.get("name", "")).lower().strip()
                if name == hint_norm:
                    return key
    except Exception:
        pass

    if (chrome_root / hint).is_dir():
        return hint

    return hint


def _resolve_site_browser_config(site_key: str) -> tuple[str, str]:
    cfg = _load_browser_profile_config()
    site_cfg = cfg.get(site_key, {})
    if not site_cfg:
        site_cfg = cfg.get("_default", {})

    browser = str(site_cfg.get("browser", "")).lower().strip() or "chrome"
    profile = _resolve_chrome_profile_directory(str(site_cfg.get("profile", "")).strip() or "Default")
    return browser, profile


def _list_known_chrome_profiles() -> list[str]:
    out = []
    local_state = Path.home() / ".config" / "google-chrome" / "Local State"
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        info = data.get("profile", {}).get("info_cache", {})
        if isinstance(info, dict):
            for key in info.keys():
                if isinstance(key, str) and key not in out:
                    out.append(key)
    except Exception:
        pass
    if "Default" not in out:
        out.append("Default")
    return out


def _prepare_shadow_chrome_user_data(profile_dir: str) -> tuple[str, str | None]:
    src_root = Path.home() / ".config" / "google-chrome"
    src_profile = src_root / profile_dir
    if not src_root.exists() or not src_profile.exists():
        return str(src_root), "source_profile_missing"

    dst_root = Path.home() / ".openclaw" / "web_ask_shadow" / "google-chrome"
    dst_profile = dst_root / profile_dir
    dst_root.mkdir(parents=True, exist_ok=True)
    dst_profile.parent.mkdir(parents=True, exist_ok=True)

    # If the user bootstrapped a login in the shadow profile, don't overwrite it.
    # Otherwise `rsync --delete` would wipe the logged-in cookies and force login_required.
    if (dst_profile / ".web_ask_bootstrap_keep").exists():
        return str(dst_root), "shadow_kept_bootstrap_marker"

    local_state_src = src_root / "Local State"
    local_state_dst = dst_root / "Local State"
    try:
        if local_state_src.exists():
            shutil.copy2(local_state_src, local_state_dst)
    except Exception:
        pass

    rsync = shutil.which("rsync")
    if rsync:
        cmd = [
            rsync,
            "-a",
            "--exclude=Cache/",
            "--exclude=Code Cache/",
            "--exclude=GPUCache/",
            "--exclude=GrShaderCache/",
            "--exclude=ShaderCache/",
            "--exclude=Service Worker/CacheStorage/",
            "--exclude=Crashpad/",
            "--exclude=BrowserMetrics/",
            "--exclude=Session Storage/",
            "--exclude=Sessions/",
            f"{src_profile}/",
            f"{dst_profile}/",
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return str(dst_root), None
        except Exception:
            pass

    try:
        # Keep existing dst_profile if present (no deletion). This avoids
        # wiping a user-authenticated shadow profile and reduces flakiness.
        if not dst_profile.exists():
            shutil.copytree(src_profile, dst_profile)
        return str(dst_root), None
    except Exception as e:
        return str(src_root), f"shadow_copy_failed:{e}"


def _log_web_ask(event: dict) -> None:
    try:
        WEB_ASK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False)
        with WEB_ASK_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        return


def extract_web_ask_request(message: str) -> tuple[str, str, str | None, str | None] | None:
    msg = (message or "").strip()
    dialog_patterns = [
        r"(?:dialoga|dialogá|dialogue|dialogar)\s+(?:con\s+)?(chatgpt|chat gpt|gemini)\s*[:,-]?\s*(.+)$",
    ]
    for pattern in dialog_patterns:
        m = re.search(pattern, msg, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        provider = m.group(1).strip().lower()
        prompt = m.group(2).strip().strip("\"'").strip()
        if not prompt:
            continue
        site_key = "chatgpt" if "chat" in provider else "gemini"
        followup = "En base a tu respuesta anterior, resumila en 1 frase y listá 3 conceptos clave."
        followup2 = "Ahora: proponé 2 preguntas de seguimiento y respondelas en forma breve (2-4 líneas cada una)."
        return site_key, prompt, followup, followup2

    patterns = [
        r"(?:preguntale|preguntále|preguntale|pregunta|consultale|consúltale|consulta|decile|decirle)\s+(?:a\s+)?(chatgpt|chat gpt|gemini)\s*[:,-]?\s*(.+)$",
        r"^(chatgpt|chat gpt|gemini)\s*[:,-]\s*(.+)$",
    ]
    for pattern in patterns:
        m = re.search(pattern, msg, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        provider = m.group(1).strip().lower()
        prompt = m.group(2).strip().strip("\"'").strip()
        if not prompt:
            continue
        site_key = "chatgpt" if "chat" in provider else "gemini"
        return site_key, prompt, None, None
    return None


def bootstrap_login(site_key: str) -> tuple[bool, str]:
    browser, profile_dir = _resolve_site_browser_config(site_key)
    if browser != "chrome":
        return False, f"profile_not_chrome browser={browser}"
    if not WEB_ASK_BOOTSTRAP_PATH.exists():
        return False, f"missing_bootstrap_script {WEB_ASK_BOOTSTRAP_PATH}"
    try:
        subprocess.Popen(
            [str(WEB_ASK_BOOTSTRAP_PATH), site_key, profile_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, f"opened shadow login window for {site_key} profile={profile_dir}"
    except Exception as e:
        return False, str(e)


def run_web_ask(
    site_key: str, prompt: str, timeout_ms: int = 60000, followup: str | None = None, followup2: str | None = None
) -> dict:
    started = time.time()
    browser, profile = _resolve_site_browser_config(site_key)
    if browser != "chrome":
        return {
            "ok": False,
            "status": "unsupported_browser",
            "text": "",
            "evidence": f"browser={browser}",
            "timings": {"start": started, "end": time.time(), "duration": 0.0},
        }

    node = shutil.which("node")
    if not node:
        return {
            "ok": False,
            "status": "missing_runtime",
            "text": "",
            "evidence": "node_not_found",
            "timings": {"start": started, "end": time.time(), "duration": 0.0},
        }
    if not WEB_ASK_SCRIPT_PATH.exists():
        return {
            "ok": False,
            "status": "missing_script",
            "text": "",
            "evidence": str(WEB_ASK_SCRIPT_PATH),
            "timings": {"start": started, "end": time.time(), "duration": 0.0},
        }

    try_all = str(os.environ.get("WEB_ASK_TRY_ALL_PROFILES", "")).strip().lower() in ("1", "true", "yes")
    fallback_profiles = [profile]
    if try_all:
        for p in _list_known_chrome_profiles():
            if p not in fallback_profiles:
                fallback_profiles.append(p)

    WEB_ASK_THREAD_DIR.mkdir(parents=True, exist_ok=True)
    thread_file = WEB_ASK_THREAD_DIR / f"{site_key}_thread.txt"

    last_payload = {
        "ok": False,
        "status": "runner_error",
        "text": "",
        "evidence": "no_attempt",
        "timings": {"start": started, "end": time.time(), "duration": 0.0},
    }

    for idx, profile_candidate in enumerate(fallback_profiles):
        shadow_user_data_dir, shadow_warn = _prepare_shadow_chrome_user_data(profile_candidate)
        cmd = [
            node,
            str(WEB_ASK_SCRIPT_PATH),
            "--site",
            site_key,
            "--prompt",
            prompt,
            "--profile-dir",
            profile_candidate,
            "--user-data-dir",
            shadow_user_data_dir,
            "--timeout-ms",
            str(timeout_ms),
            "--headless",
            "false",
            "--thread-file",
            str(thread_file),
        ]
        if followup:
            cmd.extend(["--followup", followup])
        if followup2:
            cmd.extend(["--followup2", followup2])

        WEB_ASK_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with WEB_ASK_LOCK_PATH.open("w", encoding="utf-8") as lockf:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=max(20, int(timeout_ms / 1000) + 20),
                )
        except subprocess.TimeoutExpired:
            last_payload = {
                "ok": False,
                "status": "timeout",
                "text": "",
                "evidence": "playwright_runner_timeout",
                "timings": {"start": started, "end": time.time(), "duration": round(time.time() - started, 3)},
            }
            continue
        except Exception as e:
            last_payload = {
                "ok": False,
                "status": "runner_error",
                "text": "",
                "evidence": str(e),
                "timings": {"start": started, "end": time.time(), "duration": round(time.time() - started, 3)},
            }
            continue

        payload = parse_json_object(proc.stdout) or {}
        if not payload:
            payload = {
                "ok": False,
                "status": "invalid_output",
                "text": "",
                "evidence": (proc.stderr or proc.stdout or "").strip()[:800],
                "timings": {"start": started, "end": time.time(), "duration": round(time.time() - started, 3)},
            }

        if "timings" not in payload or not isinstance(payload.get("timings"), dict):
            payload["timings"] = {"start": started, "end": time.time(), "duration": round(time.time() - started, 3)}

        payload["ok"] = bool(payload.get("ok", False))
        payload["status"] = str(payload.get("status", "error"))
        payload["text"] = str(payload.get("text", ""))
        payload["evidence"] = str(payload.get("evidence", ""))
        payload["runner_code"] = proc.returncode
        payload["profile_used"] = profile_candidate
        payload["attempt"] = idx + 1
        if shadow_warn:
            payload["shadow_warn"] = shadow_warn

        _log_web_ask(
            {
                "ts": time.time(),
                "site": site_key,
                "status": payload["status"],
                "ok": payload["ok"],
                "runner_code": proc.returncode,
                "prompt": prompt[:220],
                "duration": payload.get("timings", {}).get("duration", None),
                "evidence": payload.get("evidence", ""),
                "shadow_user_data_dir": shadow_user_data_dir,
                "shadow_warn": shadow_warn,
                "profile_used": profile_candidate,
                "attempt": idx + 1,
            }
        )

        last_payload = payload
        if payload.get("ok"):
            return payload
        if payload.get("status") not in ("login_required", "profile_locked"):
            return payload

    return last_payload


def format_web_ask_reply(site_key: str, prompt: str, result: dict) -> str:
    provider = "ChatGPT" if site_key == "chatgpt" else "Gemini"
    status = str(result.get("status", "error"))
    duration = result.get("timings", {}).get("duration", "?")
    if result.get("ok"):
        text = str(result.get("text", "")).strip() or "(respuesta vacía)"
        if len(text) > 6000:
            text = text[:6000] + "\n\n[...respuesta truncada por longitud...]"
        profile_used = str(result.get("profile_used", "")).strip()
        profile_note = f" perfil={profile_used}" if profile_used else ""
        turns = result.get("turns")
        if isinstance(turns, list) and turns:
            out_lines = []
            for idx, t in enumerate(turns[:4], 1):
                if not isinstance(t, dict):
                    continue
                p = str(t.get("prompt", "")).strip()
                tx = str(t.get("text", "")).strip()
                if p:
                    out_lines.append(f"Turno {idx} (yo): {p}")
                if tx:
                    out_lines.append(f"Turno {idx} ({provider}): {tx}")
                out_lines.append("")
            body = "\n".join(out_lines).strip()
            if len(body) > 6500:
                body = body[:6500] + "\n\n[...truncado...]"
            return f"{body}\n\nEstado: ok ({duration}s){profile_note}."
        return f"{provider} respondió:\n{text}\n\nEstado: ok ({duration}s){profile_note}."

    help_map = {
        "login_required": f"No pude completar en {provider}: la sesión requiere login manual en ese sitio.",
        "captcha_required": f"No pude completar en {provider}: apareció captcha/validación humana.",
        "selector_changed": f"No pude completar en {provider}: cambió la UI y no encontré input/respuesta.",
        "timeout": f"No pude completar en {provider}: timeout esperando respuesta.",
        "profile_locked": f"No pude completar en {provider}: el perfil de Chrome está bloqueado por otra instancia.",
        "launch_failed": f"No pude iniciar automatización de {provider}.",
        "unsupported_browser": f"No pude completar en {provider}: el perfil configurado no usa Chrome.",
        "missing_runtime": "No pude ejecutar automatización: falta runtime local de Node.js.",
        "missing_script": "No pude ejecutar automatización: falta script local web_ask_playwright.js.",
        "invalid_output": f"No pude completar en {provider}: salida inválida del runner.",
        "blocked": f"No pude completar en {provider}: el sitio bloqueó o devolvió estado no esperado.",
        "runner_error": f"No pude completar en {provider}: error interno del runner local.",
    }
    detail = str(result.get("evidence", "")).strip()
    base = help_map.get(status, f"No pude completar en {provider}: estado '{status}'.")
    if detail:
        base += f"\nDetalle: {detail[:400]}"
    return base + f"\nPrompt intentado: \"{prompt[:220]}\""


def build_site_search_url(site_key: str, query: str) -> str | None:
    template = SITE_SEARCH_TEMPLATES.get(site_key)
    if not template:
        return None
    return template.format(q=quote_plus(query))
