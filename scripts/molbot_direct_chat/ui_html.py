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
	        <input id="model" value="openai-codex/gpt-5.1-codex-mini" style="min-width:260px" />
        <button class="alt" id="clearChat">Limpiar chat</button>
        <button class="alt" id="newSession">Nueva sesion</button>
      </div>
    </div>

	    <div class="tools">
	      <span>Herramientas locales:</span>
	      <label><input type="checkbox" id="toolWebSearch" checked /> web_search</label>
	      <label><input type="checkbox" id="toolWebAsk" checked /> web_ask</label>
	      <label><input type="checkbox" id="toolDesktop" checked /> escritorio</label>
	      <label><input type="checkbox" id="toolTts" checked /> voz</label>
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
	    const toolTtsEl = document.getElementById("toolTts");
	    const attachEl = document.getElementById("attach");
	    const attachInfoEl = document.getElementById("attachInfo");
	    const meterEl = document.getElementById("meter");

    const SESSION_KEY = "molbot_direct_chat_session_id";
    let sessionId = localStorage.getItem(SESSION_KEY) || crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sessionId);

	    let history = [];
	    let pendingAttachments = [];

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
	      if (toolTtsEl.checked) out.push("tts");
	      out.push("model");
	      return out;
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
      try {
        await fetch("/api/history", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, history }),
        });
      } catch {}
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

      const payload = {
        message: text,
        model: modelEl.value.trim() || "openai-codex/gpt-5.1-codex-mini",
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

    newSessionEl.addEventListener("click", () => sendMessage("/new"));
    clearChatEl.addEventListener("click", async () => {
      history = [];
      draw();
      await saveServerHistory();
      inputEl.focus();
    });

    loadServerHistory().then(() => inputEl.focus());
    refreshMeter();
    setInterval(refreshMeter, 2000);
  </script>
</body>
</html>
"""
