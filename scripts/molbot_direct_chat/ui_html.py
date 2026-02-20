# NOTE: This file intentionally contains a large embedded HTML string.
# Keeping it separate from the server logic makes the Python file maintainable.

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
    .voice-toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid #2fffd9;
      color: #b7fff2;
      background: linear-gradient(135deg, rgba(8, 38, 44, 0.85), rgba(6, 18, 32, 0.95));
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      cursor: pointer;
      text-transform: uppercase;
      box-shadow: 0 0 0 1px rgba(47, 255, 217, 0.2) inset;
    }
    .voice-toggle[data-on="0"] {
      border-color: #6a789f;
      color: #b4bdd6;
      background: linear-gradient(135deg, rgba(26, 34, 58, 0.92), rgba(19, 25, 43, 0.96));
      box-shadow: none;
    }
    .voice-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #2fffd9;
      box-shadow: 0 0 10px rgba(47, 255, 217, 0.9);
      transition: transform 0.12s ease;
    }
    .voice-toggle[data-on="0"] .voice-dot {
      background: #8b96b8;
      box-shadow: none;
    }
    .voice-toggle.speaking .voice-dot {
      animation: voice-pulse 0.8s infinite;
    }
    @keyframes voice-pulse {
      0% { transform: scale(1.0); box-shadow: 0 0 4px rgba(47, 255, 217, 0.6); }
      50% { transform: scale(1.35); box-shadow: 0 0 14px rgba(47, 255, 217, 1); }
      100% { transform: scale(1.0); box-shadow: 0 0 4px rgba(47, 255, 217, 0.6); }
    }
    .meter {
      font-size: 12px;
      color: var(--muted);
      border: 1px solid var(--border);
      background: rgba(18, 24, 49, 0.85);
      border-radius: 999px;
      padding: 6px 10px;
      white-space: nowrap;
    }
    .meter strong { color: var(--text); font-weight: 700; }
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
	        <div class="meter" id="meter">RAM: <strong>...</strong> | Proc: <strong>...</strong> | VRAM: <strong>...</strong></div>
	        <select id="model" style="min-width:320px"></select>
        <button class="alt" id="clearChat">Limpiar chat</button>
        <button class="alt" id="newSession">Nueva sesion</button>
      </div>
    </div>

	    <div class="tools">
	      <span>Herramientas locales:</span>
	      <label><input type="checkbox" id="toolWebSearch" checked /> web_search</label>
	      <label><input type="checkbox" id="toolWebAsk" checked /> web_ask</label>
	      <label><input type="checkbox" id="toolDesktop" checked /> escritorio</label>
	      <button class="voice-toggle" id="voiceToggle" data-on="0" type="button">
          <span class="voice-dot"></span>
          <span id="voiceToggleText">VOZ OFF</span>
        </button>
      <span class="small">Slash: /new /escritorio</span>
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
    const sendEl = document.getElementById("send");
    const clearChatEl = document.getElementById("clearChat");
    const newSessionEl = document.getElementById("newSession");
	    const toolWebSearchEl = document.getElementById("toolWebSearch");
	    const toolWebAskEl = document.getElementById("toolWebAsk");
	    const toolDesktopEl = document.getElementById("toolDesktop");
	    const voiceToggleEl = document.getElementById("voiceToggle");
	    const voiceToggleTextEl = document.getElementById("voiceToggleText");
	    const attachEl = document.getElementById("attach");
	    const attachInfoEl = document.getElementById("attachInfo");
	    const meterEl = document.getElementById("meter");

    const SESSION_KEY = "molbot_direct_chat_session_id";
    const MODEL_KEY = "molbot_direct_chat_model_id";
    let sessionId = localStorage.getItem(SESSION_KEY) || crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sessionId);

	    let history = [];
	    let pendingAttachments = [];
      let voiceEnabled = true;
      let speakingTimer = null;
      let activeStreamController = null;
      let sttPollTimer = null;
      let sttSending = false;
      let sttLastText = "";
      let sttLastTextAtMs = 0;

	    function fmtMb(mb) {
	      if (mb == null || Number.isNaN(mb)) return "?";
	      if (mb > 1024) return (mb / 1024).toFixed(1) + " GB";
	      return Math.round(mb) + " MB";
	    }

	    async function refreshMeter() {
	      try {
	        const r = await fetch("/api/metrics");
	        const j = await r.json();
	        const sys = j.sys || {};
	        const proc = j.proc || {};
	        const gpu = (j.gpu || {}).vram;

	        const ram = `${fmtMb(sys.ram_used_mb)}/${fmtMb(sys.ram_total_mb)}`;
	        const pr = fmtMb(proc.rss_mb);
	        let vram = "N/A";
	        if (gpu && gpu.total_mb != null) {
	          vram = `${fmtMb(gpu.used_mb)}/${fmtMb(gpu.total_mb)}`;
	        }
	        meterEl.innerHTML = `RAM: <strong>${ram}</strong> | Proc: <strong>${pr}</strong> | VRAM: <strong>${vram}</strong>`;
	      } catch {
	        // keep last value
	      }
	    }

	    function allowedTools() {
	      const out = [];
	      out.push("firefox");
	      if (toolWebSearchEl.checked) out.push("web_search");
	      if (toolWebAskEl.checked) out.push("web_ask");
	      if (toolDesktopEl.checked) out.push("desktop");
	      if (voiceEnabled) out.push("tts");
	      out.push("model");
	      return out;
	    }

    function selectedModel() {
      const value = (modelEl.value || "").trim();
      const opt = modelEl.selectedOptions && modelEl.selectedOptions[0];
      const backend = (opt?.dataset?.backend || "").trim() || "cloud";
      return { model: value, model_backend: backend };
    }

    function modelExists(id) {
      const wanted = (id || "").trim();
      if (!wanted) return false;
      return Array.from(modelEl.options).some((o) => o.value === wanted);
    }

    async function refreshModels(force = false) {
      const qs = force ? "?refresh=1" : "";
      let payload = { default_model: "openai-codex/gpt-5.1-codex-mini", models: [] };
      try {
        const r = await fetch(`/api/models${qs}`);
        if (r.ok) payload = await r.json();
      } catch {}

      const models = Array.isArray(payload.models) ? payload.models : [];
      modelEl.innerHTML = "";

      for (const m of models) {
        const opt = document.createElement("option");
        const id = (m?.id || "").toString();
        if (!id) continue;
        const backend = (m?.backend || "cloud").toString();
        const available = !!m?.available;
        opt.value = id;
        opt.dataset.backend = backend;
        opt.dataset.available = available ? "1" : "0";
        const missing = backend === "local" && !available ? " (no instalado)" : "";
        opt.textContent = `${id} [${backend}]${missing}`;
        modelEl.appendChild(opt);
      }

      if (!modelEl.options.length) {
        const fallback = document.createElement("option");
        fallback.value = payload.default_model || "openai-codex/gpt-5.1-codex-mini";
        fallback.dataset.backend = "cloud";
        fallback.textContent = fallback.value + " [cloud]";
        modelEl.appendChild(fallback);
      }

      const persisted = (localStorage.getItem(MODEL_KEY) || "").trim();
      const desired = persisted || (payload.default_model || modelEl.options[0].value);
      const exists = modelExists(desired);
      if (persisted && !exists) {
        localStorage.removeItem(MODEL_KEY);
      }
      modelEl.value = exists ? desired : modelEl.options[0].value;
      localStorage.setItem(MODEL_KEY, modelEl.value);
    }

    function abortCurrentStream() {
      if (activeStreamController) {
        activeStreamController.abort();
        activeStreamController = null;
      }
    }

    function stopSttPolling() {
      if (sttPollTimer) {
        clearInterval(sttPollTimer);
        sttPollTimer = null;
      }
    }

    let sttLastSendAtMs = 0;
    const STT_MIN_SEND_INTERVAL_MS = 1500;

    function shouldAcceptSttText(text) {
      const t = (text || "").trim();
      if (t.length < 3) return false;
      const now = Date.now();
      if (t === sttLastText && (now - sttLastTextAtMs) < 4000) return false;
      sttLastText = t;
      sttLastTextAtMs = now;
      return true;
    }

    async function pollSttOnce() {
      if (!voiceEnabled) return;
      if (sendEl.disabled || sttSending) return;
      try {
        const q = new URLSearchParams({ session_id: sessionId, limit: "2" });
        const r = await fetch(`/api/stt/poll?${q.toString()}`);
        if (!r.ok) return;
        const j = await r.json();
        const items = Array.isArray(j?.items) ? j.items : [];
        for (const item of items) {
          const text = String(item?.text || "").trim();
          if (!shouldAcceptSttText(text)) continue;
          const nowSend = Date.now();
          if ((nowSend - sttLastSendAtMs) < STT_MIN_SEND_INTERVAL_MS) break;
          sttLastSendAtMs = nowSend;
          sttSending = true;
          try {
            await sendMessage(text);
          } finally {
            sttSending = false;
          }
          break;
        }
      } catch {}
    }

    function startSttPolling() {
      if (!voiceEnabled) return;
      if (sttPollTimer) return;
      sttPollTimer = setInterval(() => {
        pollSttOnce();
      }, 700);
      pollSttOnce();
    }

    async function claimVoiceOwner() {
      if (!voiceEnabled) return;
      try {
        await fetch("/api/voice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId }),
        });
      } catch {}
    }

    function setVoiceVisual(enabled) {
      voiceEnabled = !!enabled;
      voiceToggleEl.dataset.on = voiceEnabled ? "1" : "0";
      voiceToggleTextEl.textContent = voiceEnabled ? "VOZ ON" : "VOZ OFF";
      localStorage.setItem("molbot_voice_enabled", voiceEnabled ? "1" : "0");
      if (voiceEnabled) {
        startSttPolling();
      } else {
        stopSttPolling();
      }
    }

    function markSpeaking(active) {
      if (active) {
        voiceToggleEl.classList.add("speaking");
        return;
      }
      voiceToggleEl.classList.remove("speaking");
    }

    async function syncVoiceState() {
      try {
        const r = await fetch("/api/voice");
        const j = await r.json();
        setVoiceVisual(!!j.enabled);
        if (j.enabled && String(j.stt_owner_session_id || "").trim() === "" && sessionId !== "default") {
          await claimVoiceOwner();
        }
        return;
      } catch {}
      const ls = localStorage.getItem("molbot_voice_enabled");
      setVoiceVisual(ls !== "0");
    }

    async function setVoiceStateServer(enabled) {
      setVoiceVisual(enabled);
      try {
        await fetch("/api/voice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: !!enabled, session_id: sessionId }),
        });
      } catch {}
    }

    function el(tag, cls, text) {
      const node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = text;
      return node;
    }

    function draw() {
      chatEl.innerHTML = "";
      for (const m of history) {
        const box = el("div", `msg ${m.role === "user" ? "user" : "assistant"}`, m.content);
        chatEl.appendChild(box);
      }
      chatEl.scrollTop = chatEl.scrollHeight;
    }

    async function push(role, content) {
      history.push({ role, content });
      history = history.slice(-200);
      draw();
      await saveServerHistory();
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
      if (t === "/escritorio") return { kind: "message", text: "decime que carpetas y archivos hay en mi escritorio" };
      return { kind: "unknown" };
    }

    async function saveServerHistory() {
      const sel = selectedModel();
      try {
        await fetch("/api/history", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            model: sel.model,
            model_backend: sel.model_backend,
            history,
          }),
        });
      } catch {}
    }

    async function loadServerHistory() {
      const sel = selectedModel();
      const q = new URLSearchParams({
        session: sessionId,
        model: sel.model || "",
        model_backend: sel.model_backend || "",
      });
      try {
        const r = await fetch(`/api/history?${q.toString()}`);
        const j = await r.json();
        history = Array.isArray(j.history) ? j.history : [];
      } catch {
        history = [];
      }
      draw();
    }

    async function recoverModelSelection(errorCode) {
      const msg = errorCode === "MISSING_MODEL"
        ? "Modelo no instalado; volví al default."
        : "Modelo ya no disponible; volví al default.";
      localStorage.removeItem(MODEL_KEY);
      abortCurrentStream();
      await refreshModels(true);
      await loadServerHistory();
      await push("assistant", msg);
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
        if (voiceEnabled) {
          await claimVoiceOwner();
        }
        inputEl.value = "";
        return;
      }
      if (slash?.kind === "message") text = slash.text;
      if (slash?.kind === "unknown") {
        await push("assistant", "Comando desconocido. Usá /new /escritorio");
        inputEl.value = "";
        return;
      }

      if (pendingAttachments.length) {
        text += "\n\nAdjuntos:\n" + pendingAttachments.map(a => `- ${a.name} (${a.type})`).join("\n");
      }

      inputEl.value = "";
      await push("user", text);
      sendEl.disabled = true;
      abortCurrentStream();
      const controller = new AbortController();
      activeStreamController = controller;

      const sel = selectedModel();

      const payload = {
        message: text,
        model: sel.model || "openai-codex/gpt-5.1-codex-mini",
        model_backend: sel.model_backend || "cloud",
        history,
        mode: "operativo",
        session_id: sessionId,
        allowed_tools: allowedTools(),
        attachments: pendingAttachments,
      };

      try {
        if (true) {
          const res = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            signal: controller.signal,
          });
          if (!res.ok) {
            let errCode = "";
            let errText = `HTTP ${res.status}`;
            try {
              const j = await res.json();
              errCode = String(j?.error || "").trim();
              errText = errCode ? `${errCode}` : errText;
            } catch {}
            if (errCode === "UNKNOWN_MODEL" || errCode === "MISSING_MODEL") {
              await recoverModelSelection(errCode);
              return;
            }
            throw new Error(errText);
          }
          if (!res.body) throw new Error(`HTTP ${res.status}`);

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
          if (voiceEnabled) {
            markSpeaking(true);
            if (speakingTimer) clearTimeout(speakingTimer);
            speakingTimer = setTimeout(() => markSpeaking(false), 6000);
          }
          await saveServerHistory();
        }
      } catch (err) {
        if (err?.name === "AbortError") return;
        await push("assistant", "Error: " + (err?.message || String(err)));
      } finally {
        if (activeStreamController === controller) {
          activeStreamController = null;
        }
        pendingAttachments = [];
        attachEl.value = "";
        attachInfoEl.textContent = "";
        sendEl.disabled = false;
        inputEl.focus();
        await syncVoiceState();
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

    newSessionEl.addEventListener("click", () => sendMessage("/new"));
    modelEl.addEventListener("change", async () => {
      if (!modelExists(modelEl.value)) {
        localStorage.removeItem(MODEL_KEY);
        await refreshModels(true);
      }
      localStorage.setItem(MODEL_KEY, modelEl.value || "");
      abortCurrentStream();
      await loadServerHistory();
      inputEl.focus();
    });
    clearChatEl.addEventListener("click", async () => {
      history = [];
      draw();
      await saveServerHistory();
      inputEl.focus();
    });

    voiceToggleEl.addEventListener("click", async () => {
      await setVoiceStateServer(!voiceEnabled);
      if (!voiceEnabled) markSpeaking(false);
    });

    syncVoiceState();
    refreshModels()
      .then(() => loadServerHistory())
      .then(() => inputEl.focus());
    refreshMeter();
    setInterval(refreshMeter, 2000);
  </script>
</body>
</html>
"""
