#!/usr/bin/env node
"use strict";

// Stress test the local Molbot Direct Chat UI by typing into the textarea and clicking "Enviar".
// This uses the real browser UI (not the internal API) as requested.

const { chromium } = require("playwright");

const BASE_URL = process.env.DIRECT_CHAT_URL || "http://127.0.0.1:8787/";
const ROUNDS = Number(process.env.ROUNDS || "5");

const OPEN_COMMANDS = [
  "abrí youtube",
  "abrí chatgpt",
  "abrí gemini",
  "abrí wikipedia",
  "abrí firefox https://github.com/",
  "abrí firefox https://news.ycombinator.com/",
];

async function ensureCheckbox(page, labelText, checked) {
  const loc = page.getByLabel(labelText, { exact: true });
  if (checked) {
    await loc.check({ timeout: 5000 });
  } else {
    await loc.uncheck({ timeout: 5000 });
  }
}

async function sendAndWait(page, text) {
  const chat = page.locator("#chat");
  const beforeAssistant = await chat.locator(".msg.assistant").count();

  const input = page.getByRole("textbox", { name: "Escribi en lenguaje natural..." });
  await input.click();
  await input.fill(text);
  await page.getByRole("button", { name: "Enviar" }).click();

  // In non-stream mode, assistant reply is appended as a full message.
  await page.waitForFunction(
    (n) => document.querySelectorAll("#chat .msg.assistant").length > n,
    beforeAssistant,
    { timeout: 120000 }
  );

  const afterAssistant = await chat.locator(".msg.assistant").count();
  const last = chat.locator(".msg.assistant").nth(afterAssistant - 1);
  const reply = (await last.innerText()).trim();
  return reply;
}

async function clickNewSession(page) {
  await page.getByRole("button", { name: "Nueva sesion" }).click();
  // New session clears chat client-side after server history save.
  await page.waitForTimeout(400);
}

async function main() {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      // Keep it readable in CI logs / terminal.
      console.error("[console.error]", msg.text());
    }
  });

  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

  // Keep it deterministic: disable streaming so we wait for one assistant message per request.
  await ensureCheckbox(page, "firefox", true);
  await ensureCheckbox(page, "web_search", true);
  await ensureCheckbox(page, "web_ask", true);
  await ensureCheckbox(page, "escritorio", true);
  await ensureCheckbox(page, "modelo", true);
  await ensureCheckbox(page, "streaming", false);

  for (let i = 1; i <= ROUNDS; i++) {
    console.log(`Round ${i}/${ROUNDS}`);
    await clickNewSession(page);

    for (const cmd of OPEN_COMMANDS) {
      const reply = await sendAndWait(page, cmd);
      console.log("  ", cmd, "=>", reply.split("\n")[0].slice(0, 160));
      if (/pestañ[aá] conectada|relay|extensi[oó]n/i.test(reply)) {
        throw new Error(`Unexpected relay/extension message for cmd="${cmd}": ${reply}`);
      }
      if (/^error:/i.test(reply)) {
        throw new Error(`UI returned error for cmd="${cmd}": ${reply}`);
      }
    }

    const closeReply = await sendAndWait(page, "cerrá las ventanas web que abriste");
    console.log("  close =>", closeReply.split("\n")[0].slice(0, 200));
    if (!/Cerr[eé]\s+\d+\s+ventana/i.test(closeReply)) {
      throw new Error(`Close did not confirm window count: ${closeReply}`);
    }

    await page.waitForTimeout(700);
  }

  await browser.close();
}

main().catch(async (err) => {
  console.error("FAILED:", err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});

