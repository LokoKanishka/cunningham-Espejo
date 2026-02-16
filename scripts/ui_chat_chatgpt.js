#!/usr/bin/env node
"use strict";

// Drive Molbot Direct Chat UI like a human and start a 5-turn chat with ChatGPT via web_ask.
// If ChatGPT isn't logged-in in the shadow profile, it triggers the bootstrap login and waits.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const BASE_URL = process.env.DIRECT_CHAT_URL || "http://127.0.0.1:8787/";
const OUT_DIR = process.env.OUT_DIR || path.join(process.cwd(), "output", "playwright");
const LOGIN_WAIT_MS = Number(process.env.LOGIN_WAIT_MS || "180000");
const HEADLESS = String(process.env.HEADLESS || "false").toLowerCase() === "true";

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ensureCheckbox(page, labelText, checked) {
  const loc = page.getByLabel(labelText, { exact: true });
  if (checked) await loc.check({ timeout: 5000 });
  else await loc.uncheck({ timeout: 5000 });
}

async function clickNewSession(page) {
  await page.getByRole("button", { name: "Nueva sesion" }).click();
  await page.waitForTimeout(400);
}

async function sendAndWait(page, text) {
  const chat = page.locator("#chat");
  const beforeAssistant = await chat.locator(".msg.assistant").count();

  const input = page.getByRole("textbox", { name: "Escribi en lenguaje natural..." });
  await input.click({ delay: 40 });
  await input.press("Control+A");
  await input.press("Backspace");
  await input.type(text, { delay: 24 });
  await page.getByRole("button", { name: "Enviar" }).click();

  await page.waitForFunction(
    (n) => document.querySelectorAll("#chat .msg.assistant").length > n,
    beforeAssistant,
    { timeout: 180000 }
  );

  const afterAssistant = await chat.locator(".msg.assistant").count();
  const last = chat.locator(".msg.assistant").nth(afterAssistant - 1);
  return (await last.innerText()).trim();
}

function isLoginRequired(reply) {
  // Treat captcha/human verification like login_required: it needs a manual step in the shadow window.
  return /login_required|captcha_required|verifica\s+que\s+eres\s+un\s+ser\s+humano|turnstile|cloudflare|requiere\s+login|login\s+manual|iniciar\s+sesi[oó]n|sign\s*in|log\s*in|captcha/i.test(
    reply
  );
}

async function screenshot(page, name) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const p = path.join(OUT_DIR, name);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function ensureWebAskLoggedIn(page, provider) {
  const probe = `preguntale a ${provider}: responde solo con OK`;
  let reply = await sendAndWait(page, probe);
  if (!isLoginRequired(reply)) return;

  reply = await sendAndWait(page, `login ${provider}`);
  console.log(`login bootstrap for ${provider}:`, reply.split("\n")[0].slice(0, 160));
  console.log(`WAITING ${Math.round(LOGIN_WAIT_MS / 1000)}s for manual login in shadow window for ${provider}...`);
  await delay(LOGIN_WAIT_MS);

  reply = await sendAndWait(page, probe);
  if (isLoginRequired(reply)) {
    const shot = await screenshot(page, `ui_login_still_required_${provider}.png`);
    throw new Error(`Still login_required for ${provider}. Screenshot: ${shot}. Reply: ${reply}`);
  }
}

function validateReplyCoherence(reply, topic) {
  const r = String(reply || "").toLowerCase();
  if (!r || r.length < 100) return { ok: false, reason: "respuesta demasiado corta" };
  if (/login_required|captcha_required|selector_changed|timeout|profile_locked|blocked|error interno/i.test(r)) {
    return { ok: false, reason: "respuesta indica error operativo" };
  }
  const keywords = String(topic || "")
    .toLowerCase()
    .split(/[^a-z0-9áéíóúñü]+/i)
    .filter((w) => w.length >= 4)
    .slice(0, 4);
  const hits = keywords.filter((k) => r.includes(k)).length;
  if (hits < Math.min(2, keywords.length)) {
    return { ok: false, reason: "respuesta poco alineada al tema" };
  }
  const turnMatches = r.match(/turno\s+\d+/gi) || [];
  if (turnMatches.length < 5) {
    return { ok: false, reason: "no llegó a 5 turnos" };
  }
  return { ok: true, reason: "" };
}

async function main() {
  const browser = await chromium.launch({ headless: HEADLESS });
  try {
    const page = await browser.newPage();
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

    await ensureCheckbox(page, "web_ask", true);
    await ensureCheckbox(page, "streaming", false);
    await clickNewSession(page);

    await ensureWebAskLoggedIn(page, "chatgpt");

    const topic = process.env.TOPIC || "geopolitica: tension en el mar de China Meridional";
    const prompt = `dialoga con chatgpt: ${topic}`;
    const reply = await sendAndWait(page, prompt);

    const check = validateReplyCoherence(reply, topic);
    if (!check.ok) {
      const shot = await screenshot(page, `ui_chatgpt_invalid_reply.png`);
      throw new Error(`Chat invalid (${check.reason}). Screenshot: ${shot}. Reply: ${reply}`);
    }

    // Print the whole assistant reply to stdout.
    process.stdout.write(reply + "\n");
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error("FAILED:", err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});
