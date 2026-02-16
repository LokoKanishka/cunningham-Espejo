#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const SITE_CONFIG = {
  chatgpt: {
    url: "https://chatgpt.com/",
    inputSelectors: [
      "#prompt-textarea",
      "textarea[data-id]",
      "textarea[placeholder*='Message']",
      "textarea",
      "div[contenteditable='true'][data-id]",
      "div[contenteditable='true']",
    ],
    sendSelectors: [
      "button[data-testid='send-button']",
      "button[aria-label*='Send']",
      "button:has(svg)",
    ],
    responseSelectors: [
      "[data-message-author-role='assistant']",
      "article [data-message-author-role='assistant']",
      "article div.markdown",
      "div.markdown",
    ],
    loginSelectors: [
      "input[type='password']",
      "text=/iniciar\\s+sesi[oó]n/i",
      "text=/log\\s*in/i",
      "text=/sign\\s*in/i",
      "button:has-text('Log in')",
      "a:has-text('Log in')",
      "button:has-text('Iniciar sesión')",
      "a:has-text('Iniciar sesión')",
    ],
    minResponseLen: 4,
  },
  gemini: {
    url: "https://gemini.google.com/app",
    inputSelectors: [
      "rich-textarea div[contenteditable='true']",
      "div[contenteditable='true'][aria-label*='Mensaje']",
      "div[contenteditable='true'][aria-label*='Message']",
      "textarea[aria-label*='Gemini']",
      "div[contenteditable='true']",
      "textarea",
    ],
    sendSelectors: [
      "button[aria-label*='Enviar']",
      "button[aria-label*='Send']",
      "button:has(mat-icon)",
      "button.send-button",
    ],
    responseSelectors: [
      "model-response .markdown",
      "model-response",
      "message-content",
      ".response-content",
      "div.markdown",
    ],
    loginSelectors: [
      "input[type='password']",
      "button:has-text('Iniciar sesión')",
      "a:has-text('Iniciar sesión')",
      "button:has-text('Sign in')",
      "a:has-text('Sign in')",
      "text=/iniciar\\s+sesi[oó]n/i",
      "text=/sign\\s*in/i",
    ],
    minResponseLen: 4,
  },
};

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      out[key] = next;
      i += 1;
    } else {
      out[key] = "true";
    }
  }
  return out;
}

function nowEpoch() {
  return Date.now() / 1000;
}

function mkResult(site, startedAt) {
  return {
    ok: false,
    text: "",
    status: "error",
    evidence: "",
    timings: {
      start: startedAt,
      end: startedAt,
      duration: 0,
    },
    meta: {
      site,
    },
  };
}

function finish(result, status, ok, text = "", evidence = "") {
  const ended = nowEpoch();
  result.ok = ok;
  result.status = status;
  result.text = text;
  result.evidence = evidence;
  result.timings.end = ended;
  result.timings.duration = Number((ended - result.timings.start).toFixed(3));
  return result;
}

async function firstVisibleLocator(page, selectors, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const sel of selectors) {
      const loc = page.locator(sel).first();
      try {
        if ((await loc.count()) > 0 && (await loc.isVisible())) {
          return loc;
        }
      } catch {
        // continue trying selector list
      }
    }
    await page.waitForTimeout(180);
  }
  return null;
}

async function detectSelectorAny(page, selectors) {
  for (const sel of selectors) {
    try {
      if ((await page.locator(sel).count()) > 0) return true;
    } catch {
      // ignore invalid selector on runtime
    }
  }
  return false;
}

