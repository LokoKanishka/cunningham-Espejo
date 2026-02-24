#!/usr/bin/env node

const { chromium } = require("playwright");

const BASE = process.env.DC_BASE_URL || "http://127.0.0.1:8787";
const HEADED = process.env.HEADED === "1";
const SESSION_KEY = "molbot_direct_chat_session_id";
const PREFERRED_MODELS = ["dolphin-mixtral:latest", "ollama/dolphin-mixtral:latest"];

function norm(s) {
  return String(s || "").replace(/\s+/g, " ").trim();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitUntil(label, fn, opts = {}) {
  const timeoutMs = Number(opts.timeoutMs || 45000);
  const minDelayMs = Number(opts.minDelayMs || 120);
  const maxDelayMs = Number(opts.maxDelayMs || 1500);
  const factor = Number(opts.factor || 1.45);
  const start = Date.now();
  let delay = minDelayMs;
  let lastErr = "";
  while ((Date.now() - start) < timeoutMs) {
    try {
      const out = await fn();
      if (out) return out;
    } catch (err) {
      lastErr = err && (err.message || String(err)) || "";
    }
    await sleep(delay);
    delay = Math.min(maxDelayMs, Math.round(delay * factor));
  }
  const detail = lastErr ? ` last_err=${lastErr}` : "";
  throw new Error(`timeout_${label}_after_${timeoutMs}ms${detail}`);
}

async function getAssistantCount(page) {
  return await page.locator(".msg.assistant").count();
}

async function getLastAssistantText(page) {
  const nodes = page.locator(".msg.assistant");
  const n = await nodes.count();
  if (!n) return "";
  return norm(await nodes.nth(n - 1).innerText());
}

async function getSessionId(page) {
  return await page.evaluate((k) => localStorage.getItem(k) || "", SESSION_KEY);
}

async function waitSendEnabled(page, timeoutMs = 60000) {
  await waitUntil("send_enabled", async () => {
    return await page.evaluate(() => {
      const btn = document.querySelector("#send");
      return !!btn && !btn.disabled;
    });
  }, { timeoutMs });
}

async function sendViaUI(page, text) {
  await waitSendEnabled(page);
  await page.fill("#input", text);
  await page.click("#send");
}

async function sendAndWaitAssistant(page, text, timeoutMs = 70000) {
  const prev = await getAssistantCount(page);
  const prevLast = await getLastAssistantText(page);
  await sendViaUI(page, text);
  await waitSendEnabled(page, timeoutMs);
  await waitUntil("assistant_appended", async () => {
    const now = await getAssistantCount(page);
    if (now > prev) return true;
    const nextLast = await getLastAssistantText(page);
    return !!nextLast && nextLast !== prevLast;
  }, { timeoutMs });
  return await getLastAssistantText(page);
}

async function readerStatus(request, sessionId) {
  const r = await request.get(`${BASE}/api/reader/session?session_id=${encodeURIComponent(sessionId)}`);
  if (!r.ok()) {
    throw new Error(`reader_status_http_${r.status()}`);
  }
  const j = await r.json();
  if (!j || typeof j !== "object") {
    throw new Error("reader_status_bad_json");
  }
  return j;
}

async function ensureModelSelected(page) {
  await waitUntil("models_loaded", async () => {
    return await page.evaluate(() => {
      const sel = document.querySelector("#model");
      return !!sel && (sel.options?.length || 0) > 0;
    });
  }, { timeoutMs: 30000 });

  const out = await page.evaluate((preferred) => {
    const sel = document.querySelector("#model");
    if (!sel) return { ok: false, reason: "selector_missing", options: [] };
    const options = Array.from(sel.options || []).map((o) => ({
      value: String(o.value || ""),
      backend: String(o.dataset.backend || ""),
    }));
    const candidate = options.find((o) => preferred.includes(o.value));
    if (!candidate) return { ok: false, reason: "model_not_found", options };
    sel.value = candidate.value;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true, selected: candidate.value, options };
  }, PREFERRED_MODELS);

  if (!out?.ok) {
    const available = (out?.options || []).map((o) => `${o.value}[${o.backend}]`).join(", ");
    throw new Error(`required_model_missing wanted=${PREFERRED_MODELS.join("|")} available=${available || "none"}`);
  }
  return String(out.selected || "");
}

