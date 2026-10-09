// Demo agents check (run with the box ticked in Settings, as set here): the seeded example agents are shown without a label in the top bar,
// the 10 archived ones (repeats, archived 2026-10-08) are left out everywhere and listed in Settings,
// and every tab of every shown demo agent opens. Also Executive, Business Impact and the dependency
// graph. Changes nothing.
import { chromium } from 'playwright'
import fs from 'node:fs'
const SP = process.argv[2], B = 'http://localhost:5174', API = 'http://127.0.0.1:8002/api/v1'
const TOKEN = fs.readFileSync(`${SP}/ar-token`, 'utf8').trim()
const R = []; const ok = (n, c, e = '') => R.push([c ? 'PASS' : 'FAIL', n, String(e ?? '').slice(0, 300)])
const TABS = ['overview', 'diagram', 'governance', 'tokenomics', 'revenue', 'risk', 'integrate']
const ARCHIVED = ['Employee Onboarding Concierge', 'Expense Report Auditor', 'Transaction Fraud Detection Model', 'Customer Churn Prediction Model',
  'Refund Adjudication Agent', 'Change Request Validator', 'Code Review Copilot', 'Market Intelligence Digest', 'Dynamic Pricing Optimizer', 'Supplier Risk Monitor']
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await ctx.addInitScript(([k, t]) => { localStorage.setItem(k, t); localStorage.setItem('airegistry_include_demo', '1') }, ['airegistry_token', TOKEN])
const page = await ctx.newPage()
const errs = []
page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 160)) })
page.on('pageerror', e => errs.push('pageerror ' + String(e).slice(0, 160)))
const failed = []
let limited = 0, insightLimited = 0
page.on('response', r => {
  if (!r.url().includes('/api/v1/')) return
  // AI insight runs have their own per-person limit by design; any other refusal is a failure.
  if (r.status() === 429) { if (/\/insights\/[^/]+\/run/.test(r.url())) insightLimited++; else limited++ }
  else if (r.status() >= 500) failed.push(`${r.status()} ${r.url().replace(/^.*\/api\/v1/, '')}`)
})
const pause = ms => new Promise(r => setTimeout(r, ms))

try {
  const everyone = (await (await fetch(`${API}/agents/?limit=100`, { headers: { Authorization: `Bearer ${TOKEN}`, 'X-Include-Demo': '1' } })).json()).data
  const demo = everyone.filter(a => a.isDemo), total = everyone.length
  await page.goto(`${B}/`); await page.waitForSelector('[data-testid=user-chip]', { timeout: 30000 }); await page.waitForTimeout(2500)
  ok('the top bar shows no demo label', await page.locator('[data-testid=demo-switch]').count() === 0 && !/demo agents/i.test(await page.textContent('header').catch(() => '')))
  ok(`Executive counts all ${total} agents`, new RegExp(`Total Agents\\s*${total}`).test((await page.textContent('main')).replace(/\s+/g, ' ')))
  await page.goto(`${B}/agents`); await page.waitForSelector('h3', { timeout: 30000 }); await page.waitForTimeout(800)
  const names = await page.locator('h3').allTextContents()
  ok(`the agent list shows all ${total} agents, ${demo.length} labelled Demo`, names.length === total && names.filter(t => /Demo/.test(t)).length === demo.length, `${names.length} agents`)
  ok('no archived agent is listed', !names.some(t => ARCHIVED.some(a => t.startsWith(a))))

  for (const a of demo) {
    const problems = []
    for (const tab of TABS) {
      await page.goto(`${B}/agents/${a.id}?tab=${tab}`)
      await page.waitForSelector('h1', { timeout: 30000 }).catch(() => problems.push(`${tab}: no heading`))
      await page.waitForTimeout(1200)
      const body = await page.textContent('main').catch(() => '')
      if (!body.includes(a.name)) problems.push(`${tab}: name missing`)
      if (/Could not load|Something went wrong|Error: /.test(body)) problems.push(`${tab}: error text`)
    }
    ok(`${a.name}: all 7 tabs open without errors`, problems.length === 0, problems.join(', '))
    await pause(4000)
  }

  await page.goto(`${B}/settings`); await page.waitForSelector('[data-testid=demo-agents]', { timeout: 30000 }); await page.waitForTimeout(1200)
  ok('Settings offers the demo switch, ticked', await page.isChecked('[data-testid=demo-toggle]'))
  ok('Settings shows no archived agents card', await page.locator('[data-testid=archived-agents]').count() === 0)
  await page.goto(`${B}/business`); await page.waitForSelector('[data-testid=bu-kpis]', { timeout: 30000 }); await page.waitForTimeout(1500)
  const biz = await page.textContent('main')
  ok('Business Impact shows demo agents and no archived ones', biz.includes('Invoice Reconciliation Agent') && !ARCHIVED.some(a => biz.includes(a)))
  await page.goto(`${B}/dependencies`); await page.waitForSelector('canvas', { timeout: 30000 }).catch(() => {})
  await page.waitForTimeout(3000)
  ok('the dependency graph draws', await page.locator('canvas').count() >= 1)
  await page.screenshot({ path: `${SP}/shots/demo-graph.png` })
} catch (e) {
  ok('the check ran to the end', false, String(e).slice(0, 300))
}
ok('no server errors', failed.length === 0, failed.slice(0, 5).join(' | '))
ok('no page request was refused by the request limit (429)', limited === 0, `${limited} refused, plus ${insightLimited} AI insight runs held back by their own limit`)
ok('no console errors', errs.length === 0, errs.slice(0, 5).join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
