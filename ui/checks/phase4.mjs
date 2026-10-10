// Phase 4 browser check: declared value with a method, the finance check, measured outcomes,
// usage typed in for an agent without tracing, the model what-if, Business Impact value and
// spend with the scorecard PDF, and the cost settings. Uses a probe agent, removed at the end.
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

try {
  const before = (await j('GET', '/value/settings')).body.buildCostCents
  cleanup.push(() => j('PUT', '/value/settings', { buildCostCents: before }))
  const a = await j('POST', '/agents/', { name: 'Probe Phase Four', dept: 'dept-finance', owner: 'Probe Team', ai_type: 'Autonomous Agent',
    description: 'Temporary probe agent for the Phase 4 browser check', stage: 'Ideation', stage_reason: '' })
  const id = a.body?.id
  ok('probe agent created', !!id, JSON.stringify(a.body).slice(0, 200))
  cleanup.push(() => j('DELETE', `/agents/${id}`))

  // Usage typed in on Tokenomics (no tracing link)
  await page.goto(`${B}/agents/${id}?tab=tokenomics`); await page.waitForSelector('[data-testid=manual-usage]', { timeout: 30000 })
  await page.fill('[data-testid=manual-model]', 'gpt-4o'); await page.fill('[data-testid=manual-calls]', '25')
  await page.locator('[data-testid=manual-usage] input[type=number]').nth(1).fill('2000000')
  await page.click('[data-testid=manual-add]'); await page.waitForSelector('[data-testid=manual-row]', { timeout: 15000 })
  const econ = (await j('GET', `/agents/${id}/economics`)).body
  ok('typed-in usage gives a cost with the source "manual"', econ.tokenSource === 'manual' && econ.tokenCostCents > 0, `${econ.tokenSource} ${econ.tokenCostCents}`)

  // Value with a method, then the finance check
  await page.goto(`${B}/agents/${id}?tab=revenue`); await page.waitForSelector('[data-testid=value-panel]', { timeout: 30000 })
  await page.click('[data-testid=declare-value]')
  await page.locator('[data-testid=value-panel] label', { hasText: 'Cost avoidance' }).locator('input').check()
  await page.fill('[data-testid=value-amount]', '2000'); await page.fill('[data-testid=value-basis]', 'Probe: two contractor days a month are not bought')
  await page.click('[data-testid=save-value]'); await page.waitForTimeout(1000)
  ok('the declared value shows as declared, with its method', /Declared by the owner/.test(await text('[data-testid=value-state]')) && /Cost avoidance/.test(await text('[data-testid=value-panel]')))
  await page.click('[data-testid=attest-value]'); await page.click('[data-testid=attest-adjust]')
  await page.fill('[data-testid=attest-amount]', '1500'); await page.fill('[data-testid=attest-note]', 'Probe check: only 1.5 days are really saved')
  await page.click('[data-testid=save-attest]'); await page.waitForTimeout(1200)
  ok('the finance check adjusts the value used', /Adjusted by finance/.test(await text('[data-testid=value-state]')) && (await j('GET', `/agents/${id}/economics`)).body.valueCents === 150000)

  // Measured outcomes and the what-if
  await page.fill('[data-testid=outcome-name]', 'probe item matched'); await page.fill('[data-testid=outcome-count]', '40')
  await page.click('[data-testid=add-outcome]'); await page.waitForSelector('[data-testid=outcome-row]', { timeout: 15000 })
  ok('the outcome appears with a cost per outcome', /probe item matched/.test(await text('[data-testid=outcome-row]')) && /\$/.test(await text('[data-testid=outcome-row]')), await text('[data-testid=outcome-row]'))
  // The what-if sits on the Tokenomics tab, with the cost panels.
  await page.goto(`${B}/agents/${id}?tab=tokenomics`); await page.waitForSelector('[data-testid=model-whatif]', { timeout: 30000 })
  ok('the what-if prices the same tokens at other models and says quality was not compared', /quality was not compared/.test(await text('[data-testid=model-whatif]')))
  await page.screenshot({ path: `${SP}/shots/p4-revenue.png`, fullPage: true })

  // Business Impact: value and spend, scorecard
  await page.goto(`${B}/business`); await page.waitForSelector('[data-testid=value-spend]', { timeout: 30000 })
  await page.waitForFunction(() => (document.querySelector('[data-testid=scenario]')?.textContent || '').includes('Probe Phase Four'), null, { timeout: 20000 }).catch(() => {})
  ok('the scenario lists agents not yet in Production', (await text('[data-testid=scenario]')).includes('Probe Phase Four'))
  const dl = page.waitForEvent('download', { timeout: 20000 }).catch(() => null)
  await page.click('[data-testid=scorecard-pdf]')
  const file = await dl
  const head = file ? fs.readFileSync(await file.path()).subarray(0, 8).toString() : ''
  ok('the scorecard downloads as a PDF', head.startsWith('%PDF-1.4'), head)

  // Settings: cost settings and the build cost
  await page.goto(`${B}/settings`); await page.waitForSelector('[data-testid=cost-settings]', { timeout: 30000 })
  ok('cost settings say whether Azure Cost Management is set up', /set up|not set up/.test(await text('[data-testid=azure-state]')), await text('[data-testid=azure-state]'))
  await page.fill('[data-testid=build-cost]', '40000'); await page.locator('[data-testid=cost-settings] button', { hasText: 'Save' }).last().click()
  await page.waitForFunction(() => /Reuse savings now count/.test(document.querySelector('[data-testid=cost-settings] [role=status]')?.textContent || ''), null, { timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(1500)
  ok('the agreed build cost is saved', (await j('GET', '/value/settings')).body.buildCostCents === 4000000)
  const health = (await j('GET', '/portfolio/health')).body
  ok('programme health values the builds avoided', health.reuseSavings.buildCostCents === 4000000)
} catch (e) {
  ok('the check ran to the end', false, String(e).slice(0, 300))
} finally {
  for (const c of cleanup.reverse()) await c().catch(() => {})
}
ok('probe agent removed', !(await j('GET', '/agents/?limit=100')).body.data.some(a => a.name === 'Probe Phase Four'))
ok('no console errors', errs.length === 0, errs.join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
