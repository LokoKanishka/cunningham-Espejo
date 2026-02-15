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
import unicodedata
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


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
    "chatgpt": ["chatgpt", "chat gpt"],
    "gemini": ["gemini"],
    "youtube": ["youtube", "you tube"],
    "wikipedia": ["wikipedia", "wiki"],
    "gmail": ["gmail", "mail"],
}

# Defaults can be overridden in ~/.openclaw/direct_chat_browser_profiles.json
DEFAULT_BROWSER_PROFILE_CONFIG = {
    "_default": {"browser": "chrome", "profile": "diego"},
    "chatgpt": {"browser": "chrome", "profile": "Chat"},
    "youtube": {"browser": "chrome", "profile": "diego"},
}
WEB_ASK_SCRIPT_PATH = Path(__file__).with_name("web_ask_playwright.js")
WEB_ASK_LOG_PATH = Path.home() / ".openclaw" / "logs" / "web_ask.log"
WEB_ASK_LOCK_PATH = Path.home() / ".openclaw" / "web_ask_shadow" / ".web_ask.lock"


HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Molbot Direct Chat</title>
  <style>
    :root {
      --bg: #0f1222;
      --panel: #181d33;
      --muted: #8f9ab8;
      --text: #eef2ff;
      --user: #21305f;
      --assistant: #212842;
      --accent: #4dd4ac;
      --border: #2b3359;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      color: var(--text);
      background: radial-gradient(1200px 700px at 20% -10%, #22306a 0%, transparent 55%), var(--bg);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .app {
      width: min(1100px, 100%);
      border: 1px solid var(--border);
      border-radius: 14px;
      background: var(--panel);
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      height: min(92vh, 940px);
      overflow: hidden;
    }
    .top {
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
    }
    .title { font-weight: 700; }
    .meta { color: var(--muted); font-size: 13px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .tools {
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
    }
    .tools label { display: inline-flex; gap: 6px; align-items: center; }
    .chat {
      padding: 14px;
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .msg {
      padding: 10px 12px;
      border-radius: 10px;
      max-width: 90%;
      white-space: pre-wrap;
      line-height: 1.4;
      border: 1px solid var(--border);
    }
    .user { background: var(--user); align-self: flex-end; }
    .assistant { background: var(--assistant); align-self: flex-start; }
    .composer {
      border-top: 1px solid var(--border);
      padding: 10px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
    }
    textarea, input, select {
      color: var(--text);
      background: #121831;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px 10px;
    }
    textarea { min-height: 74px; resize: vertical; width: 100%; }
    button {
      color: #06291f;
      background: var(--accent);
      border: 0;
      border-radius: 10px;
      padding: 8px 12px;
      font-weight: 700;
      cursor: pointer;
    }
    button.alt {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
      font-weight: 600;
    }
    .small { font-size: 12px; color: var(--muted); }
  </style>
</head>
<body>
  <div class="app">
    <div class="top">
      <div>
        <div class="title">Molbot Direct Chat</div>
        <div class="meta">Sin doble capa. OpenClaw directo.</div>
      </div>
      <div class="row">
        <input id="model" value="openai-codex/gpt-5.1-codex-mini" style="min-width:260px" />
        <select id="mode">
          <option value="conciso">conciso</option>
          <option value="operativo" selected>operativo</option>
          <option value="investigacion">investigacion</option>
        </select>
        <button class="alt" id="newSession">Nueva sesion</button>
        <button class="alt" id="exportMd">Export MD</button>
        <button class="alt" id="exportTxt">Export TXT</button>
      </div>
    </div>

    <div class="tools">
      <span>Herramientas locales:</span>
      <label><input type="checkbox" id="toolFirefox" checked /> firefox</label>
      <label><input type="checkbox" id="toolDesktop" checked /> escritorio</label>
      <label><input type="checkbox" id="toolModel" checked /> modelo</label>
      <label><input type="checkbox" id="useStream" checked /> streaming</label>
      <button class="alt" id="btnFirefox">Abrir Firefox</button>
      <button class="alt" id="btnDesktop">Listar Escritorio</button>
      <span class="small">Slash: /new /firefox [url] /escritorio /modo [conciso|operativo|investigacion]</span>
    </div>

    <div id="chat" class="chat"></div>

    <div class="composer">
      <div>
        <textarea id="input" placeholder="Escribi en lenguaje natural..."></textarea>
        <div class="row" style="margin-top:6px;">
          <input id="attach" type="file" multiple />
          <span class="small" id="attachInfo"></span>
        </div>
      </div>
      <button id="send">Enviar</button>
    </div>
  </div>

  <script>
    const chatEl = document.getElementById("chat");
    const inputEl = document.getElementById("input");
    const modelEl = document.getElementById("model");
    const modeEl = document.getElementById("mode");
    const sendEl = document.getElementById("send");
    const newSessionEl = document.getElementById("newSession");
    const exportMdEl = document.getElementById("exportMd");
    const exportTxtEl = document.getElementById("exportTxt");
    const toolFirefoxEl = document.getElementById("toolFirefox");
    const toolDesktopEl = document.getElementById("toolDesktop");
    const toolModelEl = document.getElementById("toolModel");
    const useStreamEl = document.getElementById("useStream");
    const btnFirefoxEl = document.getElementById("btnFirefox");
    const btnDesktopEl = document.getElementById("btnDesktop");
    const attachEl = document.getElementById("attach");
    const attachInfoEl = document.getElementById("attachInfo");

    const SESSION_KEY = "molbot_direct_chat_session_id";
    let sessionId = localStorage.getItem(SESSION_KEY) || crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sessionId);

    let history = [];
    let pendingAttachments = [];

    function allowedTools() {
      const out = [];
      if (toolFirefoxEl.checked) out.push("firefox");
      if (toolDesktopEl.checked) out.push("desktop");
      if (toolModelEl.checked) out.push("model");
      return out;
    }

    async function loadServerHistory() {
      try {
        const r = await fetch(`/api/history?session=${encodeURIComponent(sessionId)}`);
        const j = await r.json();
        history = Array.isArray(j.history) ? j.history : [];
      } catch {
        history = [];
      }
      draw();
    }

    async function saveServerHistory() {
      await fetch("/api/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, history })
      }).catch(() => {});
    }

    function draw() {
      chatEl.innerHTML = "";
      for (const m of history) {
        const div = document.createElement("div");
        div.className = "msg " + (m.role === "user" ? "user" : "assistant");
        div.textContent = m.content;
        chatEl.appendChild(div);
      }
      chatEl.scrollTop = chatEl.scrollHeight;
    }

    async function push(role, content) {
      history.push({ role, content });
      if (history.length > 80) history = history.slice(-80);
      draw();
      await saveServerHistory();
    }

    function download(name, content) {
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    }

    function exportTxt() {
      const body = history.map(m => `[${m.role}] ${m.content}`).join("\n\n");
      download(`molbot_chat_${sessionId}.txt`, body);
    }

    function exportMd() {
      const body = history.map(m => `${m.role === "user" ? "## Usuario" : "## Asistente"}\n\n${m.content}`).join("\n\n");
      download(`molbot_chat_${sessionId}.md`, body);
    }

    function startAssistantMessage() {
      history.push({ role: "assistant", content: "" });
      draw();
    }

    function appendAssistantChunk(chunk) {
      if (!history.length || history[history.length - 1].role !== "assistant") {
        startAssistantMessage();
      }
      history[history.length - 1].content += chunk;
      draw();
    }

    async function readAttachments(files) {
      const out = [];
      for (const f of files) {
        const type = (f.type || "").toLowerCase();
        if (type.startsWith("text/") || /\.(md|txt|json|csv|log|py|js|ts|html|css|sh)$/i.test(f.name)) {
          const text = await f.text();
          out.push({ name: f.name, type: "text", content: text.slice(0, 12000) });
        } else if (type.startsWith("image/")) {
          out.push({ name: f.name, type: "image", content: `[imagen adjunta: ${f.name}]` });
        } else {
          out.push({ name: f.name, type: "file", content: `[archivo adjunto: ${f.name}]` });
        }
      }
      return out;
    }

    function parseSlash(text) {
      const t = text.trim();
      if (!t.startsWith("/")) return null;
      if (t === "/new") return { kind: "new" };
      if (t.startsWith("/firefox")) {
        const url = t.replace(/^\/firefox\s*/i, "").trim();
        return { kind: "message", text: `abrí firefox ${url}`.trim() };
      }
      if (t === "/escritorio") return { kind: "message", text: "decime que carpetas y archivos hay en mi escritorio" };
      if (t.startsWith("/modo")) {
        const mode = t.replace(/^\/modo\s*/i, "").trim();
        if (["conciso", "operativo", "investigacion"].includes(mode)) return { kind: "mode", mode };
      }
      return { kind: "unknown" };
    }

    async function sendMessage(rawText) {
      let text = (rawText ?? inputEl.value).trim();
      if (!text && pendingAttachments.length === 0) return;

      const slash = parseSlash(text);
      if (slash?.kind === "new") {
        sessionId = crypto.randomUUID();
        localStorage.setItem(SESSION_KEY, sessionId);
        history = [];
        draw();
        await saveServerHistory();
        inputEl.value = "";
        return;
      }
      if (slash?.kind === "mode") {
        modeEl.value = slash.mode;
        inputEl.value = "";
        return;
      }
      if (slash?.kind === "message") text = slash.text;
      if (slash?.kind === "unknown") {
        await push("assistant", "Comando desconocido. Usá /new /firefox [url] /escritorio /modo [conciso|operativo|investigacion]");
        inputEl.value = "";
        return;
      }

      if (pendingAttachments.length) {
        text += "\n\nAdjuntos:\n" + pendingAttachments.map(a => `- ${a.name} (${a.type})`).join("\n");
      }

      inputEl.value = "";
      await push("user", text);
      sendEl.disabled = true;

      const payload = {
        message: text,
        model: modelEl.value.trim() || "openai-codex/gpt-5.1-codex-mini",
        history,
        mode: modeEl.value,
        session_id: sessionId,
        allowed_tools: allowedTools(),
        attachments: pendingAttachments,
      };

      try {
        if (useStreamEl.checked) {
          const res = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

          startAssistantMessage();
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buf = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const parts = buf.split("\n\n");
            buf = parts.pop() || "";
            for (const part of parts) {
              const line = part.split("\n").find(l => l.startsWith("data: "));
              if (!line) continue;
              const data = line.slice(6);
              if (data === "[DONE]") continue;
              try {
                const j = JSON.parse(data);
                if (j.token) appendAssistantChunk(j.token);
                if (j.error) appendAssistantChunk(`\nError: ${j.error}`);
              } catch {}
            }
          }
          await saveServerHistory();
        } else {
          const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || (`HTTP ${res.status}`));
          await push("assistant", data.reply || "(sin respuesta)");
        }
      } catch (err) {
        await push("assistant", "Error: " + (err?.message || String(err)));
      } finally {
        pendingAttachments = [];
        attachEl.value = "";
        attachInfoEl.textContent = "";
        sendEl.disabled = false;
        inputEl.focus();
      }
    }

    sendEl.addEventListener("click", () => sendMessage());
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
      if (e.ctrlKey && e.key.toLowerCase() === "l") {
        e.preventDefault();
        inputEl.focus();
      }
    });

    attachEl.addEventListener("change", async () => {
      const files = Array.from(attachEl.files || []);
      pendingAttachments = await readAttachments(files);
      attachInfoEl.textContent = pendingAttachments.length
        ? `${pendingAttachments.length} adjunto(s): ${pendingAttachments.map(a => a.name).join(", ")}`
        : "";
    });

    btnFirefoxEl.addEventListener("click", () => sendMessage("abrí firefox"));
    btnDesktopEl.addEventListener("click", () => sendMessage("decime que carpetas y archivos hay en mi escritorio"));
    newSessionEl.addEventListener("click", () => sendMessage("/new"));
    exportMdEl.addEventListener("click", exportMd);
    exportTxtEl.addEventListener("click", exportTxt);

    loadServerHistory().then(() => inputEl.focus());
  </script>
