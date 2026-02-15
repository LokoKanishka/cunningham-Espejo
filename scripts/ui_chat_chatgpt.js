#!/usr/bin/env node
"use strict";

// Drive Molbot Direct Chat UI like a human and start a 3-turn chat with ChatGPT via web_ask.
// If ChatGPT isn't logged-in in the shadow profile, it triggers the bootstrap login and waits.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const BASE_URL = process.env.DIRECT_CHAT_URL || "http://127.0.0.1:8787/";
const OUT_DIR = process.env.OUT_DIR || path.join(process.cwd(), "output", "playwright");
const LOGIN_WAIT_MS = Number(process.env.LOGIN_WAIT_MS || "180000");

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
  await input.click();
  await input.fill(text);
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
  return /login_required|requiere\s+login|login\s+manual|iniciar\s+sesi[oó]n|sign\s*in|log\s*in/i.test(reply);
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

async function main() {
  const browser = await chromium.launch({ headless: true });
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

    if (!/Turno\s+3/i.test(reply)) {
      const shot = await screenshot(page, `ui_chatgpt_no_turn3.png`);
      throw new Error(`Chat did not reach 3 turns. Screenshot: ${shot}. Reply: ${reply}`);
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
