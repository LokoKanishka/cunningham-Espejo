#!/usr/bin/env node
"use strict";

const { chromium } = require("playwright");

const BASE_URL = process.env.DIRECT_CHAT_URL || "http://127.0.0.1:8787/";
const HEADED = String(process.env.HEADED || "").trim() === "1";
const CLOUD_MODEL = "openai-codex/gpt-5.1-codex-mini";
const LOCAL_MODELS = ["dolphin-mixtral:latest", "huihui_ai/qwq-abliterated:32b-Q6_K"];
const EXPECTED_MODELS = [CLOUD_MODEL, ...LOCAL_MODELS];

async function sendAndWaitReply(page, text) {
  const chat = page.locator("#chat");
  const beforeAssistant = await chat.locator(".msg.assistant").count();
  await page.getByRole("textbox", { name: "Escribi en lenguaje natural..." }).fill(text);
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

async function collectModels(page) {
  return await page.evaluate(() => {
    const sel = document.getElementById("model");
    if (!sel) return [];
    return Array.from(sel.options || []).map((opt) => String(opt.value || "").trim()).filter(Boolean);
  });
}

async function main() {
    const browser = await chromium.launch({ headless: !HEADED });
  try {
    const page = await browser.newPage();
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });

    const models = await collectModels(page);
    const gotSorted = [...models].sort();
    const expectedSorted = [...EXPECTED_MODELS].sort();
    if (gotSorted.length !== expectedSorted.length || gotSorted.some((m, i) => m !== expectedSorted[i])) {
      throw new Error(`model_list_mismatch expected=${JSON.stringify(expectedSorted)} got=${JSON.stringify(gotSorted)}`);
    }

    const modelSelect = page.locator("#model");
    for (const modelId of EXPECTED_MODELS) {
      await modelSelect.selectOption(modelId);
      const reply = await sendAndWaitReply(page, "hola");
      if (!reply || /^error:/i.test(reply)) {
        throw new Error(`model_failed model=${modelId} reply=${JSON.stringify(reply)}`);
      }
      console.log(`MODEL_OK ${modelId}: ${reply.slice(0, 120)}`);
    }

    console.log("DC_UI_MODELS_OK");
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error("DC_UI_MODELS_FAIL:", err && err.stack ? err.stack : String(err));
  process.exitCode = 1;
});
