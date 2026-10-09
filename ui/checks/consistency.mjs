// Consistency check: one place for each action and one rule for each figure.
// Governance statuses are read-only links, cleared follows the governance rules, the Edit window does not change
// owner or value, Executive and Business Impact agree on value, Platform links to the graph page, and /playground
// lands on the Integrate tab.
// Creates one probe agent and deletes it at the end.
import { chromium } from 'playwright'
import fs from 'node:fs'
const SP = process.argv[2], B = 'http://localhost:5174', API = 'http://127.0.0.1:8002/api/v1'
const TOKEN = fs.readFileSync(`${SP}/ar-token`, 'utf8').trim()
const H = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json', 'X-Include-Demo': '1' }
const j = async (m, p, b) => { const r = await fetch(API + p, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined }); return { status: r.status, body: await r.json().catch(() => null) } }
const R = []; const ok = (n, c, e = '') => R.push([c ? 'PASS' : 'FAIL', n, String(e ?? '').slice(0, 300)])
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await ctx.addInitScript(([k, t]) => localStorage.setItem(k, t), ['airegistry_token', TOKEN])
const page = await ctx.newPage()
const errs = []; page.on('pageerror', e => errs.push(String(e).slice(0, 160)))
const text = async sel => ((await page.textContent(sel).catch(() => '')) || '').replace(/\s+/g, ' ')
const money = s => { const m = /\$([\d.,]+)([KM]?)/.exec(s || ''); return m ? Number(m[1].replace(/,/g, '')) * (m[2] === 'M' ? 1e6 : m[2] === 'K' ? 1e3 : 1) : null }
let probe = null
try {
  const a = await j('POST', '/agents/', { name: 'Probe Consistency', dept: 'dept-finance', owner: 'Probe Team', ai_type: 'Autonomous Agent',
    description: 'Temporary probe agent for the consistency browser check', stage: 'Ideation', stage_reason: '' })
  probe = a.body?.id
  ok('probe agent created', !!probe, JSON.stringify(a.body).slice(0, 200))

  // Governance: summary from the server, read-only statuses
  // The browser hides the demo agents by default, so the comparison figure is read without them too.
  const sum = await (await fetch(API + '/governance/summary', { headers: { Authorization: `Bearer ${TOKEN}` } })).json()
  await page.goto(`${B}/governance`); await page.waitForSelector('[data-testid=tile-cleared]', { timeout: 30000 }); await page.waitForTimeout(1500)
  ok('the cleared tile shows the server figure', (await text('[data-testid=tile-cleared]')).trim() === String(sum.cleared), `${await text('[data-testid=tile-cleared]')} vs ${sum.cleared}`)
  ok('no review dropdown and no Register button on Governance', await page.locator('table select').count() === 0 && !/Register agent/.test(await text('main')))

  // Edit window: owner and value are not editable there
  await page.goto(`${B}/agents`); await page.waitForSelector('h3', { timeout: 30000 }); await page.waitForTimeout(800)
  await page.click('[aria-label="Edit Probe Consistency"]'); await page.waitForSelector('[data-testid=edit-agent-form]', { timeout: 10000 })
  ok('the Edit window links to Overview for the owner and to Revenue & Expenditure for the value',
    await page.locator('#edit-owner, #edit-value').count() === 0 && /Change on Overview/.test(await text('[data-testid=edit-owner]')) && /Declare on Revenue/.test(await text('[data-testid=edit-value]')))
  await page.keyboard.press('Escape'); await page.locator('[data-testid=edit-agent-form] button', { hasText: 'Cancel' }).click()

  // Executive and Business Impact agree on the value of all stages
  await page.goto(`${B}/`); await page.waitForSelector('[data-testid=user-chip]', { timeout: 30000 }); await page.waitForTimeout(3000)
  const exec = money((/Value \/ mo, all stages[^$]*(\$[\d.,]+[KM]?)/i.exec(await text('main')) || [])[1])
  await page.goto(`${B}/business`); await page.waitForSelector('[data-testid=bu-kpis]', { timeout: 30000 }); await page.waitForTimeout(2500)
  const biz = money((/Value \/ month[^$]*(\$[\d.,]+[KM]?)/i.exec(await text('[data-testid=bu-kpis]')) || [])[1])
  ok('Executive and Business Impact show the same value for all stages', exec !== null && exec === biz, `${exec} vs ${biz}`)

  // Platform and Playground
  await page.goto(`${B}/platform`); await page.waitForSelector('[data-testid=to-dependencies]', { timeout: 30000 })
  ok('Platform links to All Agents Graph instead of drawing the call graph', await page.locator('canvas').count() === 0)
  ok('the menu has no Playground entry', await page.locator('nav a', { hasText: 'Playground' }).count() === 0)
  await page.goto(`${B}/playground?agent=${probe}`); await page.waitForTimeout(2500)
  ok('/playground lands on the Integrate tab of that agent', page.url().includes(`/agents/${probe}?tab=integrate`), page.url())

} catch (e) {
  ok('the check ran to the end', false, String(e).slice(0, 300))
} finally {
  if (probe) { await j('POST', `/agents/${probe}/unarchive`); const d = await j('DELETE', `/agents/${probe}`); ok('probe agent removed', d.status < 300, String(d.status)) }
}
ok('no page errors', errs.length === 0, errs.slice(0, 3).join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