async function detectHumanVerification(page) {
  // Detect captcha / anti-bot verification pages (Cloudflare Turnstile, reCAPTCHA, etc).
  // We do NOT try to solve/bypass; we just return a clear status so the user can intervene.
  const selectors = [
    "iframe[src*='captcha']",
    "iframe[title*='captcha']",
    "div.g-recaptcha",
    "iframe[src*='challenges.cloudflare.com']",
    "iframe[src*='turnstile']",
    ".cf-turnstile",
    "text=/verifica\\s+que\\s+eres\\s+humano/i",
    "text=/verifica\\s+que\\s+eres\\s+una\\s+persona/i",
    "text=/verifica\\s+que\\s+eres\\s+un\\s+ser\\s+humano/i",
    "text=/cloudflare/i",
    "text=/turnstile/i",
    "text=/captcha/i",
  ];
  if (await detectSelectorAny(page, selectors)) return true;

  try {
    const title = await page.title();
    if (/captcha|cloudflare|turnstile/i.test(String(title || ""))) return true;
  } catch {}

  try {
    const url = page.url();
    if (/challenges\\.cloudflare\\.com/i.test(String(url || ""))) return true;
  } catch {}

  try {
    const frames = page.frames();
    for (const fr of frames) {
      const furl = String(fr.url() || "");
      if (/challenges\.cloudflare\.com|turnstile|captcha|recaptcha/i.test(furl)) return true;
    }
  } catch {}

  try {
    const bodyText = await page.evaluate(() =>
      String(document && document.body ? document.body.innerText || "" : "")
    );
    if (/verifica\s+que\s+eres\s+.*humano|verify\s+you\s+are\s+human|cloudflare|turnstile|captcha/i.test(bodyText)) {
      return true;
    }
  } catch {}

  return false;
}

function randInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

async function dismissInterruptions(page) {
  const closeSelectors = [
    "button[aria-label='Close']",
    "button[aria-label*='Cerrar']",
    "button:has-text('Close')",
    "button:has-text('Cerrar')",
    "button:has-text('Entendido')",
    "button:has-text('Aceptar')",
    "button:has-text('Accept')",
    "button:has-text('Got it')",
    "button:has-text('Not now')",
    "button:has-text('Ahora no')",
    "button:has-text('Continue')",
    "[data-testid='close-button']",
    "[data-testid='modal-close-button']",
  ];

  for (let round = 0; round < 3; round += 1) {
    for (const sel of closeSelectors) {
      try {
        const btn = page.locator(sel).first();
        if ((await btn.count()) > 0 && (await btn.isVisible())) {
          await btn.click({ force: true, timeout: 800 }).catch(() => {});
          await page.waitForTimeout(180);
        }
      } catch {
        // keep trying candidates
      }
    }
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(140);
  }
}

async function ensureChatSurfaceReady(page, cfg, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await dismissInterruptions(page);
    if (await detectSelectorAny(page, cfg.loginSelectors)) {
      return { ok: false, status: "login_required", input: null };
    }
    if (await detectHumanVerification(page)) {
      return { ok: false, status: "captcha_required", input: null };
    }
    const input = await firstVisibleLocator(page, cfg.inputSelectors, 1400);
    if (input) {
      return { ok: true, status: "ok", input };
    }
    await page.mouse.wheel(0, randInt(180, 420)).catch(() => {});
    await page.waitForTimeout(240);
  }
  return { ok: false, status: "selector_changed", input: null };
}

async function writePrompt(page, inputLocator, prompt) {
  await inputLocator.scrollIntoViewIfNeeded();
  await inputLocator.click({ force: true, delay: randInt(20, 70) });
  await page.keyboard.press("Control+A");
  await page.keyboard.press("Backspace");

  try {
    await page.keyboard.type(prompt, { delay: randInt(22, 48) });
    return;
  } catch {
    await inputLocator.fill(prompt);
  }
}

async function sendPrompt(page, cfg) {
  for (const sel of cfg.sendSelectors) {
    try {
      const btn = page.locator(sel).first();
      if ((await btn.count()) > 0 && (await btn.isVisible())) {
        await btn.click({ force: true, timeout: 1500, delay: randInt(20, 60) });
        return true;
      }
    } catch {
      // fallback to keyboard
    }
  }
  await page.keyboard.press("Enter");
  return true;
}

