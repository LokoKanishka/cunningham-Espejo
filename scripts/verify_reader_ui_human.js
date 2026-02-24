#!/usr/bin/env node

const { chromium } = require("playwright");

const BASE = process.env.DC_BASE_URL || "http://127.0.0.1:8787";
const HEADED = process.env.HEADED === "1";
const SESSION_KEY = "molbot_direct_chat_session_id";
const PREFERRED_MODELS = ["dolphin-mixtral:latest", "ollama/dolphin-mixtral:latest"];

function norm(s) {
  return String(s || "").replace(/\s+/g, " ").trim();
}

function looksLikeReadingReply(text) {
  const t = norm(text);
  if (!t) return false;
  if (/bloque\s+\d+\//i.test(t)) return true;
  if (/fin de lectura/i.test(t)) return true;
  if (/^retomo desde:/i.test(t)) return true;
  if (/^retroced[ií]/i.test(t)) return true;
  return false;
}

function isPacingReply(text) {
  return /pausa breve de lectura/i.test(norm(text));
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

async function settleReadingReply(page, initialReply, timeoutMs = 25000) {
  if (looksLikeReadingReply(initialReply)) return initialReply;
  if (!isPacingReply(initialReply)) return initialReply;
  const baseline = await getAssistantCount(page);
  return await waitUntil("reading_reply_after_pacing", async () => {
    const now = await getAssistantCount(page);
    if (now <= baseline) return false;
    const txt = await getLastAssistantText(page);
    return looksLikeReadingReply(txt) ? txt : false;
  }, { timeoutMs, minDelayMs: 120, maxDelayMs: 1500 });
}

async function sendReaderCommandExpectReading(page, text, timeoutMs = 80000) {
  const first = await sendAndWaitAssistant(page, text, timeoutMs);
  let settled = await settleReadingReply(page, first, 35000);
  if (looksLikeReadingReply(settled)) return settled;
  const fallback = await sendAndWaitAssistant(page, "seguí", timeoutMs);
  settled = await settleReadingReply(page, fallback, 35000);
  return settled;
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

async function voiceStatus(request) {
  const r = await request.get(`${BASE}/api/voice`);
  if (!r.ok()) return {};
  const j = await r.json();
  return (j && typeof j === "object") ? j : {};
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

    await waitSendEnabled(page, 80000);

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
    const stAutoStart = await readerStatus(context.request, sessionId);
    if (stAutoStart.continuous_enabled !== true) {
      throw new Error(`autopilot_default_not_enabled status=${JSON.stringify(stAutoStart)}`);
    }
    if (stAutoStart.manual_mode === true) {
      throw new Error(`autopilot_default_in_manual_mode status=${JSON.stringify(stAutoStart)}`);
    }

    const autoStartCount = await getAssistantCount(page);
    await waitUntil("autopilot_progress_without_input", async () => {
      const now = await getAssistantCount(page);
      const st = await readerStatus(context.request, sessionId);
      return now >= (autoStartCount + 1) || Number(st.cursor || 0) > Number(stAutoStart.cursor || 0);
    }, { timeoutMs: 12000, minDelayMs: 140, maxDelayMs: 1200 });

    await sendAndWaitAssistant(page, "detenete", 80000);
    await waitUntil("reader_stopped_by_barge", async () => {
      const st = await readerStatus(context.request, sessionId);
      return st.continuous_enabled === false && (st.reader_state === "commenting" || st.reader_state === "paused");
    }, { timeoutMs: 25000, minDelayMs: 100, maxDelayMs: 1000 });

    await sendAndWaitAssistant(page, "estado lectura", 80000);

    const continued = await sendReaderCommandExpectReading(page, "continuar", 80000);
    if (!looksLikeReadingReply(continued)) {
      throw new Error(`continuar_missing_block reply=${continued.slice(0, 220)}`);
    }
    const stAfterContinue = await readerStatus(context.request, sessionId);
    if (stAfterContinue.continuous_enabled !== true && stAfterContinue.done !== true) {
      const lastTxt = await getLastAssistantText(page);
      const voiceNow = await voiceStatus(context.request);
      const detail = String(voiceNow?.last_status?.detail || "").trim().toLowerCase();
      const fallbackVoiceIssue = /voz no disponible/i.test(lastTxt) || (
        voiceNow?.enabled === true &&
        !!detail &&
        detail !== "ok_stream" &&
        detail !== "ok_player_dry_run" &&
        detail !== "not_started" &&
        detail !== "queued"
      );
      const fallbackPaused = String(stAfterContinue.continuous_reason || "") === "reader_user_paused";
      if (!fallbackVoiceIssue && !fallbackPaused) {
        throw new Error(`continuar_did_not_resume_autopilot status=${JSON.stringify(stAfterContinue)} last=${lastTxt.slice(0, 180)}`);
      }
    }

    const phraseMatch = continued.match(/[A-Za-zÁÉÍÓÚáéíóúñÑ]{6,}/);
    const phrase = phraseMatch ? phraseMatch[0] : "texto";
    const continuedFrom = await sendReaderCommandExpectReading(page, `continuar desde "${phrase}"`, 80000);
    if (!looksLikeReadingReply(continuedFrom) && !/no encontr[eé]/i.test(continuedFrom)) {
      throw new Error(`continuar_desde_unexpected reply=${continuedFrom.slice(0, 240)}`);
    }
    const stAfterContinueFrom = await readerStatus(context.request, sessionId);
    if (stAfterContinueFrom.continuous_enabled !== true && stAfterContinueFrom.done !== true) {
      const lastTxt = await getLastAssistantText(page);
      const fallbackPaused = String(stAfterContinueFrom.continuous_reason || "") === "reader_user_paused";
      if (!/voz no disponible/i.test(lastTxt) && !fallbackPaused) {
        throw new Error(`continuar_desde_did_not_resume_autopilot status=${JSON.stringify(stAfterContinueFrom)} last=${lastTxt.slice(0, 180)}`);
      }
    }

    const manualOnReply = await sendAndWaitAssistant(page, "modo manual on", 80000);
    if (!/manual/i.test(manualOnReply)) {
      throw new Error(`manual_on_missing_ack reply=${manualOnReply.slice(0, 220)}`);
    }
    const stManualOn = await readerStatus(context.request, sessionId);
    if (stManualOn.manual_mode !== true || stManualOn.continuous_enabled !== false) {
      throw new Error(`manual_on_not_applied status=${JSON.stringify(stManualOn)}`);
    }

    const beforeManual1 = Number(stManualOn.cursor || 0);
    const manual1 = await sendAndWaitAssistant(page, "seguí", 80000);
    if (!looksLikeReadingReply(manual1)) {
      throw new Error(`manual_1_missing_block reply=${manual1.slice(0, 220)}`);
    }
    const stManual1 = await readerStatus(context.request, sessionId);
    if (Number(stManual1.cursor || 0) > (beforeManual1 + 1)) {
      throw new Error(`manual_1_advanced_more_than_one before=${beforeManual1} after=${stManual1.cursor}`);
    }
    if (stManual1.continuous_enabled === true) {
      throw new Error(`manual_1_reactivated_autopilot status=${JSON.stringify(stManual1)}`);
    }

    const beforeManual2 = Number(stManual1.cursor || 0);
    const manual2 = await sendAndWaitAssistant(page, "seguí", 80000);
    if (!looksLikeReadingReply(manual2)) {
      throw new Error(`manual_2_missing_block reply=${manual2.slice(0, 220)}`);
    }
    const stManual2 = await readerStatus(context.request, sessionId);
    if (Number(stManual2.cursor || 0) > (beforeManual2 + 1)) {
      throw new Error(`manual_2_advanced_more_than_one before=${beforeManual2} after=${stManual2.cursor}`);
    }
    if (stManual2.continuous_enabled === true) {
      throw new Error(`manual_2_reactivated_autopilot status=${JSON.stringify(stManual2)}`);
    }

    const manualOffReply = await sendAndWaitAssistant(page, "modo manual off", 80000);
    if (!/autopiloto|manual desactivado/i.test(manualOffReply)) {
      throw new Error(`manual_off_missing_ack reply=${manualOffReply.slice(0, 220)}`);
    }
    const stManualOff = await readerStatus(context.request, sessionId);
    if (stManualOff.manual_mode === true || stManualOff.continuous_enabled !== true) {
      throw new Error(`manual_off_not_applied status=${JSON.stringify(stManualOff)}`);
    }

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