</body>
</html>
"""


def _extract_url(text: str) -> str | None:
    m = re.search(r"(https?://[^\s]+)", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    no_accents = "".join(c for c in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_accents).strip()


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


def _open_url_with_site_context(url: str, site_key: str | None) -> str | None:
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


def _open_site_urls(entries: list[tuple[str | None, str]]) -> tuple[list[str], str | None]:
    opened = []
    for site_key, url in entries:
        error = _open_url_with_site_context(url, site_key)
        if error:
            return opened, error
        opened.append(url)
    return opened, None


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


def _resolve_site_browser_config(site_key: str) -> tuple[str, str]:
    cfg = _load_browser_profile_config()
    site_cfg = cfg.get(site_key, {})
    if not site_cfg:
        site_cfg = cfg.get("_default", {})

    browser = str(site_cfg.get("browser", "")).lower().strip() or "chrome"
    profile = _resolve_chrome_profile_directory(str(site_cfg.get("profile", "")).strip() or "Default")
    return browser, profile


def _prepare_shadow_chrome_user_data(profile_dir: str) -> tuple[str, str | None]:
    src_root = Path.home() / ".config" / "google-chrome"
    src_profile = src_root / profile_dir
    if not src_root.exists() or not src_profile.exists():
        return str(src_root), "source_profile_missing"

    dst_root = Path.home() / ".openclaw" / "web_ask_shadow" / "google-chrome"
    dst_profile = dst_root / profile_dir
    dst_root.mkdir(parents=True, exist_ok=True)
    dst_profile.parent.mkdir(parents=True, exist_ok=True)

    local_state_src = src_root / "Local State"
    local_state_dst = dst_root / "Local State"
    try:
        if local_state_src.exists():
            shutil.copy2(local_state_src, local_state_dst)
    except Exception:
        # non-fatal: playwright can still launch without latest Local State
        pass

    rsync = shutil.which("rsync")
    if rsync:
        cmd = [
            rsync,
            "-a",
            "--delete",
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
            # fallback to shutil copytree below
            pass

    try:
        if dst_profile.exists():
            shutil.rmtree(dst_profile)
        shutil.copytree(src_profile, dst_profile)
        return str(dst_root), None
    except Exception as e:
        return str(src_root), f"shadow_copy_failed:{e}"


def _parse_json_object(raw: str) -> dict | None:
    data = (raw or "").strip()
    if not data:
        return None
    try:
        parsed = json.loads(data)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    start = data.find("{")
    end = data.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(data[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _log_web_ask(event: dict) -> None:
    try:
        WEB_ASK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False)
        with WEB_ASK_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        return


def _extract_web_ask_request(message: str) -> tuple[str, str] | None:
    msg = message.strip()
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
        return site_key, prompt
    return None


def _run_web_ask(site_key: str, prompt: str, timeout_ms: int = 60000) -> dict:
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

    shadow_user_data_dir, shadow_warn = _prepare_shadow_chrome_user_data(profile)

    cmd = [
        node,
        str(WEB_ASK_SCRIPT_PATH),
        "--site",
        site_key,
        "--prompt",
        prompt,
        "--profile-dir",
        profile,
        "--user-data-dir",
        shadow_user_data_dir,
        "--timeout-ms",
        str(timeout_ms),
        "--headless",
        "false",
    ]
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
        result = {
            "ok": False,
            "status": "timeout",
            "text": "",
            "evidence": "playwright_runner_timeout",
            "timings": {"start": started, "end": time.time(), "duration": round(time.time() - started, 3)},
        }
        _log_web_ask({"ts": time.time(), "site": site_key, "status": result["status"], "prompt": prompt[:220], "result": result})
        return result
    except Exception as e:
        result = {
            "ok": False,
            "status": "runner_error",
            "text": "",
            "evidence": str(e),
            "timings": {"start": started, "end": time.time(), "duration": round(time.time() - started, 3)},
        }
        _log_web_ask({"ts": time.time(), "site": site_key, "status": result["status"], "prompt": prompt[:220], "result": result})
        return result

    payload = _parse_json_object(proc.stdout) or {}
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
        }
    )
    return payload


def _format_web_ask_reply(site_key: str, prompt: str, result: dict) -> str:
    provider = "ChatGPT" if site_key == "chatgpt" else "Gemini"
    status = str(result.get("status", "error"))
    duration = result.get("timings", {}).get("duration", "?")
    if result.get("ok"):
        text = str(result.get("text", "")).strip()
        if not text:
            text = "(respuesta vacía)"
        if len(text) > 6000:
            text = text[:6000] + "\n\n[...respuesta truncada por longitud...]"
        return f"{provider} respondió:\n{text}\n\nEstado: ok ({duration}s)."

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


def _safe_session_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", value)[:64]
    return cleaned or "default"


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


def _maybe_handle_local_action(message: str, allowed_tools: set[str]) -> dict | None:
    text = message.lower()
    normalized = _normalize_text(message)

    web_req = _extract_web_ask_request(message)
    if web_req is not None:
        if "firefox" not in allowed_tools:
            return {"reply": "La herramienta local 'firefox' está deshabilitada en esta sesión."}
        site_key, prompt = web_req
        result = _run_web_ask(site_key, prompt, timeout_ms=60000)
        return {"reply": _format_web_ask_reply(site_key, prompt, result)}

    if "firefox" in text and any(k in normalized for k in ("abr", "open", "lanz", "inici")):
        if "firefox" not in allowed_tools:
            return {"reply": "La herramienta local 'firefox' está deshabilitada en esta sesión."}
        url = _extract_url(message) or "about:blank"
        opened, error = _open_site_urls([(None, url)])
        if error:
            return {"reply": error}
        return {"reply": f"Listo, abrí Firefox en: {opened[0]}"}

    site_keys = _canonical_site_keys(message)
    wants_open = any(k in normalized for k in ("abr", "open", "entra", "entrar", "ir a", "lanz", "inici"))
    wants_search = ("busc" in normalized) or any(k in normalized for k in ("search", "investiga", "investigar"))
    wants_new_chat = any(k in normalized for k in ("chat nuevo", "nuevo chat", "iniciar una conversacion", "iniciar conversacion"))
    topic = _extract_topic(message)

    m_site_search = re.search(r"(?:busca|buscar|search)\s+(.+?)\s+en\s+(youtube|wikipedia)", normalized, flags=re.IGNORECASE)
    if "firefox" in allowed_tools and m_site_search:
        query = m_site_search.group(1).strip()
        site = m_site_search.group(2).strip()
        url = _build_site_search_url(site, query)
        if url:
            opened, error = _open_site_urls([(site, url)])
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
            opened, error = _open_site_urls(entries)
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
        opened, error = _open_site_urls([("youtube", url)]) if url else ([], "No pude construir la búsqueda en YouTube.")
        if error:
            return {"reply": error}
        return {"reply": f"Abrí videos de YouTube sobre '{query}': {opened[0]}"}

    if "firefox" in allowed_tools and site_keys and wants_open and not wants_search and not wants_new_chat:
        entries = [(site_key, _site_url(site_key)) for site_key in site_keys]
        opened, error = _open_site_urls(entries)
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

    def _json(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

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

            if not message:
                self._json(400, {"error": "Missing message"})
                return

            local_action = _maybe_handle_local_action(message, allowed_tools)
            if local_action is not None:
                if self.path == "/api/chat/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    reply = str(local_action.get("reply", ""))
                    out = json.dumps({"token": reply}, ensure_ascii=False).encode("utf-8")
                    self.wfile.write(b"data: " + out + b"\n\n")
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                    self.close_connection = True
                    return

                self._json(200, local_action)
                return

            messages = self._build_messages(message, history, mode, allowed_tools, attachments)

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
                    self.wfile.write(b"data: " + out + b"\n\n")
                    self.wfile.flush()
                    time.sleep(0.01)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
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