function normalizeText(raw) {
  return String(raw || "").replace(/\s+/g, " ").trim();
}

async function extractLastResponseText(page, selectors) {
  let best = "";
  for (const sel of selectors) {
    try {
      const count = await page.locator(sel).count();
      if (count < 1) continue;
      const last = page.locator(sel).nth(count - 1);
      const txt = normalizeText(await last.innerText());
      if (txt.length > best.length) best = txt;
    } catch {
      // keep trying selector candidates
    }
  }
  return best;
}

async function waitForFreshResponse(page, selectors, baseline, timeoutMs, minLen) {
  const deadline = Date.now() + timeoutMs;
  let stableHits = 0;
  let candidate = "";
  const needLen = Math.max(1, parseInt(String(minLen || 1), 10) || 1);

  while (Date.now() < deadline) {
    const latest = await extractLastResponseText(page, selectors);
    if (latest && latest !== baseline && latest.length >= needLen) {
      if (latest === candidate) {
        stableHits += 1;
      } else {
        candidate = latest;
        stableHits = 1;
      }
      if (stableHits >= 2) {
        return latest;
      }
    }
    await page.waitForTimeout(900);
  }

  return "";
}

function screenshotPath(site) {
  const outDir = path.join(os.homedir(), ".openclaw", "logs", "web_ask_screens");
  fs.mkdirSync(outDir, { recursive: true });
  return path.join(outDir, `${site}_${Date.now()}.png`);
}

async function safeScreenshot(page, site) {
  const shot = screenshotPath(site);
  try {
    await page.screenshot({ path: shot, fullPage: true });
    if (fs.existsSync(shot)) return { path: shot, error: "" };
    return { path: "", error: "screenshot_missing_after_write" };
  } catch (err) {
    return { path: "", error: String(err && err.message ? err.message : err).slice(0, 400) };
  }
}

