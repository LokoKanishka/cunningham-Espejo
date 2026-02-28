# Dedicated Reader UI to keep voice/reading flow isolated from chat writing mode.
READER_HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Molbot Reader</title>
  <style>
    :root {
      --bg: #060708;
      --panel: #0e1216;
      --text: #dff5ff;
      --muted: #8cb3c5;
      --accent: #00d2ff;
      --border: #1e3442;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      color: var(--text);
      background: radial-gradient(1200px 700px at 20% -10%, #0e3348 0%, transparent 55%), var(--bg);
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 14px;
    }
    .app {
      width: min(980px, 100%);
      height: min(92vh, 920px);
      border: 1px solid var(--border);
      border-radius: 16px;
      background: var(--panel);
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      overflow: hidden;
    }
    .top, .tools, .composer { padding: 10px 14px; border-bottom: 1px solid var(--border); }
    .top { display: flex; gap: 10px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
    .tools { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .title { font-weight: 700; color: #b8ecff; }
    .meta { color: var(--muted); font-size: 13px; }
    .chat { padding: 14px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
    .msg { max-width: 90%; padding: 10px 12px; border-radius: 10px; border: 1px solid #284454; background: #13212b; white-space: pre-wrap; }
    .msg.user { align-self: flex-end; background: #112a35; border-color: #2b566d; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .mini-input {
      width: 86px;
      border-radius: 8px;
      border: 1px solid #3a6178;
      background: #0c1c25;
      color: #e8f6ff;
      padding: 6px 8px;
      font: inherit;
      font-size: 13px;
    }
    button {
      border: 1px solid #316078;
      background: #102734;
      color: #dff5ff;
      border-radius: 10px;
      padding: 8px 10px;
      font-weight: 700;
      cursor: pointer;
    }
    button.alt { background: #16202a; color: #b6ccda; border-color: #324b5c; }
    textarea {
      width: 100%;
      min-height: 84px;
      border-radius: 10px;
      border: 1px solid #35566b;
      background: #0c1c25;
      color: #e8f6ff;
      resize: vertical;
      padding: 10px;
      font: inherit;
    }
    .status { font-size: 12px; color: #9ac8de; border: 1px solid #27485a; border-radius: 999px; padding: 6px 10px; }
  </style>
</head>
<body>
  <div class="app">
    <div class="top">
      <div>
        <div class="title">Molbot Reader Mode</div>
        <div class="meta">Pantalla dedicada de lectura con voz aislada.</div>
      </div>
      <div class="row">
        <div class="status" id="status">reader_mode: booting...</div>
        <button class="alt" id="backChat">Volver a chat</button>
      </div>
    </div>

    <div class="tools">
      <button id="cmdLibrary">biblioteca</button>
      <button id="cmdRead1">leer libro 1</button>
      <button id="cmdPrevParagraph">párrafo anterior</button>
      <button id="cmdNextParagraph">párrafo siguiente</button>
      <button id="cmdPause">pausa lectura</button>
      <button id="cmdContinue">continuar</button>
      <button id="cmdStop">detenete</button>
      <button id="cmdComment">de que habla este bloque?</button>
      <input id="jumpParagraph" class="mini-input" type="number" min="1" step="1" placeholder="párrafo #" />
      <button id="jumpParagraphGo">ir</button>
    </div>

    <div class="chat" id="chat"></div>

    <div class="composer">
      <div class="row">
        <textarea id="input" placeholder="Comandos de lectura..."></textarea>
      </div>
      <div class="row" style="margin-top:8px;">
        <button id="send">Enviar</button>
      </div>
    </div>
  </div>

  <script>
    const chatEl = document.getElementById("chat");
    const inputEl = document.getElementById("input");
    const sendEl = document.getElementById("send");
    const statusEl = document.getElementById("status");
    const backChatEl = document.getElementById("backChat");
    const jumpParagraphEl = document.getElementById("jumpParagraph");
    const jumpParagraphGoEl = document.getElementById("jumpParagraphGo");
    const SESSION_KEY = "molbot_reader_session_id";
    const TAB_KEY = "molbot_reader_tab_id";
    const sessionId = localStorage.getItem(SESSION_KEY) || crypto.randomUUID();
    const readerTabId = sessionStorage.getItem(TAB_KEY) || crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sessionId);
    sessionStorage.setItem(TAB_KEY, readerTabId);
    let history = [];

    function draw() {
      chatEl.innerHTML = "";
      for (const m of history) {
        const box = document.createElement("div");
        box.className = `msg ${m.role === "user" ? "user" : "assistant"}`;
        box.textContent = m.content;
        chatEl.appendChild(box);
      }
      chatEl.scrollTop = chatEl.scrollHeight;
    }

    function push(role, content) {
      history.push({ role, content: String(content || "") });
      history = history.slice(-220);
      draw();
    }

    async function callVoice(payload) {
      const r = await fetch("/api/voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, reader_owner_token: readerTabId, ...payload }),
      });
      return await r.json();
    }

    async function syncStatus() {
      try {
        const r = await fetch("/api/voice");
        const j = await r.json();
        const owner = String(j.voice_owner || "chat");
        const active = !!j.reader_mode_active;
        statusEl.textContent = `reader_mode: ${active ? "ON" : "OFF"} | owner: ${owner} | voz: ${j.enabled ? "ON" : "OFF"}`;
      } catch {
        statusEl.textContent = "reader_mode: status_error";
      }
    }

    async function activateReaderMode() {
      await callVoice({
        voice_owner: "reader",
        reader_mode_active: true,
        enabled: true,
        voice_mode_profile: "stable",
      });
      await syncStatus();
    }

    async function releaseReaderMode() {
      await callVoice({
        voice_owner: "chat",
        reader_mode_active: false,
        enabled: false,
      });
    }

    async function sendMessage(textFromButton = "") {
      const msg = String(textFromButton || inputEl.value || "").trim();
      if (!msg) return;
      push("user", msg);
      inputEl.value = "";
      sendEl.disabled = true;
      try {
        const r = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            message: msg,
            allowed_tools: ["tts"],
            history: history.slice(-40),
            mode: "operativo",
          }),
        });
        const j = await r.json();
        if (!r.ok) {
          const detail = String(j.error || j.detail || `HTTP ${r.status}`);
          push("assistant", `Error: ${detail}`);
        } else if (typeof j.reply === "string" && j.reply.trim()) {
          push("assistant", j.reply);
        } else if (j && (j.error || j.detail)) {
          push("assistant", `Error: ${String(j.error || j.detail)}`);
        } else {
          push("assistant", "[sin respuesta]");
        }
      } catch (e) {
        push("assistant", "Error: " + String((e && e.message) || e));
      } finally {
        sendEl.disabled = false;
        await syncStatus();
        inputEl.focus();
      }
    }

    function bindQuick(id, text) {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("click", () => sendMessage(text));
    }

    bindQuick("cmdLibrary", "biblioteca");
    bindQuick("cmdRead1", "leer libro 1");
    bindQuick("cmdPrevParagraph", "volver un párrafo");
    bindQuick("cmdNextParagraph", "continuar");
    bindQuick("cmdPause", "pausa lectura");
    bindQuick("cmdContinue", "continuar");
    bindQuick("cmdStop", "detenete");
    bindQuick("cmdComment", "de que habla este bloque?");

    sendEl.addEventListener("click", () => sendMessage());
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    async function jumpToParagraph() {
      const raw = String(jumpParagraphEl.value || "").trim();
      const num = Number(raw);
      if (!Number.isFinite(num) || num < 1) {
        push("assistant", "Indicá un número de párrafo válido (>= 1).");
        jumpParagraphEl.focus();
        return;
      }
      await sendMessage(`ir al párrafo ${Math.trunc(num)}`);
    }

    jumpParagraphGoEl.addEventListener("click", () => {
      jumpToParagraph();
    });

    jumpParagraphEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        jumpToParagraph();
      }
    });

    backChatEl.addEventListener("click", async () => {
      await releaseReaderMode();
      window.location.href = "/";
    });

    window.addEventListener("beforeunload", () => {
      try {
        const payload = JSON.stringify({
          session_id: sessionId,
          reader_owner_token: readerTabId,
          voice_owner: "chat",
          reader_mode_active: false,
          enabled: false,
        });
        if (navigator && typeof navigator.sendBeacon === "function") {
          navigator.sendBeacon("/api/voice", new Blob([payload], { type: "application/json" }));
        }
      } catch {}
    });

    activateReaderMode().then(() => {
      push("assistant", "Modo lectura activo. Decí: biblioteca o leer libro 1.");
      inputEl.focus();
    });
  </script>
</body>
</html>
"""
