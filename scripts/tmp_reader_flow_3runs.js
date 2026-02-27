const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:8787';

function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
function norm(s){ return String(s||'').replace(/\s+/g,' ').trim().toLowerCase(); }
async function waitUntil(fn, {timeoutMs=30000, stepMs=200, label='cond'}={}){
  const t0 = Date.now();
  let lastErr = '';
  while(Date.now()-t0 < timeoutMs){
    try{ const v = await fn(); if(v) return v; } catch(e){ lastErr = String(e && e.message || e); }
    await sleep(stepMs);
  }
  throw new Error(`timeout:${label}${lastErr?` last=${lastErr}`:''}`);
}

async function voiceState(ctx){
  const r = await ctx.request.get(`${BASE}/api/voice`);
  if(!r.ok()) return {};
  return await r.json();
}

async function timeline(page){
  return await page.$$eval('.msg', ns => ns.map(n => ({
    role: (n.classList.contains('user') ? 'user' : (n.classList.contains('assistant') ? 'assistant' : 'other')),
    text: (n.innerText || '').trim(),
  })));
}

async function send(page, text){
  await waitUntil(async()=>!(await page.$eval('#send', b=>b.disabled)), {timeoutMs:90000,label:'send_enabled'});
  await page.fill('#input', text);
  await page.click('#send');
}

async function assistantTexts(page){
  const arr = await page.$$eval('.msg.assistant', ns => ns.map(n => (n.innerText||'').trim()));
  return arr.filter(Boolean);
}

async function sendAndWaitAssistant(page, text, predicate = null, timeoutMs = 25000){
  await send(page, text);
  const textNorm = norm(text);
  return await waitUntil(async()=>{
    const now = await timeline(page);
    let userIdx = -1;
    for(let i=now.length-1;i>=0;i--){
      const m = now[i];
      if(m.role !== 'user') continue;
      const u = norm(m.text);
      if(u === textNorm || u.includes(textNorm) || textNorm.includes(u)){
        userIdx = i;
        break;
      }
    }
    if(userIdx < 0) return false;
    const assistantNow = now.filter(m => m.role === 'assistant').map(m => m.text).filter(Boolean);
    const fresh = [];
    for(let i=userIdx+1;i<now.length;i++){
      const m = now[i];
      if(m.role !== 'assistant') continue;
      const t = String(m.text || '').trim();
      if(!t) continue;
      fresh.push(t);
    }
    if(!fresh.length) return false;
    if (typeof predicate === 'function') {
      for(let i=fresh.length-1;i>=0;i--){
        const msg = fresh[i];
        if(predicate(msg, assistantNow)) return msg;
      }
      return false;
    }
    return fresh[fresh.length-1];
  }, {timeoutMs, stepMs:180, label:`assistant_after_${text.slice(0,20)}`});
}

