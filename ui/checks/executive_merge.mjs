// Navigation, the merged Executive page, clickable cards, the Business Value and Tokenomics tabs with their
// year and month filter, and the Digital Onboarding Prod demo agent (all checks green, $3,000 cost, $5,000 profit).
// Reads only. Needs the demo agent seeded with backend/scripts/seed_happy_path.py.
import { chromium } from 'playwright'
import fs from 'node:fs'
const SP = process.argv[2], B = 'http://localhost:5174', API = 'http://127.0.0.1:8002/api/v1'
const TOKEN = fs.readFileSync(`${SP}/ar-token`, 'utf8').trim()
const R = []; const ok = (n, c, e = '') => R.push([c ? 'PASS' : 'FAIL', n, String(e ?? '').slice(0, 300)])
const get = async p => (await fetch(API + p, { headers: { Authorization: `Bearer ${TOKEN}`, 'X-Include-Demo': '1' } })).json()
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
await ctx.addInitScript(([k, t]) => { localStorage.setItem(k, t); localStorage.setItem('airegistry_include_demo', '1') }, ['airegistry_token', TOKEN])
const page = await ctx.newPage()
const errs = []; page.on('pageerror', e => errs.push(String(e).slice(0, 160)))
const text = async sel => ((await page.textContent(sel).catch(() => '')) || '').replace(/\s+/g, ' ')
const money = s => { const m = /\$([\d.,]+)([KM]?)/.exec(s || ''); return m ? Number(m[1].replace(/,/g, '')) * (m[2] === 'M' ? 1e6 : m[2] === 'K' ? 1e3 : 1) : null }
const prevMonth = (() => { const d = new Date(); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() - 1); return d })()
const prevKey = `${prevMonth.getUTCFullYear()}-${String(prevMonth.getUTCMonth() + 1).padStart(2, '0')}`
const pick = async (scope) => {          // choose the previous month in a MonthPicker
  await page.locator(`[data-testid=${scope}] select[aria-label=Year]`).selectOption(String(prevMonth.getUTCFullYear()))
  await page.locator(`[data-testid=${scope}] select[aria-label=Period]`).selectOption(prevKey)
}
try {
  const all = (await get('/agents/?limit=100')).data
  // What the page shows: the real agents and the showcase agent (the other demo agents need the browser switch, set above).
  const shown = all
  const prod = all.find(a => a.name === 'Digital Onboarding Prod')
  ok('the demo agent Digital Onboarding Prod exists', !!prod && prod.isDemo, prod?.id)

  // 2, 3, 4: menu
  await page.goto(`${B}/`); await page.waitForSelector('[data-testid=user-chip]', { timeout: 30000 }); await page.waitForTimeout(2500)
  const nav = (await page.locator('nav a').allTextContents()).map(t => t.replace(/\s*\d+$/, '').trim())
  ok('the menu says Agent Registry, with Discovered Agents above it', nav.indexOf('Discovered Agents') >= 0 && nav.indexOf('Discovered Agents') < nav.indexOf('Agent Registry'), nav.join(' | '))
  ok('the menu has no Business Impact, Programme Health or AI Registry', !nav.some(n => /Business Impact|Programme Health|AI Registry/.test(n)))
  await page.goto(`${B}/agents`); await page.waitForSelector('h1'); ok('the agents page is titled Agent Registry', /Agent Registry/.test(await text('h1')))

  // 1: Business Impact is part of the Executive page
  await page.goto(`${B}/business?dept=Finance`); await page.waitForTimeout(3500)
  ok('/business lands on the Executive page and keeps the unit filter', new URL(page.url()).pathname === '/' && new URL(page.url()).searchParams.get('dept') === 'Finance' && await page.locator('#business-impact [data-testid=bu-kpis]').count() === 1, page.url())
  await page.goto(`${B}/`); await page.waitForSelector('#business-impact [data-testid=bu-kpis]', { timeout: 30000 })
  ok('Executive has no "Show what is counted" links: the cards are clickable', await page.locator('button', { hasText: 'Show what is counted' }).count() === 0)

  // 6: cards open what they count
  await page.locator('[data-testid=kpi-agents]').click(); await page.waitForTimeout(300)
  ok('there are four cards and clicking Total agents lists the agents in the pipeline', await page.locator('[data-testid=bu-kpis] [role=button]').count() === 4); ok('the list holds the pipeline agents', /in the pipeline/.test(await text('[data-testid=tile-behind]')) && await page.locator('[data-testid=tile-behind] a').count() === shown.filter(a => ['Ideation', 'Development', 'Testing'].includes(a.stage)).length)
  await page.locator('[data-testid=kpi-agents]').click()
  ok('clicking again closes the list', await page.locator('[data-testid=tile-behind]').count() === 0)

  // One page, one filter: no separate business impact title, every business unit offered, every widget follows the choice
  ok('the page has one title and no Business impact heading', await page.locator('main h1').count() === 1 && !/Business impact by business unit/i.test(await text('main')))
  const chips = (await page.locator('[data-testid=bu-chips] button').allTextContents()).map(x => x.replace(/\s+/g, ' ').trim())
  const depts = (await get('/admin/taxonomy')).departments
  ok('every business unit is offered as a filter, also one with no agent', depts.every(d => chips.some(x => x.startsWith(d.name))) && chips.some(x => / 0$/.test(x)), chips.join(' | '))
  const chipsBox = await page.locator('[data-testid=bu-chips]').boundingBox(), kpiBox = await page.locator('[data-testid=bu-kpis]').boundingBox()
  ok('the filter sits above the cards', chipsBox.y < kpiBox.y)
  ok('the risk charts sit above Agents by stage', (await page.locator('[data-testid=risk-charts]').boundingBox()).y < (await page.locator('[data-testid=pipeline-rail]').boundingBox()).y)
  // The numbers of one unit agree with each other and with the API
  const unit = depts.find(d => shown.some(a => a.dept === d.id))
  await page.locator('[data-testid=bu-chips] button', { hasText: unit.name }).click(); await page.waitForTimeout(2500)
  const inUnit = shown.filter(a => a.dept === unit.id), live = inUnit.filter(a => a.stage !== 'Deprecated')
  // The figure of a card is its second line.
  const cardValue = async id => Number(((await page.locator(`[data-testid=${id}] > div`).nth(1).textContent()) || '').replace(/[^\d]/g, ''))
  const totalAgents = await cardValue('kpi-agents'), inPipeline = Number((/(\d+) in pipeline/.exec(await text('[data-testid=kpi-agents]')) || [])[1]), openFindings = await cardValue('kpi-open-risk-findings')
  const stageSum = (await page.locator('[data-testid^=stage-] div:first-child').allTextContents()).reduce((n, x) => n + Number(x), 0)
  const unitRisks = await get(`/governance/risks/summary?dept=${unit.id}`)   // asked the way the page asks: with the demo agents this browser shows
  ok(`${unit.name}: total agents, the stage tiles and the agent table agree`, totalAgents === live.length && stageSum === inUnit.length && await page.locator('[data-testid=bu-row]').count() === inUnit.length, `${totalAgents} ${stageSum} ${inUnit.length}`)
  ok(`${unit.name}: in pipeline and open risk findings follow the filter`, inPipeline === live.filter(a => ['Ideation', 'Development', 'Testing'].includes(a.stage)).length && openFindings === unitRisks.totalFindings, `${inPipeline} ${openFindings} vs ${unitRisks.totalFindings}`)
  const charts = await text('[data-testid=risk-charts]')
  ok(`${unit.name}: the risk chart shows the same count for each category as the API`, unitRisks.byCategory.every(c => new RegExp(`${c.label}\\s*${c.count}(?!\\d)`).test(charts)), unitRisks.byCategory.map(c => `${c.label} ${c.count}`).join(', '))
  await page.locator('[data-testid=bu-chips] button').first().click(); await page.waitForTimeout(1500)

  await page.locator('#business-impact [data-testid=value-breakdown-toggle]').click(); await page.waitForSelector('[data-testid=value-breakdown]')
  ok('clicking the Value / month card opens the calculation', /How the value is calculated/.test(await text('[data-testid=value-breakdown]')))
  await page.locator('#business-impact [data-testid=cost-breakdown-toggle]').click(); await page.waitForSelector('[data-testid=cost-breakdown]')
  ok('clicking the Cost to run card opens the calculation', /How the cost to run is calculated/.test(await text('[data-testid=cost-breakdown]')))
  await page.click('[data-testid=stage-Production]'); await page.waitForSelector('h3', { timeout: 30000 }); await page.waitForTimeout(1200)
  const stages = await page.locator('select').first().inputValue()
  ok('clicking the Production pipeline tile opens the agent list on Production', new URL(page.url()).searchParams.get('stage') === 'Production' && stages === 'Production', page.url())

  // 5, 7, 8: agent tabs
  await page.goto(`${B}/agents/${prod.id}`); await page.waitForSelector('h1', { timeout: 30000 })
  const tabs = (await page.locator('[role=tablist] button, button[role=tab], nav button').allTextContents()).join(' | ')
  ok('the agent tab is named Business Value, not Revenue & Expenditure', /Business Value/.test(await text('main')) && !/Expenditure/.test(await text('main')), tabs.slice(0, 120))
  await page.goto(`${B}/agents/${prod.id}?tab=revenue`); await page.waitForSelector('[data-testid=value-month]', { timeout: 30000 }); await page.waitForTimeout(1500)
  const bv = await text('main')
  ok('Business Value has no token or hosting tiles, one Total cost with a link to Tokenomics', !/TOKEN COST|Hosting cost/i.test(await text('section')) && await page.locator('[data-testid=to-tokenomics]').count() === 1)
  ok('Business Value shows value $8.0K, total cost $3.0K and net +$5.0K for the demo agent', /\$8\.0K\/mo/.test(bv) && /\$3\.0K/.test(bv) && /\+\$5\.0K/.test(bv))
  ok('Business Value no longer carries the hosting setup or the other-models table', !/Hosting & infrastructure|same work on other models/.test(bv))
  await pick('value-month'); await page.waitForTimeout(2500)
  const econPrev = await get(`/agents/${prod.id}/economics?month=${prevKey}`)
  ok('choosing the previous month shows that month on Business Value', new RegExp(`the whole month`).test(await text('main')) && econPrev.period.month === prevKey, `${econPrev.period.month} ${econPrev.totalCostCents / 100}`)
  await page.goto(`${B}/agents/${prod.id}?tab=tokenomics`); await page.waitForSelector('[data-testid=usage-month]', { timeout: 30000 }); await page.waitForTimeout(2000)
  const tk = await text('main')
  ok('Tokenomics carries token cost, hosting cost, total cost, where the money goes, hosting setup and other models', /Token cost/.test(tk) && /Hosting cost/.test(tk) && /Total cost/.test(tk) && /Where the money goes/.test(tk) && /Hosting & infrastructure/.test(tk) && /same work on other models/.test(tk))
  ok('Tokenomics total cost for the demo agent is $3.0K', money((await text('[data-testid=cost-section]')).split('Total cost')[1]) === 3000)
  await pick('usage-month'); await page.waitForTimeout(3000)
  const usagePrev = await get(`/agents/${prod.id}/tokenomics?month=${prevKey}`)
  ok('the period control has no Month label and offers the last 30 and 90 days', !/Month/.test((await text('[data-testid=usage-month]')).replace(/Last \d+ days|January|February|March|April|May|June|July|August|September|October|November|December|\d{4}/g, '')) && /Last 30 days/.test(await text('[data-testid=usage-month]')) && /Last 90 days/.test(await text('[data-testid=usage-month]')))
  ok('choosing the previous month shows that month on Tokenomics', new RegExp(`Showing\\s+${prevMonth.toLocaleString('en-US', { month: 'long', timeZone: 'UTC' })}`).test(await text('[data-testid=usage-period]')) && usagePrev.month === prevKey, await text('[data-testid=usage-period]'))
  ok('that month shows its own token cost and hides the forecast', usagePrev.totals.costCents > 0 && !/Token cost forecast/.test(await text('main')), `${usagePrev.totals.costCents}`)

  // 9: the demo agent is green
  const gov = await get(`/agents/${prod.id}/governance`), econ = await get(`/agents/${prod.id}/economics`), risks = await get(`/agents/${prod.id}/risks`), integ = await get(`/agents/${prod.id}/integration`)
  ok('the three reviews are approved with every checklist item passing', gov.gates.every(g => g.status === 'Approved' && g.checklistSummary.failed === 0 && g.checklistSummary.pending === 0), gov.gates.map(g => `${g.gate} ${g.checklistSummary.passed}/${g.checklistSummary.total}`).join(' '))
  ok('the record is 100% complete, ready for Production, nothing to recertify', gov.completeness.score === 100 && gov.readiness.production.ready && !gov.recertification.due)
  ok('the demo agent costs $3,000 a month, earns $8,000 and makes a $5,000 profit', econ.totalCostCents === 300000 && econ.valueCents === 800000 && econ.netCents === 500000 && econ.valueState === 'attested', `${econ.totalCostCents / 100} ${econ.valueCents / 100} ${econ.netCents / 100}`)
  ok('no open risks and certified for reuse', risks.score.total === 0 && integ.reuse.certified === true)
} catch (e) {
  ok('the check ran to the end', false, String(e).slice(0, 300))
}
ok('no page errors', errs.length === 0, errs.slice(0, 3).join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
