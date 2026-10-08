// Phase 3 browser check: consumers on Integrate (approved, seen or both), reading callers,
// chargeback on Tokenomics, the Programme health page with a search gap and the CSV,
// and starting a registration from a certified agent (with a probe certified agent).
// Probe data is removed at the end; the search-log row is removed by the caller with sqlite.
import { chromium } from 'playwright'
import fs from 'node:fs'
const SP = process.argv[2], B = 'http://localhost:5174', API = 'http://127.0.0.1:8002/api/v1'
const TOKEN = fs.readFileSync(`${SP}/ar-token`, 'utf8').trim()
const H = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }
const R = []; const ok = (n, c, e = '') => R.push([c ? 'PASS' : 'FAIL', n, String(e ?? '').slice(0, 300)])
const j = async (method, path, body) => { const r = await fetch(`${API}${path}`, { method, headers: H, body: body ? JSON.stringify(body) : undefined }); return { status: r.status, body: await r.json().catch(() => null) } }
const cleanup = []
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
await ctx.addInitScript(([k, t]) => localStorage.setItem(k, t), ['airegistry_token', TOKEN])
const page = await ctx.newPage()
const errs = []
page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 160)) })
page.on('pageerror', e => errs.push('pageerror ' + String(e).slice(0, 160)))
const text = async sel => (await page.textContent(sel).catch(() => '')) || ''
const GAP = 'zzq probe payroll reconciler'

try {
  const dot = (await j('GET', '/agents/?limit=100')).body.data.find(a => a.name === 'Digital Onboarding Test')
  // Integrate → Consumers, and reading callers from Phoenix
  await page.goto(`${B}/agents/${dot.id}?tab=integrate`); await page.waitForSelector('[data-testid=consumers]', { timeout: 30000 })
  ok('Integrate shows the consumers with the span attribute to set', /consumer\.team/.test(await text('[data-testid=consumers]')))
  await page.click('[data-testid=observe-consumers]')
  await page.waitForSelector('[data-testid=consumers] [role=status]', { timeout: 120000 })
  const status = await text('[data-testid=consumers] [role=status]')
  ok('Read callers now reports what happened', /Callers read|Not read/.test(status), status)
  const runs = (await j('GET', '/jobs/runs?job=consumer_observation&limit=1')).body
  ok('the read is logged as a consumer observation run', JSON.stringify(runs || {}).includes('consumer_observation'), JSON.stringify(runs).slice(0, 200))

  // Tokenomics → Chargeback
  await page.goto(`${B}/agents/${dot.id}?tab=tokenomics`); await page.waitForSelector('[data-testid=chargeback]', { timeout: 30000 })
  ok('Tokenomics shows the chargeback for the month', /Token cost in \d{4}-\d{2}/.test(await text('[data-testid=chargeback]')), await text('[data-testid=chargeback]'))

  // A search that finds nothing becomes a search gap
  await page.goto(`${B}/agents`); await page.waitForSelector('input[placeholder]', { timeout: 30000 })
  await page.locator('input[placeholder]').first().fill(GAP); await page.waitForTimeout(1500)
  await page.goto(`${B}/programme`); await page.waitForSelector('[data-testid=programme-health]', { timeout: 30000 })
  ok('Programme health shows the four figures', await page.locator('[data-testid^=tile-]').count() === 4)
  ok('the empty search is listed as a search gap', (await text('[data-testid=search-gaps]')).includes(GAP), await text('[data-testid=search-gaps]'))
  ok('reuse by unit is shown', await page.locator('[data-testid=reuse-by-unit] tbody tr').count() >= 1)
  const dl = page.waitForEvent('download', { timeout: 15000 }).catch(() => null)
  await page.click('[data-testid=chargeback-csv]')
  const file = await dl
  const csv = file ? fs.readFileSync(await file.path(), 'utf8') : ''
  ok('the chargeback CSV downloads with its header', csv.startsWith('month,agent,owner unit'), csv.slice(0, 80))
  await page.screenshot({ path: `${SP}/shots/p3-programme.png`, fullPage: true })

  // Start from a certified agent: make a probe agent certified, then pick it in the form
  const a = await j('POST', '/agents/', { name: 'Probe Certified Template', dept: 'dept-finance', owner: 'Probe Team', ai_type: 'Autonomous Agent',
    description: 'Temporary certified probe agent used as a template in the check', stage: 'Production',
    stage_reason: 'Probe agent created live for the browser check only', capabilities: ['Probe capability one'], sla: '99.0%' })
  const pid = a.body?.id
  cleanup.push(() => j('DELETE', `/agents/${pid}`))
  for (const g of ['arb', 'security', 'dp']) await j('PUT', `/agents/${pid}/governance/${g}`, { status: 'Approved' })
  const cert = (await j('GET', '/agents/?certified=true&limit=100')).body.data.some(x => x.id === pid)
  ok('the probe agent is certified for reuse', cert)
  await page.goto(`${B}/agents`); await page.getByRole('button', { name: /Register/ }).first().click()
  await page.waitForSelector('[data-testid=certified-select]', { timeout: 15000 })
  await page.selectOption('[data-testid=certified-select]', pid)
  await page.waitForTimeout(1200)
  const caps = await page.locator('textarea').evaluateAll(els => els.map(e => e.value).join(' | '))
  ok('picking it fills the empty fields from its contract', caps.includes('Probe capability one'), caps.slice(0, 200))
  await page.keyboard.press('Escape'); await page.locator('button', { hasText: '×' }).first().click().catch(() => {})
} catch (e) {
  ok('the check ran to the end', false, String(e).slice(0, 300))
} finally {
  for (const c of cleanup.reverse()) await c().catch(() => {})
}
ok('probe agent removed', !(await j('GET', '/agents/?limit=100')).body.data.some(a => a.name === 'Probe Certified Template'))
ok('no console errors', errs.length === 0, errs.join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