function extractBlockNum(t){ const m = /bloque\s*(\d+)\s*\//i.exec(String(t||'')); return m ? Number(m[1]) : 0; }
function hasReaderDuplicate(messages){
  const byBlock = new Map();
  for(const t of messages){
    const n = extractBlockNum(t);
    if(!n) continue;
    const arr = byBlock.get(n) || [];
    arr.push(t);
    byBlock.set(n, arr);
  }
  for(const arr of byBlock.values()){
    if(arr.length < 2) continue;
    for(let i=0;i<arr.length;i++){
      for(let j=i+1;j<arr.length;j++){
        const a = norm(arr[i]);
        const b = norm(arr[j]);
        if(!a || !b) continue;
        if(a===b) return true;
        if((a.length>80 && b.length>80) && (a.includes(b.slice(0,120)) || b.includes(a.slice(0,120)))) return true;
      }
    }
  }
  return false;
}
function blockKeyword(text){
  const words = String(text||'').toLowerCase().replace(/[^a-záéíóúñü0-9\s]/gi,' ').split(/\s+/).filter(w=>w.length>=6);
  const stop = new Set(['bloque','lectura','iniciada','primer','borrador','indice','texto','autopiloto','lenguaje']);
  for(const w of words){ if(!stop.has(w)) return w; }
  return words[0] || 'lenguaje';
}

async function ensureVoiceOn(page){
  const txt = await page.locator('#voiceToggleText').innerText();
  if(/off/i.test(txt)){ await page.click('#voiceToggle'); await sleep(500); }
}
async function ensureSttChatOff(page){
  const txt = await page.locator('#sttChatToggleText').innerText();
  if(/on/i.test(txt)){ await page.click('#sttChatToggle'); await sleep(350); }
}

async function runRound(page, ctx, idx){
  const out = { round: idx, ok:false, duplicate:false, ttsStart:false, pauseOk:false, stopOk:false, commentOk:false, continueOk:false, detail:[] };
  await page.click('#newSession');
  await sleep(700);

  await sendAndWaitAssistant(page, 'biblioteca', (last)=>/biblioteca/i.test(last), 60000);

  let firstBlock = '';
  for(let i=0;i<20;i++){
    const rep = await sendAndWaitAssistant(
      page,
      'leer libro 1',
      (last)=>/lectura iniciada|ya estoy leyendo|bloque\s*1\s*\//i.test(last),
      30000,
    );
    if(!firstBlock && /bloque\s*1\s*\//i.test(rep)) firstBlock = rep;
    await sleep(130);
  }
  if(!firstBlock){
    firstBlock = await waitUntil(async()=>{
      const a = await assistantTexts(page);
      return a.find(t=>/bloque\s*1\s*\//i.test(t)) || false;
    }, {timeoutMs:30000,label:'block1'});
  }

  try{
    await waitUntil(async()=>{ const st = await voiceState(ctx); return !!st.tts_playing || Number(st.tts_playing_stream_id||0)>0 || Number(st?.last_status?.stream_id||0)>0; }, {timeoutMs:15000,label:'tts_start'});
    out.ttsStart = true;
  } catch(e){ out.detail.push(`tts_not_started:${String(e.message||e)}`); }

  await sleep(900);
  const aNow = await assistantTexts(page);
  out.duplicate = hasReaderDuplicate(aNow);
  if(out.duplicate) out.detail.push('duplicate_blocks_detected');

  const tPauseStart = Date.now();
  const pauseReply = await sendAndWaitAssistant(page, 'pausa lectura', (last)=>norm(last)==='si como seguimos?', 30000);
  if(norm(pauseReply)==='si como seguimos?') out.pauseOk = true; else out.detail.push(`pause_reply_unexpected:${pauseReply}`);
  try{ await waitUntil(async()=>{ const st=await voiceState(ctx); return !st.tts_playing; }, {timeoutMs:5000,label:'tts_stop_after_pause'});} catch{ out.detail.push('tts_not_stopped_fast_after_pause'); }
  out.detail.push(`pause_latency_ms=${Date.now()-tPauseStart}`);

  const commentReply = await sendAndWaitAssistant(
    page,
    'de que habla este bloque?',
    (last)=>last.length > 24 && norm(last) !== 'si como seguimos?' && !/ya estoy leyendo/i.test(last),
    45000,
  );
  const kw = blockKeyword(firstBlock);
  if(norm(commentReply).includes(norm(kw)) || /bloque|habla|trata|texto|lenguaje/i.test(commentReply)) out.commentOk=true; else out.detail.push(`comment_missing_kw:${kw}`);

  const contReply = await sendAndWaitAssistant(page, `entonces segui desde ${kw}`, (last)=>/retomo desde|bloque\s*\d+\s*\//i.test(last), 45000);
  out.continueOk = !!contReply;
  try{ await waitUntil(async()=>{ const st=await voiceState(ctx); return !!st.tts_playing || Number(st.tts_playing_stream_id||0)>0; }, {timeoutMs:10000,label:'tts_restart'});} catch{ out.detail.push('tts_not_restarted_after_continue'); }

  await sleep(1800);
  let stopReply = '';
  try {
    stopReply = await sendAndWaitAssistant(page, 'detenete', (last)=>norm(last)==='detenida', 30000);
  } catch {
    // Retry once in case the first click landed while UI was transitioning.
    stopReply = await sendAndWaitAssistant(page, 'detenete', (last)=>norm(last)==='detenida', 30000);
  }
  if(norm(stopReply)==='detenida') out.stopOk=true; else out.detail.push(`stop_reply_unexpected:${stopReply}`);
  try{ await waitUntil(async()=>{ const st=await voiceState(ctx); return !st.tts_playing; }, {timeoutMs:2500,label:'tts_stop_after_detenete'});} catch{ out.detail.push('tts_not_stopped_fast_after_detenete'); }

  out.ok = out.ttsStart && !out.duplicate && out.pauseOk && out.stopOk && out.commentOk && out.continueOk;
  return out;
}

(async()=>{
  const browser = await chromium.launch({ headless:false, executablePath:'/usr/bin/google-chrome', args:['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport:{width:1440,height:920} });
  const page = await ctx.newPage();
  const report = { runs: [] };
  try{
    await page.goto(BASE, {waitUntil:'domcontentloaded', timeout:45000});
    await page.waitForSelector('#input', {timeout:20000});
    await ensureVoiceOn(page);
    await ensureSttChatOff(page);

    for(let i=1;i<=3;i++){
      let r;
      try { r = await runRound(page, ctx, i); }
      catch(e){ r = { round:i, ok:false, duplicate:false, ttsStart:false, pauseOk:false, stopOk:false, commentOk:false, continueOk:false, detail:[`run_exception:${String(e&&e.message||e)}`] }; }
      report.runs.push(r);
      if(!r.ok) break;
      await sleep(600);
    }
    report.ok = report.runs.length===3 && report.runs.every(r=>r.ok);
    console.log(JSON.stringify(report, null, 2));
    if(!report.ok) process.exitCode = 2;
  } finally {
    await browser.close();
  }
})();
