const { chromium } = require("playwright");

const BASE = "http://127.0.0.1:8787";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function norm(s) {
  return String(s || "").replace(/\s+/g, " ").trim().toLowerCase();
}

async function waitUntil(fn, { timeoutMs = 30000, stepMs = 150, label = "cond" } = {}) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const v = await fn();
      if (v) return v;
    } catch {}
    await sleep(stepMs);
  }
  throw new Error(`timeout:${label}`);
}

async function voiceState(ctx) {
  const r = await ctx.request.get(`${BASE}/api/voice`);
  if (!r.ok()) return {};
  return await r.json();
}

async function timeline(page) {
  return await page.$$eval(".msg", (nodes) =>
    nodes.map((n) => ({
      role: n.classList.contains("user") ? "user" : n.classList.contains("assistant") ? "assistant" : "other",
      text: (n.innerText || "").trim(),
    })),
  );
}

async function send(page, text) {
  await waitUntil(async () => !(await page.$eval("#send", (b) => b.disabled)), {
    timeoutMs: 90000,
    label: "send_enabled",
  });
  await page.fill("#input", text);
  await page.click("#send");
}

async function sendAndWaitAssistant(page, text, predicate = null, timeoutMs = 30000) {
  await send(page, text);
  const target = norm(text);
  return await waitUntil(
    async () => {
      const now = await timeline(page);
      let userIdx = -1;
      for (let i = now.length - 1; i >= 0; i--) {
        if (now[i].role !== "user") continue;
        const u = norm(now[i].text);
        if (u === target || u.includes(target) || target.includes(u)) {
          userIdx = i;
          break;
        }
      }
      if (userIdx < 0) return false;
      const fresh = [];
      for (let i = userIdx + 1; i < now.length; i++) {
        if (now[i].role !== "assistant") continue;
        const t = String(now[i].text || "").trim();
        if (t) fresh.push(t);
      }
      if (!fresh.length) return false;
      if (typeof predicate === "function") {
        for (let i = fresh.length - 1; i >= 0; i--) {
          if (predicate(fresh[i])) return fresh[i];
        }
        return false;
      }
      return fresh[fresh.length - 1];
    },
    { timeoutMs, stepMs: 180, label: `assistant_after_${text.slice(0, 18)}` },
  );
}

async function ensureVoiceOn(page) {
  const toggle = await page.$("#voiceToggle");
  if (!toggle) return false;
  const isOn = await page.$eval("#voiceToggle", (el) => String(el.getAttribute("data-on") || "0") === "1");
  if (isOn) return true;
  await page.click("#voiceToggle");
  await waitUntil(
    async () => await page.$eval("#voiceToggle", (el) => String(el.getAttribute("data-on") || "0") === "1"),
    { timeoutMs: 12000, label: "voice_on" },
  );
  return true;
}

async function main() {
  const browser = await chromium.launch({
    headless: false,
    executablePath: "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 920 } });
  const page = await ctx.newPage();

  const report = {
    ok: false,
    ttsStarted: false,
    pauseOk: false,
    commentOk: false,
    continueOk: false,
    stopOk: false,
    details: [],
  };

  try {
    await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForSelector("#input", { timeout: 20000 });
    await ensureVoiceOn(page);

    console.log("[sample] DC abierto. Activa VOZ ON ahora si queres; arranco en 5s...");
    await sleep(5000);

    await page.click("#newSession");
    await sleep(600);

    await sendAndWaitAssistant(page, "biblioteca", (last) => /biblioteca/i.test(last), 45000);
    console.log("[sample] biblioteca ok");

    let firstBlock = "";
    for (let i = 0; i < 20; i++) {
      const rep = await sendAndWaitAssistant(
        page,
        "leer libro 1",
        (last) => /lectura iniciada|ya estoy leyendo|bloque\s*1\s*\//i.test(last),
        30000,
      );
      if (!firstBlock && /bloque\s*1\s*\//i.test(rep)) firstBlock = rep;
      await sleep(120);
    }
    console.log("[sample] leer libro 1 x20 enviado");

    try {
      await waitUntil(async () => {
        const st = await voiceState(ctx);
        return !!st.tts_playing || Number(st.tts_playing_stream_id || 0) > 0;
      }, { timeoutMs: 12000, label: "tts_start" });
      report.ttsStarted = true;
    } catch {
      report.details.push("tts_not_detected_after_start");
    }

    await sleep(1800);

    const pauseReply = await sendAndWaitAssistant(
      page,
      "pausa lectura",
      (last) => norm(last) === "si como seguimos?",
      30000,
    );
    report.pauseOk = norm(pauseReply) === "si como seguimos?";
    console.log("[sample] pausa ->", pauseReply);

    const commentReply = await sendAndWaitAssistant(
      page,
      "de que habla este bloque?",
      (last) => last.length > 24 && !/ya estoy leyendo/i.test(last),
      45000,
    );
    report.commentOk = /bloque|lenguaje|habla|trata/i.test(commentReply);
    console.log("[sample] comentario ->", commentReply.slice(0, 120));

    const kw = /\blenguaje\b/i.test(firstBlock) ? "lenguaje" : "idea";
    const contReply = await sendAndWaitAssistant(
      page,
      `entonces segui desde ${kw}`,
      (last) => /retomo desde|bloque\s*\d+\s*\//i.test(last),
      45000,
    );
    report.continueOk = !!contReply;
    console.log("[sample] continuar ->", contReply.slice(0, 90));

    await sleep(1500);
    const stopReply = await sendAndWaitAssistant(page, "detenete", (last) => norm(last) === "detenida", 30000);
    report.stopOk = norm(stopReply) === "detenida";
    console.log("[sample] detener ->", stopReply);

    report.ok = report.ttsStarted && report.pauseOk && report.commentOk && report.continueOk && report.stopOk;
    console.log("[sample] RESULT=", JSON.stringify(report, null, 2));

    await sleep(1200);
  } catch (e) {
    report.details.push(`exception:${String(e && e.message ? e.message : e)}`);
    console.log("[sample] RESULT=", JSON.stringify(report, null, 2));
    process.exitCode = 2;
  } finally {
    await browser.close();
  }
}

main();
