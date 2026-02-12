#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env.n8n.local ]; then
  set -a
  . ./.env.n8n.local
  set +a
fi

: "${N8N_BASE_URL:?Missing N8N_BASE_URL}"
: "${N8N_EMAIL:?Missing N8N_EMAIL}"
: "${N8N_PASSWORD:?Missing N8N_PASSWORD}"

node <<'JS'
const { chromium } = require('playwright');

(async () => {
  const base = process.env.N8N_BASE_URL;
  const email = process.env.N8N_EMAIL;
  const pass = process.env.N8N_PASSWORD;

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  await page.goto(`${base}/signin`, { waitUntil: 'domcontentloaded' });
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', pass);
  await Promise.all([
    page.waitForURL(/\/home\/workflows/, { timeout: 15000 }),
    page.click('button:has-text("Sign in"), button:has-text("Iniciar sesión")')
  ]);

  await page.goto(`${base}/home/workflows`, { waitUntil: 'networkidle' });
  const wfCandidate = page.locator('text=/Prueba_Manos|Test_Manos/i').first();
  try {
    await wfCandidate.waitFor({ state: 'visible', timeout: 30000 });
  } catch (e) {
    await page.screenshot({ path: 'output_playwright_n8n_not_found.png', fullPage: true });
    throw new Error('No se encontró workflow Prueba_Manos/Test_Manos en la lista');
  }
  await wfCandidate.click();
  await page.waitForLoadState('networkidle');

  const runButton = page.locator('[data-test-id^="execute-workflow-button"]').first();
  await runButton.waitFor({ state: 'visible', timeout: 30000 });
  await runButton.click({ force: true });

  await page.waitForTimeout(4000);
  await page.goto(`${base}/home/executions`, { waitUntil: 'networkidle' });
  const firstRow = page.locator('table tbody tr, [data-test-id="execution-list-item"]').first();

  let statusText = '';
  if (await firstRow.count()) {
    statusText = (await firstRow.innerText()).replace(/\s+/g, ' ').trim();
    await firstRow.click();
    await page.waitForTimeout(1500);
  } else {
    statusText = 'No execution row found';
  }

  let errorText = '';
  const errorNode = page.locator('text=/error|failed|fallo|fallida/i').first();
  if (await errorNode.count()) {
    errorText = (await errorNode.innerText()).replace(/\s+/g, ' ').trim();
  }

  console.log(`STATUS_ROW=${statusText}`);
  console.log(`ERROR_TEXT=${errorText || 'none'}`);
  await browser.close();
})().catch((err) => {
  console.error('RUN_ERROR=' + (err && err.message ? err.message : String(err)));
  process.exit(1);
});
JS
