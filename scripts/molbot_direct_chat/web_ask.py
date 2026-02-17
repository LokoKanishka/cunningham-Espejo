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
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .util import normalize_text, parse_json_object


# Web automation runner (Node + Playwright)
SCRIPTS_ROOT = Path(__file__).resolve().parents[1]  # .../scripts
WEB_ASK_SCRIPT_PATH = SCRIPTS_ROOT / "web_ask_playwright.js"
WEB_ASK_BOOTSTRAP_PATH = SCRIPTS_ROOT / "web_ask_bootstrap.sh"

WEB_ASK_LOG_PATH = Path.home() / ".openclaw" / "logs" / "web_ask.log"
WEB_ASK_LOCK_PATH = Path.home() / ".openclaw" / "web_ask_shadow" / ".web_ask.lock"
WEB_ASK_THREAD_DIR = Path.home() / ".openclaw" / "web_ask_shadow" / "threads"
GEMINI_API_USAGE_PATH = Path.home() / ".openclaw" / "logs" / "gemini_api_usage.json"
GEMINI_API_USAGE_LOCK_PATH = Path.home() / ".openclaw" / "logs" / ".gemini_api_usage.lock"

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


def _env_flag(name: str, default: str = "0") -> bool:
    raw = str(os.environ.get(name, default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _gemini_api_enabled() -> bool:
    return _env_flag("GEMINI_API_ENABLED", "1")


def _gemini_api_key() -> str:
    return str(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def _gemini_api_models() -> list[str]:
    raw = str(
        os.environ.get(
            "GEMINI_API_MODELS",
            "gemini-2.5-flash,gemini-2.0-flash,gemini-1.5-flash",
        )
    ).strip()
    models: list[str] = []
    for part in raw.split(","):
        model = part.strip()
        if model and model not in models:
            models.append(model)
    if not models:
        models = ["gemini-2.0-flash"]
    return models


def _gemini_api_allow_paid() -> bool:
    return _env_flag("GEMINI_API_ALLOW_PAID", "0")


def _gemini_api_free_allowlist() -> list[str]:
    raw = str(
        os.environ.get(
            "GEMINI_API_FREE_MODELS",
            "gemini-2.5-flash,gemini-2.0-flash,gemini-1.5-flash",
        )
    ).strip()
    out: list[str] = []
    for part in raw.split(","):
        m = part.strip()
        if m and m not in out:
            out.append(m)
    if not out:
        out = ["gemini-2.0-flash"]
    return out


def _gemini_api_daily_limit() -> int:
    raw = str(os.environ.get("GEMINI_API_DAILY_LIMIT", "200")).strip()
    try:
        n = int(raw)
    except Exception:
        n = 200
    return max(1, n)


def _gemini_api_prompt_char_limit() -> int:
    raw = str(os.environ.get("GEMINI_API_PROMPT_CHAR_LIMIT", "2500")).strip()
    try:
        n = int(raw)
    except Exception:
        n = 2500
    return max(128, n)


def _gemini_api_models_safe() -> list[str]:
    models = _gemini_api_models()
    if _gemini_api_allow_paid():
        return models
    free_allowed = set(_gemini_api_free_allowlist())
    return [m for m in models if m in free_allowed]


def _gemini_api_usage_reserve(units: int = 1) -> tuple[bool, int, int]:
    limit = _gemini_api_daily_limit()
    today = time.strftime("%Y-%m-%d", time.localtime())
    used = 0
    try:
        GEMINI_API_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        GEMINI_API_USAGE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with GEMINI_API_USAGE_LOCK_PATH.open("a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            data = {}
            if GEMINI_API_USAGE_PATH.exists():
                try:
                    data = json.loads(GEMINI_API_USAGE_PATH.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            date = str(data.get("date", ""))
            used = int(data.get("used", 0) or 0)
            if date != today:
                used = 0
            if used + units > limit:
                return False, used, limit
            used += units
            payload = {"date": today, "used": used, "limit": limit, "updated_ts": time.time()}
            GEMINI_API_USAGE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return True, used, limit
    except Exception:
        # Fail closed: if usage persistence fails, don't risk unbounded calls.
        return False, used, limit


def _gemini_api_extract_text(payload: dict) -> str:
    try:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            return ""
        out_parts: list[str] = []
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            content = cand.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                txt = str(part.get("text", "")).strip()
                if txt:
                    out_parts.append(txt)
            if out_parts:
                break
        return "\n".join(out_parts).strip()
    except Exception:
        return ""


def _gemini_api_status_from_error(code: int, detail: str) -> str:
    d = (detail or "").lower()
    if code == 401:
        return "api_auth_error"
    if code == 403:
        return "api_auth_error"
    if code == 404:
        return "model_not_found"
    if code == 429:
        return "quota_exceeded"
    if code >= 500:
        return "upstream_error"
    if "quota" in d or "rate" in d:
        return "quota_exceeded"
    if "api key" in d or "permission" in d or "unauthorized" in d:
        return "api_auth_error"
    return "runner_error"


def _gemini_api_generate_once(
    model: str,
    api_key: str,
    contents: list[dict],
    timeout_ms: int,
) -> tuple[bool, str, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {"contents": contents}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    timeout_s = max(8.0, float(timeout_ms) / 1000.0)
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        status = _gemini_api_status_from_error(int(getattr(e, "code", 0) or 0), detail)
        return False, status, detail[:800]
    except URLError as e:
        return False, "upstream_error", str(e)[:800]
    except Exception as e:
        return False, "runner_error", str(e)[:800]

    try:
        payload = json.loads(raw)
    except Exception:
        return False, "invalid_output", raw[:800]

    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        err = payload.get("error", {})
        code = int(err.get("code", 0) or 0)
        detail = str(err.get("message", "") or json.dumps(err, ensure_ascii=False))
        status = _gemini_api_status_from_error(code, detail)
        return False, status, detail[:800]

    text = _gemini_api_extract_text(payload)
    if text:
        return True, "ok", text

    prompt_feedback = str(payload.get("promptFeedback", "")).lower()
    if "block" in prompt_feedback or "safety" in prompt_feedback:
        return False, "blocked", json.dumps(payload, ensure_ascii=False)[:800]
    return False, "invalid_output", json.dumps(payload, ensure_ascii=False)[:800]


def _run_gemini_api(prompt: str, timeout_ms: int = 60000, followups: list[str] | None = None) -> dict:
    started = time.time()
    if not _gemini_api_enabled():
        return {
            "ok": False,
            "status": "api_disabled",
            "text": "",
            "evidence": "GEMINI_API_ENABLED=0",
            "timings": {"start": started, "end": time.time(), "duration": 0.0},
        }

    api_key = _gemini_api_key()
    if not api_key:
        return {
            "ok": False,
            "status": "missing_api_key",
            "text": "",
            "evidence": "set GEMINI_API_KEY (or GOOGLE_API_KEY)",
            "timings": {"start": started, "end": time.time(), "duration": 0.0},
        }

    prompt_limit = _gemini_api_prompt_char_limit()
    if len(prompt) > prompt_limit:
        return {
            "ok": False,
            "status": "prompt_too_long",
            "text": "",
            "evidence": f"prompt_len={len(prompt)} limit={prompt_limit}",
            "timings": {"start": started, "end": time.time(), "duration": 0.0},
        }

    if isinstance(followups, list):
        for fup in followups:
            if len(str(fup)) > prompt_limit:
                return {
                    "ok": False,
                    "status": "prompt_too_long",
                    "text": "",
                    "evidence": f"followup_len={len(str(fup))} limit={prompt_limit}",
                    "timings": {"start": started, "end": time.time(), "duration": 0.0},
                }

    models = _gemini_api_models_safe()
    if not models:
        return {
            "ok": False,
            "status": "model_not_allowed",
            "text": "",
            "evidence": "no_safe_model_in_GEMINI_API_MODELS",
            "timings": {"start": started, "end": time.time(), "duration": 0.0},
        }

    reserved, used, max_daily = _gemini_api_usage_reserve(units=1)
    if not reserved:
        return {
            "ok": False,
            "status": "daily_limit_reached",
            "text": "",
            "evidence": f"used={used} limit={max_daily}",
            "timings": {"start": started, "end": time.time(), "duration": 0.0},
        }

    prompts = [prompt]
    if isinstance(followups, list):
        prompts.extend([str(x).strip() for x in followups if str(x).strip()])

    last_error = {
        "ok": False,
        "status": "runner_error",
        "text": "",
        "evidence": "no_model_attempted",
        "timings": {"start": started, "end": time.time(), "duration": 0.0},
    }

    for model in models:
        contents: list[dict] = []
        turns: list[dict] = []
        failed = False
        fail_status = ""
        fail_evidence = ""

        for p in prompts:
            contents.append({"role": "user", "parts": [{"text": p}]})
            ok, status, out = _gemini_api_generate_once(model=model, api_key=api_key, contents=contents, timeout_ms=timeout_ms)
            if not ok:
                failed = True
                fail_status = status
                fail_evidence = out
                break
            answer = str(out).strip()
            turns.append({"prompt": p, "text": answer})
            contents.append({"role": "model", "parts": [{"text": answer}]})

        if not failed:
            ended = time.time()
            payload = {
                "ok": True,
                "status": "ok",
                "text": (turns[-1]["text"] if turns else ""),
                "turns": turns if len(turns) > 1 else None,
                "provider": "gemini_api",
                "model_used": model,
                "evidence": "gemini_api_generateContent",
                "timings": {"start": started, "end": ended, "duration": round(ended - started, 3)},
            }
            _log_web_ask(
                {
                    "ts": time.time(),
                    "site": "gemini",
                    "status": "ok",
                    "ok": True,
                    "runner_code": 0,
                    "prompt": prompt[:220],
                    "duration": payload["timings"]["duration"],
                    "evidence": payload["evidence"],
                    "provider": "gemini_api",
                    "model_used": model,
                }
            )
            return payload

        ended = time.time()
        last_error = {
            "ok": False,
            "status": fail_status or "runner_error",
            "text": "",
            "evidence": f"model={model} {fail_evidence}".strip()[:800],
            "provider": "gemini_api",
            "model_used": model,
            "timings": {"start": started, "end": ended, "duration": round(ended - started, 3)},
        }
        # If model doesn't exist, try next model. For other failures, stop fast.
        if fail_status != "model_not_found":
            _log_web_ask(
                {
                    "ts": time.time(),
                    "site": "gemini",
                    "status": last_error["status"],
                    "ok": False,
                    "runner_code": -1,
                    "prompt": prompt[:220],
                    "duration": last_error["timings"]["duration"],
                    "evidence": last_error["evidence"],
                    "provider": "gemini_api",
                    "model_used": model,
                }
            )
            return last_error

    _log_web_ask(
        {
            "ts": time.time(),
            "site": "gemini",
            "status": last_error["status"],
            "ok": False,
            "runner_code": -1,
            "prompt": prompt[:220],
            "duration": last_error.get("timings", {}).get("duration", None),
            "evidence": last_error.get("evidence", ""),
            "provider": "gemini_api",
            "model_used": last_error.get("model_used", ""),
        }
    )
    return last_error


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


def extract_web_ask_request(message: str) -> tuple[str, str, list[str] | None] | None:
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
        followups = [
            "En base a tu respuesta anterior, resumila en 1 frase y listá 3 conceptos clave.",
            "Ahora detectá 2 riesgos o huecos de esa respuesta y proponé cómo mitigarlos.",
            "Dame un ejemplo concreto y breve aplicado al caso.",
            "Cerrá con un mini checklist de 3 pasos accionables.",
        ]
        return site_key, prompt, followups

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
        return site_key, prompt, None
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


def run_web_ask(site_key: str, prompt: str, timeout_ms: int = 60000, followups: list[str] | None = None) -> dict:
    started = time.time()
    # Preferred stable path for Gemini: official API (free tier when available).
    if site_key == "gemini":
        api_result = _run_gemini_api(prompt=prompt, timeout_ms=timeout_ms, followups=followups)
        # Fallback to web UI automation only when API is not configured/disabled.
        if str(api_result.get("status", "")) not in ("missing_api_key", "api_disabled"):
            return api_result

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
        real_user_data_dir = str(Path.home() / ".config" / "google-chrome")
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
        if followups:
            cmd.extend(["--followups-json", json.dumps(followups, ensure_ascii=False)])

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
        # Gemini fallback: if shadow profile appears logged-out, try the real profile once.
        # This preserves shadow-by-default but helps when session state doesn't carry over.
        if site_key == "gemini" and payload.get("status") == "login_required":
            cmd_real = [
                node,
                str(WEB_ASK_SCRIPT_PATH),
                "--site",
                site_key,
                "--prompt",
                prompt,
                "--profile-dir",
                profile_candidate,
                "--user-data-dir",
                real_user_data_dir,
                "--timeout-ms",
                str(timeout_ms),
                "--headless",
                "false",
                "--thread-file",
                str(thread_file),
            ]
            if followups:
                cmd_real.extend(["--followups-json", json.dumps(followups, ensure_ascii=False)])
            try:
                with WEB_ASK_LOCK_PATH.open("w", encoding="utf-8") as lockf:
                    fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
                    proc_real = subprocess.run(
                        cmd_real,
                        capture_output=True,
                        text=True,
                        timeout=max(20, int(timeout_ms / 1000) + 20),
                    )
                payload_real = parse_json_object(proc_real.stdout) or {}
                if payload_real:
                    payload_real["ok"] = bool(payload_real.get("ok", False))
                    payload_real["status"] = str(payload_real.get("status", "error"))
                    payload_real["text"] = str(payload_real.get("text", ""))
                    payload_real["evidence"] = str(payload_real.get("evidence", ""))
                    payload_real["runner_code"] = proc_real.returncode
                    payload_real["profile_used"] = profile_candidate
                    payload_real["attempt"] = idx + 1
                    payload_real["user_data_mode"] = "real_profile_fallback"
                    _log_web_ask(
                        {
                            "ts": time.time(),
                            "site": site_key,
                            "status": payload_real["status"],
                            "ok": payload_real["ok"],
                            "runner_code": proc_real.returncode,
                            "prompt": prompt[:220],
                            "duration": payload_real.get("timings", {}).get("duration", None),
                            "evidence": payload_real.get("evidence", ""),
                            "shadow_user_data_dir": real_user_data_dir,
                            "shadow_warn": "real_profile_fallback",
                            "profile_used": profile_candidate,
                            "attempt": idx + 1,
                        }
                    )
                    if payload_real.get("ok"):
                        return payload_real
                    if payload_real.get("status") != "profile_locked":
                        return payload_real
            except Exception:
                pass
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
        model_used = str(result.get("model_used", "")).strip()
        model_note = f" modelo={model_used}" if model_used else ""
        if isinstance(turns, list) and turns:
            out_lines = []
            for idx, t in enumerate(turns[:6], 1):
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
            return f"{body}\n\nEstado: ok ({duration}s){profile_note}{model_note}. Turnos: {len(turns)}."
        return f"{provider} respondió:\n{text}\n\nEstado: ok ({duration}s){profile_note}{model_note}."

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
        "missing_api_key": f"No pude completar en {provider} por API: falta GEMINI_API_KEY.",
        "api_disabled": f"No pude completar en {provider} por API: está deshabilitada (GEMINI_API_ENABLED=0).",
        "api_auth_error": f"No pude completar en {provider} por API: API key inválida o sin permisos.",
        "quota_exceeded": f"No pude completar en {provider} por API: cuota/rate-limit excedido.",
        "model_not_found": f"No pude completar en {provider} por API: modelo no disponible.",
        "upstream_error": f"No pude completar en {provider} por API: error de red/servidor.",
        "daily_limit_reached": f"No pude completar en {provider} por API: límite diario alcanzado.",
        "model_not_allowed": f"No pude completar en {provider} por API: modelo no permitido por política anti-costo.",
        "prompt_too_long": f"No pude completar en {provider} por API: prompt demasiado largo.",
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