async function main() {
  const browser = await chromium.launch({ headless: !HEADED });
  const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
  const page = await context.newPage();

  try {
    await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForSelector("#input", { timeout: 20000 });

    const model = await ensureModelSelected(page);
    await waitSendEnabled(page, 30000);
    await sleep(300);
    const sidModel = await getSessionId(page);
    await page.click("#newSession");
    await waitUntil("new_session_after_model", async () => {
      const now = await getSessionId(page);
      return !!now && now !== sidModel;
    }, { timeoutMs: 15000 });
    await waitSendEnabled(page, 30000);
    await sleep(250);

    await sendAndWaitAssistant(page, "biblioteca rescan");
    await sendAndWaitAssistant(page, "biblioteca");

    const beforeRead = await getAssistantCount(page);
    const firstRead = await sendAndWaitAssistant(page, "leer libro 1", 80000);
    if (!/bloque\s+\d+\//i.test(firstRead)) {
      throw new Error(`leer_libro_missing_block_header reply=${firstRead.slice(0, 220)}`);
    }
    if (firstRead.length < 100) {
      throw new Error(`leer_libro_reply_too_short len=${firstRead.length}`);
    }

    const sessionId = await getSessionId(page);
    const initialStatus = await readerStatus(context.request, sessionId);
    const total = Math.max(1, Number(initialStatus.total_chunks || 0));
    const targetCursor = total >= 2 ? 2 : 1;

    const progressedStatus = await waitUntil("reader_auto_progress", async () => {
      const st = await readerStatus(context.request, sessionId);
      if (st.done) return st;
      if (Number(st.cursor || 0) >= targetCursor) return st;
      return false;
    }, { timeoutMs: 60000, minDelayMs: 140, maxDelayMs: 2000 });

    if (!progressedStatus.done && Number(progressedStatus.cursor || 0) < targetCursor) {
      throw new Error(`reader_no_progress cursor=${progressedStatus.cursor} target=${targetCursor} total=${total}`);
    }

    if (total >= 2) {
      await waitUntil("assistant_auto_block_visible", async () => {
        const now = await getAssistantCount(page);
        return now >= (beforeRead + 2);
      }, { timeoutMs: 45000 });
      const autoText = await getLastAssistantText(page);
      if (!/bloque\s+\d+\//i.test(autoText)) {
        throw new Error(`auto_block_missing_header text=${autoText.slice(0, 220)}`);
      }
      if (autoText.length < 80) {
        throw new Error(`auto_block_too_short len=${autoText.length}`);
      }
    }

    // Interruption: trigger from UI, assert reader mode switches off via status API
    // without waiting for model inference to finish.
    await sendViaUI(page, "hola");
    await waitUntil("reader_interrupted", async () => {
      const st = await readerStatus(context.request, sessionId);
      return st.continuous_active === false;
    }, { timeoutMs: 25000, minDelayMs: 100, maxDelayMs: 1000 });

    await waitSendEnabled(page, 80000);
    const estado = await sendAndWaitAssistant(page, "estado lectura", 80000);
    if (!/cursor=\d+\//i.test(estado)) {
      throw new Error(`estado_missing_cursor reply=${estado.slice(0, 220)}`);
    }
    if (!/continua=off/i.test(estado)) {
      throw new Error(`interrupt_not_applied reply=${estado.slice(0, 240)}`);
    }

    const resumed = await sendAndWaitAssistant(page, "seguí", 80000);
    if (!/bloque\s+\d+\//i.test(resumed) && !/fin de lectura/i.test(resumed)) {
      throw new Error(`resume_missing_block reply=${resumed.slice(0, 220)}`);
    }

    console.log(`READER_UI_HUMAN_OK base=${BASE} model=${model}`);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((err) => {
  console.error("READER_UI_HUMAN_FAIL:", err && (err.stack || err.message || String(err)));
  process.exit(1);
});
