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

    // Keep this verifier deterministic: anti-flood checks without TTS confirmations.
    await sendAndWaitAssistant(page, "voz off", 80000);

    await sendAndWaitAssistant(page, "biblioteca rescan");
    await sendAndWaitAssistant(page, "biblioteca");

    const beforeRead = await getAssistantCount(page);
    await sendViaUI(page, "leer libro 1");
    await waitSendEnabled(page, 80000);
    const firstRead = await waitUntil("leer_libro_block_reply", async () => {
      const txt = await getLastAssistantText(page);
      return /bloque\s+\d+\//i.test(txt) ? txt : false;
    }, { timeoutMs: 80000, minDelayMs: 120, maxDelayMs: 1200 });
    if (!/bloque\s+\d+\//i.test(firstRead)) {
      throw new Error(`leer_libro_missing_block_header reply=${firstRead.slice(0, 220)}`);
    }
    if (firstRead.length < 100) {
      throw new Error(`leer_libro_reply_too_short len=${firstRead.length}`);
    }

    const sessionId = await getSessionId(page);
    const stManualStart = await readerStatus(context.request, sessionId);
    if (stManualStart.continuous_enabled === true) {
      throw new Error(`manual_default_failed status=${JSON.stringify(stManualStart)}`);
    }

    await sleep(3200);
    const stAfterWait = await readerStatus(context.request, sessionId);
    if (Number(stAfterWait.cursor || 0) !== Number(stManualStart.cursor || 0)) {
      throw new Error(`manual_cursor_moved_without_input before=${stManualStart.cursor} after=${stAfterWait.cursor}`);
    }

    const beforeManual = stAfterWait;
    const resumed1 = await sendAndWaitAssistant(page, "seguí", 80000);
    if (!/bloque\s+\d+\//i.test(resumed1) && !/fin de lectura/i.test(resumed1)) {
      throw new Error(`manual_1_missing_block reply=${resumed1.slice(0, 220)}`);
    }
    const afterManual1 = await readerStatus(context.request, sessionId);
    if (Number(afterManual1.cursor || 0) > (Number(beforeManual.cursor || 0) + 1)) {
      throw new Error(`manual_1_advanced_more_than_one before=${beforeManual.cursor} after=${afterManual1.cursor}`);
    }
    if (afterManual1.continuous_enabled === true) {
      throw new Error(`manual_1_reactivated_continuous status=${JSON.stringify(afterManual1)}`);
    }

    const resumed2 = await sendAndWaitAssistant(page, "seguí", 80000);
    if (!/bloque\s+\d+\//i.test(resumed2) && !/fin de lectura/i.test(resumed2)) {
      throw new Error(`manual_2_missing_block reply=${resumed2.slice(0, 220)}`);
    }
    const afterManual2 = await readerStatus(context.request, sessionId);
    if (Number(afterManual2.cursor || 0) > (Number(afterManual1.cursor || 0) + 1)) {
      throw new Error(`manual_2_advanced_more_than_one prev=${afterManual1.cursor} after=${afterManual2.cursor}`);
    }
    if (afterManual2.continuous_enabled === true) {
      throw new Error(`manual_2_reactivated_continuous status=${JSON.stringify(afterManual2)}`);
    }

    const contOnReply = await sendAndWaitAssistant(page, "continuo on", 80000);
    if (!/continua|continuo/i.test(contOnReply)) {
      throw new Error(`continuous_on_missing_ack reply=${contOnReply.slice(0, 220)}`);
    }
    const stContOn = await readerStatus(context.request, sessionId);
    if (stContOn.continuous_enabled !== true) {
      throw new Error(`continuous_on_not_applied status=${JSON.stringify(stContOn)}`);
    }

    // In opt-in continuous mode, reader can chain with pacing.
    const afterEnableCount = await getAssistantCount(page);
    await sendAndWaitAssistant(page, "seguí", 80000);
    await waitUntil("continuous_progress_after_opt_in", async () => {
      const now = await getAssistantCount(page);
      return now >= (afterEnableCount + 1);
    }, { timeoutMs: 45000, minDelayMs: 140, maxDelayMs: 1800 });

    await sendViaUI(page, "pausa lectura");
    await waitUntil("reader_paused", async () => {
      const st = await readerStatus(context.request, sessionId);
      return st.continuous_enabled === false;
    }, { timeoutMs: 25000, minDelayMs: 100, maxDelayMs: 1000 });

    await waitSendEnabled(page, 80000);
    const estado = await sendAndWaitAssistant(page, "estado lectura", 80000);
    if (!/cursor=\d+\//i.test(estado)) {
      throw new Error(`estado_missing_cursor reply=${estado.slice(0, 220)}`);
    }
    if (!/continua=off/i.test(estado)) {
      throw new Error(`pause_not_applied reply=${estado.slice(0, 240)}`);
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
