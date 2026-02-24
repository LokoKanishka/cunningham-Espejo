#!/usr/bin/env node
/* Deterministic DC model verifier (API-based).
   Checks /api/models and /api/chat (non-stream) for 3-model set. */

const BASE = process.env.DC_BASE_URL || "http://127.0.0.1:8787";

const EXPECTED = [
  { id: "openai-codex/gpt-5.1-codex-mini", backend: "cloud" },
  { id: "dolphin-mixtral:latest", backend: "local" },
  { id: "huihui_ai/qwq-abliterated:32b-Q6_K", backend: "local" },
];

async function jget(path) {
  const r = await fetch(`${BASE}${path}`, { headers: { accept: "application/json" } });
  const t = await r.text();
  let j;
  try {
    j = JSON.parse(t);
  } catch {
    throw new Error(`bad_json ${path}: ${t.slice(0, 200)}`);
  }
  if (!r.ok) throw new Error(`http_${r.status} ${path}: ${t.slice(0, 220)}`);
  return j;
}

async function jpost(path, payload) {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(payload),
  });
  const t = await r.text();
  let j;
  try {
    j = JSON.parse(t);
  } catch {
    throw new Error(`bad_json ${path}: ${t.slice(0, 200)}`);
  }
  if (!r.ok) throw new Error(`http_${r.status} ${path}: ${t.slice(0, 220)}`);
  return j;
}

function norm(s) {
  return String(s || "").trim();
}

async function main() {
  const m = await jget("/api/models");
  const gotIds = (Array.isArray(m.models) ? m.models : []).map((x) => norm(x.id)).filter(Boolean).sort();
  const expIds = EXPECTED.map((x) => x.id).sort();

  if (JSON.stringify(gotIds) !== JSON.stringify(expIds)) {
    throw new Error(`model_list_mismatch expected=${JSON.stringify(expIds)} got=${JSON.stringify(gotIds)}`);
  }

  // Quick chat checks (non-stream) — deterministic
  for (const it of EXPECTED) {
    const payload = {
      message: "hola",
      model: it.id,
      model_backend: it.backend,
      history: [],
      mode: "operativo",
      session_id: "verify_dc_models",
      allowed_tools: [], // keep it simple
      attachments: [],
    };
    const out = await jpost("/api/chat", payload);
    const reply = norm(out.reply || "");
    if (!reply) {
      throw new Error(`model_failed model=${it.id} backend=${it.backend} reply=""`);
    }
  }

  console.log(`DC_UI_MODELS_OK base=${BASE} models=3`);
}

main().catch((e) => {
  console.error("DC_UI_MODELS_FAIL:", e && (e.stack || e.message || String(e)));
  process.exit(1);
});
