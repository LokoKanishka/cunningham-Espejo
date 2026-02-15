#!/usr/bin/env node
"use strict";

// Drive the local UI like a human: type questions and click Enviar.
// Focus: validate UI + model integration using local SearXNG web_search lane.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const BASE_URL = process.env.DIRECT_CHAT_URL || "http://127.0.0.1:8787/";
const OUT_DIR = process.env.OUT_DIR || path.join(process.cwd(), "output", "playwright");

const QUESTIONS = [
  "busca en internet: quien es el presidente actual de Argentina? responde en 1 frase y cita",
  "busca en internet: precio actual de Bitcoin (BTC) en USD. responde con numero y cita",
  "busca en internet: que es la teoria de la relatividad. responde en 3 bullets y cita",
  "busca en internet: cual fue el ultimo ganador del Balon de Oro. responde y cita",
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
    { timeout: 120000 }
  );

  const afterAssistant = await chat.locator(".msg.assistant").count();
  const last = chat.locator(".msg.assistant").nth(afterAssistant - 1);
  return (await last.innerText()).trim();
}

function looksOk(reply) {
  if (!reply) return false;
  if (/^error:/i.test(reply)) return false;
  // Must be grounded in our local results format (either "resultado N", "Fuente:",
  // or numeric citation like "(1)").
  if (!/resultado\s+\d+/i.test(reply) && !/fuente\s*:/i.test(reply) && !/\(\d+\)/.test(reply)) return false;
  return true;
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

  // Deterministic settings for this run.
  await ensureCheckbox(page, "web_search", true);
  await ensureCheckbox(page, "streaming", false);
  // Others can stay enabled; web_search path is explicit-trigger only.

  await clickNewSession(page);

  for (let i = 0; i < QUESTIONS.length; i++) {
    const q = QUESTIONS[i];
    const reply = await sendAndWait(page, q);
    const firstLine = reply.split("\n")[0].slice(0, 160);
    console.log(`Q${i + 1}: ${q}`);
    console.log(`A${i + 1}: ${firstLine}`);

    if (!looksOk(reply)) {
      const shot = path.join(OUT_DIR, `ui_web_search_fail_q${i + 1}.png`);
      await page.screenshot({ path: shot, fullPage: true });
      throw new Error(`Bad reply for Q${i + 1}. Screenshot: ${shot}. Reply: ${reply}`);
    }
  }

  if (consoleErrors.length) {
    const logPath = path.join(OUT_DIR, "ui_web_search_console_errors.log");
    fs.writeFileSync(logPath, consoleErrors.join("\n"), "utf-8");
    console.error(`Console had ${consoleErrors.length} error(s). Saved: ${logPath}`);
  }

  await browser.close();
}

main().catch((err) => {
  console.error("FAILED:", err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});
