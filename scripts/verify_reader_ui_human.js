#!/usr/bin/env node

const { chromium } = require("playwright");

const BASE = process.env.DC_BASE_URL || "http://127.0.0.1:8787";
const HEADED = process.env.HEADED === "1";

function norm(s) {
  return String(s || "").replace(/\s+/g, " ").trim();
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

async function sendAndWaitAssistant(page, text, timeoutMs = 45000) {
  const prev = await getAssistantCount(page);
  await page.fill("#input", text);
  await page.click("#send");
  await page.waitForFunction(() => {
    const btn = document.querySelector("#send");
    return !!btn && !btn.disabled;
  }, { timeout: timeoutMs });
  await page.waitForFunction((prevCount) => {
    return document.querySelectorAll(".msg.assistant").length > prevCount;
  }, prev, { timeout: timeoutMs });
  return await getLastAssistantText(page);
}

async function main() {
  const browser = await chromium.launch({ headless: !HEADED });
  const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
  const page = await context.newPage();

  try {
    await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForSelector("#input", { timeout: 20000 });

    // Start clean and choose local model to keep interruption test deterministic.
    await page.click("#newSession");
    await page.waitForTimeout(350);
    await page.evaluate(() => {
      const sel = document.querySelector("#model");
      if (!sel) return;
      const opts = Array.from(sel.options || []);
      const local = opts.find((o) => String(o.dataset.backend || "").trim() === "local");
      if (!local) return;
      sel.value = local.value;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForTimeout(400);

    await sendAndWaitAssistant(page, "biblioteca rescan");
    await sendAndWaitAssistant(page, "biblioteca");

    const beforeRead = await getAssistantCount(page);
    const firstRead = await sendAndWaitAssistant(page, "leer libro 1", 50000);
    if (!/bloque\s+\d+\//i.test(firstRead)) {
      throw new Error(`leer_libro_missing_block_header reply=${firstRead.slice(0, 220)}`);
    }
    if (firstRead.length < 100) {
      throw new Error(`leer_libro_reply_too_short len=${firstRead.length}`);
    }

    // Reader auto-continue: at least 3 assistant blocks after starting.
    await page.waitForFunction((baseCount) => {
      return document.querySelectorAll(".msg.assistant").length >= baseCount + 3;
    }, beforeRead, { timeout: 30000 });

    const assistantTexts = await page.$$eval(".msg.assistant", (els) => els.map((e) => (e.textContent || "").replace(/\s+/g, " ").trim()));
    const tail = assistantTexts.slice(-3);
    for (const t of tail) {
      if (!t || t.length < 80) {
        throw new Error(`auto_block_empty_or_short text=${String(t).slice(0, 120)}`);
      }
      if (!/bloque\s+\d+\//i.test(t)) {
        throw new Error(`auto_block_missing_header text=${String(t).slice(0, 160)}`);
      }
    }

    // Interruption with normal message.
    await sendAndWaitAssistant(page, "hola", 50000);
    const estado = await sendAndWaitAssistant(page, "estado lectura", 50000);
    if (!/cursor=\d+\//i.test(estado)) {
      throw new Error(`estado_missing_cursor reply=${estado.slice(0, 220)}`);
    }
    if (!/continua=off/i.test(estado)) {
      throw new Error(`interrupt_not_applied reply=${estado.slice(0, 240)}`);
    }

    // Resume check.
    const resumed = await sendAndWaitAssistant(page, "seguí", 50000);
    if (!/bloque\s+\d+\//i.test(resumed)) {
      throw new Error(`resume_missing_block reply=${resumed.slice(0, 220)}`);
    }

    console.log(`READER_UI_HUMAN_OK base=${BASE}`);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((err) => {
  console.error("READER_UI_HUMAN_FAIL:", err && (err.stack || err.message || String(err)));
  process.exit(1);
});