function clearSingletonArtifacts(userDataDir) {
  const targets = [
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
    "lockfile",
    "LOCK",
  ];
  for (const name of targets) {
    const p = path.join(userDataDir, name);
    try {
      fs.rmSync(p, { force: true, recursive: true });
    } catch {
      // ignore cleanup errors
    }
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const site = String(args.site || "").trim().toLowerCase();
  const prompt = String(args.prompt || "").trim();
  const profileDir = String(args["profile-dir"] || "Default");
  const userDataDir = String(args["user-data-dir"] || path.join(os.homedir(), ".config", "google-chrome"));
  const timeoutMs = Math.max(5000, parseInt(String(args["timeout-ms"] || "60000"), 10) || 60000);
  const headless = String(args.headless || "false").toLowerCase() === "true";
  const threadFile = String(args["thread-file"] || "").trim();
  const followup = String(args.followup || "").trim();
  const followup2 = String(args.followup2 || "").trim();
  const followupsJson = String(args["followups-json"] || "").trim();

  const startedAt = nowEpoch();
  const result = mkResult(site, startedAt);
  const cfg = SITE_CONFIG[site];
  if (!cfg) {
    console.log(JSON.stringify(finish(result, "unsupported_site", false), null, 2));
    process.exit(2);
  }
  if (!prompt) {
    console.log(JSON.stringify(finish(result, "missing_prompt", false), null, 2));
    process.exit(2);
  }

  let context;
  clearSingletonArtifacts(userDataDir);
  try {
    context = await chromium.launchPersistentContext(userDataDir, {
      channel: "chrome",
      headless,
      viewport: null,
      args: [
        `--profile-directory=${profileDir}`,
        "--no-first-run",
        "--no-default-browser-check",
      ],
    });
  } catch (err) {
    const raw = String(err && err.message ? err.message : err);
    const lower = raw.toLowerCase();
    const status =
      lower.includes("lock") || lower.includes("singleton")
        ? "profile_locked"
        : "launch_failed";
    console.log(JSON.stringify(finish(result, status, false, "", raw.slice(0, 500)), null, 2));
    process.exit(3);
  }

  try {
    const page = context.pages()[0] || (await context.newPage());
    let targetUrl = cfg.url;
    if (threadFile && site === "chatgpt") {
      try {
        if (fs.existsSync(threadFile)) {
          const saved = String(fs.readFileSync(threadFile, "utf-8") || "").trim();
          if (/^https:\/\/chatgpt\.com\/c\//.test(saved)) targetUrl = saved;
        }
      } catch {
        // non-fatal
      }
    }

    const prompts = [prompt];
    if (followupsJson) {
      try {
        const parsed = JSON.parse(followupsJson);
        if (Array.isArray(parsed)) {
          for (const item of parsed) {
            const clean = String(item || "").trim();
            if (clean) prompts.push(clean);
          }
        }
      } catch {
        // fallback to legacy args
      }
    }
    if (prompts.length === 1 && followup) prompts.push(followup);
    if (prompts.length <= 2 && followup2) prompts.push(followup2);

    await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    await page.waitForTimeout(900);

    const turns = [];
    for (let turnIndex = 0; turnIndex < prompts.length; turnIndex += 1) {
      const turnPrompt = prompts[turnIndex];
      const ready = await ensureChatSurfaceReady(page, cfg, Math.min(timeoutMs, 12000));
      if (!ready.ok || !ready.input) {
        const cap = await safeScreenshot(page, site);
        result.turns = turns;
        console.log(JSON.stringify(finish(result, ready.status || "selector_changed", false, "", cap.path || cap.error), null, 2));
        return;
      }

      const baseline = await extractLastResponseText(page, cfg.responseSelectors);
      await writePrompt(page, ready.input, turnPrompt);
      await sendPrompt(page, cfg);

      const responseText = await waitForFreshResponse(
        page,
        cfg.responseSelectors,
        baseline,
        timeoutMs,
        cfg.minResponseLen || 1
      );
      if (!responseText) {
        const cap = await safeScreenshot(page, site);
        let status = "timeout";
        if (await detectSelectorAny(page, cfg.loginSelectors)) status = "login_required";
        else if (await detectHumanVerification(page)) status = "captcha_required";
        result.turns = turns;
        console.log(JSON.stringify(finish(result, status, false, "", cap.path || cap.error), null, 2));
        return;
      }

      turns.push({ prompt: turnPrompt, text: responseText });
      await page.waitForTimeout(randInt(300, 900));

      if (threadFile && site === "chatgpt" && turnIndex === 0) {
        try {
          const current = String(page.url() || "").trim();
          if (/^https:\/\/chatgpt\.com\/c\//.test(current)) {
            fs.mkdirSync(path.dirname(threadFile), { recursive: true });
            fs.writeFileSync(threadFile, current, "utf-8");
          }
        } catch {
          // ignore thread save failures
        }
      }
    }

    const lastText = turns.length ? String(turns[turns.length - 1].text || "") : "";
    result.turns = turns;
    console.log(JSON.stringify(finish(result, "ok", true, lastText), null, 2));
  } catch (err) {
    const raw = String(err && err.message ? err.message : err);
    const status = /timeout/i.test(raw) ? "timeout" : "blocked";
    let evidence = raw.slice(0, 500);
    try {
      const p = context.pages()[0];
      if (p) {
        const cap = await safeScreenshot(p, site);
        evidence = cap.path || cap.error || evidence;
      }
    } catch {}
    console.log(JSON.stringify(finish(result, status, false, "", evidence), null, 2));
  } finally {
    await context.close().catch(() => {});
  }
}

main().catch((err) => {
  const fallback = {
    ok: false,
    text: "",
    status: "internal_error",
    evidence: String(err && err.message ? err.message : err),
    timings: {
      start: nowEpoch(),
      end: nowEpoch(),
      duration: 0,
    },
  };
  console.log(JSON.stringify(fallback, null, 2));
  process.exit(1);
});
