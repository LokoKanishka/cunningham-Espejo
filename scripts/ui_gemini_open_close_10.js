#!/usr/bin/env node
"use strict";

// Type into Molbot Direct Chat UI like a human and request 10 different
// "open/close Gemini" commands.

const { chromium } = require("playwright");

const BASE_URL = process.env.DIRECT_CHAT_URL || "http://127.0.0.1:8787/";
const HEADLESS = String(process.env.HEADLESS || "true").toLowerCase() === "true";

const COMMANDS = [
  { kind: "open", text: "abrí gemini" },
  { kind: "close", text: "cerrá las ventanas web que abriste" },
  { kind: "open", text: "abre gemini por favor" },
  { kind: "close", text: "cerrar ventanas web abiertas por vos" },
  { kind: "open", text: "abrime gemini" },
  { kind: "close", text: "cierra las ventanas web que abriste en esta sesion" },
  { kind: "open", text: "quiero abrir gemini" },
  { kind: "close", text: "close web windows you opened" },
  { kind: "open", text: "abrir gemini ahora" },
  { kind: "close", text: "por favor cerrá las ventanas web que abriste" },
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

  await input.click({ delay: 40 });
  await input.press("Control+A");
  await input.press("Backspace");
  await input.type(text, { delay: 23 });
  await page.getByRole("button", { name: "Enviar" }).click();

  await page.waitForFunction(
    (n) => document.querySelectorAll("#chat .msg.assistant").length > n,
    beforeAssistant,
    { timeout: 90000 }
  );

  const afterAssistant = await chat.locator(".msg.assistant").count();
  const last = chat.locator(".msg.assistant").nth(afterAssistant - 1);
  return (await last.innerText()).trim();
}

function looksOk(kind, reply) {
  const r = String(reply || "");
  if (kind === "open") return /abr[ií]|abri|gemini|cliente configurado|flujo fijo/i.test(r);
  return /cerr[eé]\s+\d+\s+ventana|cerr[eé]\s+0\s+ventana/i.test(r);
}

async function main() {
  const browser = await chromium.launch({ headless: HEADLESS });
  const results = [];
  try {
    const page = await browser.newPage();
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

    await ensureCheckbox(page, "firefox", true);
    await ensureCheckbox(page, "streaming", false);
    await clickNewSession(page);

    for (let i = 0; i < COMMANDS.length; i += 1) {
      const c = COMMANDS[i];
      const reply = await sendAndWait(page, c.text);
      const ok = looksOk(c.kind, reply);
      results.push({
        idx: i + 1,
        kind: c.kind,
        command: c.text,
        ok,
        reply: reply.split("\n")[0].slice(0, 220),
      });
      await page.waitForTimeout(250);
    }
  } finally {
    await browser.close();
  }

  const passed = results.filter((r) => r.ok).length;
  process.stdout.write(`RESULT ${passed}/${results.length}\n`);
  for (const r of results) {
    process.stdout.write(`[${r.idx}] ${r.ok ? "OK" : "FAIL"} ${r.kind} :: ${r.command}\n`);
    process.stdout.write(`     -> ${r.reply}\n`);
  }
  if (passed !== results.length) process.exitCode = 1;
}

main().catch((err) => {
  console.error("FAILED:", err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});

