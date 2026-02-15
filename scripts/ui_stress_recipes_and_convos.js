#!/usr/bin/env node
"use strict";

// UI-driven stress test: type into Molbot Direct Chat UI like a human.
// 1) 10 recipe requests via web_ask (ChatGPT/Gemini web)
// 2) 5 conversations, each with >=3 turns (dialoga uses followup + followup2)
//
// NOTE: If not logged-in in the shadow profile, it will ask you to run login and pause.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const BASE_URL = process.env.DIRECT_CHAT_URL || "http://127.0.0.1:8787/";
const OUT_DIR = process.env.OUT_DIR || path.join(process.cwd(), "output", "playwright");
const LOGIN_WAIT_MS = Number(process.env.LOGIN_WAIT_MS || "120000");
const HEADED = String(process.env.HEADED || "").trim() === "1";

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const RECIPES = [
  "preguntale a chatgpt: receta de budin de pistacho sin gluten para celiacos. dame ingredientes y pasos.",
  "preguntale a chatgpt: receta rapida de tortillas de maiz caseras (sin prensa), con tips.",
  "preguntale a chatgpt: receta de hummus clasico y una variante picante.",
  "preguntale a chatgpt: receta de pollo al horno con papas, tiempos y temperaturas.",
  "preguntale a chatgpt: receta de pan lactal casero, con medidas en gramos.",
  "preguntale a chatgpt: receta de sopa de calabaza cremosa, sin crema.",
  "preguntale a chatgpt: receta de brownies fudgy, como evitar que queden secos.",
  "preguntale a chatgpt: receta de salsa bolognesa tradicional, con sugerencias de vino.",
  "preguntale a chatgpt: receta de ensalada cesar con aderezo casero (sin anchoas opcional).",
  "preguntale a chatgpt: receta de galletitas de avena y banana (sin azucar agregada).",
];

const CONVERSATIONS = [
  { who: "chatgpt", topic: "geopolitica: tension en el mar de China Meridional" },
  { who: "gemini", topic: "economia: inflacion y politica monetaria" },
  { who: "chatgpt", topic: "tecnologia: riesgos y mitigaciones de IA en empresas" },
  { who: "gemini", topic: "energia: transicion energetica y seguridad de suministro" },
  { who: "chatgpt", topic: "salud: como evaluar evidencia cientifica sin caer en desinformacion" },
];

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
  // Probe with a tiny ask.
  const probe = `preguntale a ${provider}: responde solo con OK`;
  let reply = await sendAndWait(page, probe);
  if (!isLoginRequired(reply)) return;

  // Open bootstrap window via UI.
  const loginCmd = `login ${provider}`;
  reply = await sendAndWait(page, loginCmd);
  console.log(`login bootstrap for ${provider}:`, reply.split("\n")[0].slice(0, 160));

  // Give user time to log in manually.
  console.log(`WAITING ${Math.round(LOGIN_WAIT_MS / 1000)}s for manual login in shadow window for ${provider}...`);
  await delay(LOGIN_WAIT_MS);

  // Retry probe
  reply = await sendAndWait(page, probe);
  if (isLoginRequired(reply)) {
    const shot = await screenshot(page, `ui_login_still_required_${provider}.png`);
    throw new Error(`Still login_required for ${provider}. Screenshot: ${shot}. Reply: ${reply}`);
  }
}

async function main() {
  const consoleErrors = [];
  const browser = await chromium.launch({ headless: !HEADED });
  try {
    const page = await browser.newPage();
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

    // Deterministic: disable streaming so we wait for one assistant message.
    await ensureCheckbox(page, "web_ask", true);
    await ensureCheckbox(page, "streaming", false);

    await clickNewSession(page);

    // Ensure logins (may require user manual step).
    await ensureWebAskLoggedIn(page, "chatgpt");
    await ensureWebAskLoggedIn(page, "gemini");

    console.log("RECIPES (10)");
    for (let i = 0; i < RECIPES.length; i++) {
      const q = RECIPES[i];
      const r = await sendAndWait(page, q);
      console.log(`  R${i + 1}:`, r.split("\n")[0].slice(0, 160));
      if (isLoginRequired(r) || /^error:/i.test(r)) {
        const shot = await screenshot(page, `ui_recipe_fail_${i + 1}.png`);
        throw new Error(`Recipe ${i + 1} failed. Screenshot: ${shot}. Reply: ${r}`);
      }
    }

    console.log("CONVERSATIONS (5) x >=3 turns");
    for (let i = 0; i < CONVERSATIONS.length; i++) {
      const c = CONVERSATIONS[i];
      const q = `dialoga con ${c.who}: ${c.topic}`;
      const r = await sendAndWait(page, q);
      const first = r.split("\n")[0].slice(0, 160);
      console.log(`  C${i + 1}:`, first);
      if (!/Turno\s+3/i.test(r)) {
        const shot = await screenshot(page, `ui_convo_fail_${i + 1}.png`);
        throw new Error(`Conversation ${i + 1} did not reach 3 turns. Screenshot: ${shot}. Reply: ${r}`);
      }
    }

    if (consoleErrors.length) {
      fs.mkdirSync(OUT_DIR, { recursive: true });
      const logPath = path.join(OUT_DIR, "ui_recipes_convos_console_errors.log");
      fs.writeFileSync(logPath, consoleErrors.join("\n"), "utf-8");
      console.error(`Console had ${consoleErrors.length} error(s). Saved: ${logPath}`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error("FAILED:", err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});
