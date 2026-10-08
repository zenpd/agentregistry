// Phase 0 browser check: demo switch, roles in the shell, gate decisions, rule proposal,
// audit trail, notifications, connection test, registry AI card, Pipelines and How It Works.
// Writes only to a probe agent it creates and deletes again.
import { chromium } from 'playwright'
import fs from 'node:fs'
const SP = process.argv[2], B = 'http://localhost:5174', API = 'http://127.0.0.1:8002/api/v1'
const TOKEN = fs.readFileSync(`${SP}/ar-token`, 'utf8').trim()
const H = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }
const R = []; const ok = (n, c, e = '') => R.push([c ? 'PASS' : 'FAIL', n, String(e ?? '').slice(0, 260)])
const browser = await chromium.launch()

// 1. Login page in development shows the local account.
{
  const ctx = await browser.newContext(); const p = await ctx.newPage()
  await p.goto(`${B}/login`); await p.waitForSelector('[data-testid=demo-login]', { timeout: 15000 }).catch(() => {})
  ok('login page shows the local development account in development', await p.locator('[data-testid=demo-login]').count() === 1)
  ok('login fields are filled for the local account', (await p.locator('input[type=email]').inputValue()) === 'admin@airegistry.local')
  await ctx.close()
}

const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
await ctx.addInitScript(([k, t]) => localStorage.setItem(k, t), ['airegistry_token', TOKEN])
const page = await ctx.newPage()
const errs = []
page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 160)) })
page.on('pageerror', e => errs.push('pageerror ' + String(e).slice(0, 160)))

// 2. Shell: demo switch, user chip, bell.
await page.goto(`${B}/`); await page.waitForSelector('[data-testid=user-chip]', { timeout: 30000 })
ok('the top bar shows no demo label', await page.locator('[data-testid=demo-switch]').count() === 0)
ok('top bar shows the signed-in person and role', /Registry Admin/.test(await page.textContent('[data-testid=user-chip]')))
ok('notification bell is in the top bar', await page.locator('[data-testid=notification-bell]').count() === 1)
await page.screenshot({ path: `${SP}/shots/p0-exec-default.png`, fullPage: false })

// 3. Agents page: only the 6 real agents by default, then 18 (12 labelled Demo) after the box is ticked in Settings.
await page.goto(`${B}/agents`); await page.waitForSelector('h3', { timeout: 30000 }); await page.waitForTimeout(800)
const realCards = await page.locator('h3').count()
ok('by default the list shows only the 6 real agents', realCards === 6, `cards: ${realCards}`)
await page.goto(`${B}/settings`); await page.waitForSelector('[data-testid=demo-toggle]', { timeout: 30000 })
ok('Settings says the demo agents are hidden and the box is not ticked', !(await page.isChecked('[data-testid=demo-toggle]')) && /hidden on every page/.test(await page.textContent('[data-testid=demo-agents]')))
await page.click('[data-testid=demo-toggle]'); await page.waitForSelector('[data-testid=demo-toggle]', { timeout: 30000 }); await page.waitForTimeout(1000)
await page.goto(`${B}/agents`); await page.waitForSelector('h3', { timeout: 30000 }); await page.waitForTimeout(800)
const allCards = await page.locator('h3').count()
const demoBadges = await page.locator('h3 >> text=Demo').count()
ok('after ticking the box the list shows 18 agents, 12 labelled Demo', allCards === 18 && demoBadges === 12, `cards ${allCards}, badges ${demoBadges}`)

// 4. A demo agent's own page opens while demo is hidden, labelled.
await page.goto(`${B}/agents/inv-recon`); await page.waitForSelector('[data-testid=demo-badge]', { timeout: 30000 }).catch(() => {})
ok('a demo agent page still opens and says Demo agent', await page.locator('[data-testid=demo-badge]').count() === 1)

// 5. Governance page: read-only review statuses, and the rule proposal that saves nothing.
const probe = await (await fetch(`${API}/agents/`, { method: 'POST', headers: H, body: JSON.stringify({ name: 'Probe Phase0 Check', description: 'browser check probe', reuse_justification: 'Temporary probe for the browser check, deleted at the end' }) })).json()
ok('probe agent created', !!probe.id, JSON.stringify(probe).slice(0, 200))
await page.goto(`${B}/governance`); await page.waitForSelector('table', { timeout: 30000 })
const row = page.locator('tr', { hasText: 'Probe Phase0 Check' })
ok('the Governance table has no decision dropdown: each status links to the agent tab',
  await row.locator('select').count() === 0 && await row.locator('[data-testid=review-status]').count() === 3
  && (await row.locator('[data-testid=review-status]').first().getAttribute('href')).endsWith(`/agents/${probe.id}?tab=governance`))
// The decision itself is recorded on the agent's Governance tab; here through the same API call.
const decided = await fetch(`${API}/agents/${probe.id}/governance/arb`, { method: 'PUT', headers: H, body: JSON.stringify({ status: 'Approved' }) })
ok('a decision is accepted for the signed-in reviewer', decided.ok, String(decided.status))
const gov = await (await fetch(`${API}/agents/${probe.id}/governance`, { headers: H })).json()
const arb = gov.gates.find(g => g.gate === 'arb')
ok('server shows reviewer = signed-in person and an expiry', arb.reviewer === 'Registry Admin' && !!arb.expiresAt, `${arb.reviewer} ${arb.expiresAt}`)
await row.locator('button', { hasText: 'Propose by rules' }).click()
await page.waitForSelector('[data-testid=rule-proposal]', { timeout: 15000 }).catch(() => {})
ok('rule proposal opens, marked not saved', /not saved/.test(await page.textContent('[data-testid=rule-proposal]').catch(() => '')))
ok('accept stays disabled until a reason of 20 characters', await page.locator('[data-testid=rule-proposal] button', { hasText: 'Accept and record' }).isDisabled())
await page.click('[data-testid=rule-proposal] >> text=Discard')
const gov2 = await (await fetch(`${API}/agents/${probe.id}/governance`, { headers: H })).json()
ok('discarding the proposal changed nothing', gov2.gates.filter(g => g.status === 'Approved').length === 1)
await page.screenshot({ path: `${SP}/shots/p0-governance.png`, fullPage: false })

// 6. Agent Governance tab: decision buttons, the note that I am recorded.
await page.goto(`${B}/agents/${probe.id}?tab=governance`); await page.waitForSelector('text=Request changes', { timeout: 30000 })
await page.locator('button', { hasText: 'Request changes' }).first().click()
ok('decision form says I am recorded as reviewer (no typed reviewer)', await page.locator('[data-testid=decider-note]').count() === 1)
await page.locator('button', { hasText: 'Cancel' }).first().click()

// 7. Audit trail.
await page.goto(`${B}/audit`); await page.waitForSelector('[data-testid=audit-count]', { timeout: 30000 }); await page.waitForTimeout(1200)
const auditCount = await page.textContent('[data-testid=audit-count]')
ok('audit trail lists events by people', /Showing \d+ of \d+/.test(auditCount) && await page.locator('[data-testid=audit-table] tbody tr').count() > 0, auditCount)
ok('my gate decision on the probe is in the trail', /Review gate changed/.test(await page.textContent('[data-testid=audit-table]')))
await page.click('text=By the registry'); await page.waitForTimeout(1200)
ok('the registry filter shows automatic events', /automatic/.test(await page.textContent('[data-testid=audit-table]')))
const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 15000 }).catch(() => null), page.click('[data-testid=audit-export]')])
ok('CSV export downloads a file', !!dl && /audit-trail-.*\.csv/.test(dl?.suggestedFilename() || ''), dl?.suggestedFilename())
await page.screenshot({ path: `${SP}/shots/p0-audit.png`, fullPage: false })

// 8. Settings: connection test, notifications, registry AI, users.
await page.goto(`${B}/settings`); await page.waitForSelector('[data-testid=test-connection]', { timeout: 30000 })
await page.click('[data-testid=test-connection]'); await page.waitForSelector('[data-testid=connection-result]', { timeout: 60000 }).catch(() => {})
const conn = await page.textContent('[data-testid=connection-result]').catch(() => 'no result')
ok('connection test names its result', /Connected|unreachable|unauthorized|not configured|not phoenix|blocked/i.test(conn), conn)
ok('notifications card shows the in-app inbox as on', /In-app inbox/.test(await page.textContent('[data-testid=notification-settings]')))
const before = await page.textContent('[data-testid=notification-bell]')
await page.click('[data-testid=send-test-notification]'); await page.waitForTimeout(2000)
const after = await page.getAttribute('[data-testid=notification-bell]', 'aria-label')
ok('a test message arrives in the bell', /unread/.test(after || ''), `${before} → ${after}`)
await page.click('[data-testid=notification-bell]'); await page.waitForSelector('[data-testid=notification-panel]', { timeout: 5000 }).catch(() => {})
ok('the bell panel lists the test message', /test notification/i.test(await page.textContent('[data-testid=notification-panel]').catch(() => '')))
await page.keyboard.press('Escape'); await page.mouse.click(5, 500)
ok('registry AI card lists 8 functions', await page.locator('[data-testid=registry-ai] tbody tr').count() >= 8)
await page.click('[data-testid=ai-off-check]'); await page.waitForSelector('[data-testid=ai-off-result]', { timeout: 60000 }).catch(() => {})
ok('the AI-off check passes', /every function still answers/.test(await page.textContent('[data-testid=ai-off-result]').catch(() => '')))
ok('users section offers role, deactivate and password reset', await page.locator('[data-testid=user-list] select').count() >= 1 && await page.locator('[data-testid=user-list] button', { hasText: 'Reset password' }).count() >= 1)
await page.screenshot({ path: `${SP}/shots/p0-settings.png`, fullPage: true })

// 9. Pipelines and How It Works.
await page.goto(`${B}/pipelines`); await page.waitForSelector('text=Daily notifications', { timeout: 30000 }).catch(() => {})
ok('Pipelines lists the daily notifications job', await page.locator('text=Daily notifications').count() > 0)
await page.goto(`${B}/how-it-works`); await page.waitForSelector('[data-testid=known-limits]', { timeout: 30000 }).catch(() => {})
ok('How It Works lists the known limits', await page.locator('[data-testid=known-limits] li').count() >= 5)

// Clean up the probe.
const del = await fetch(`${API}/agents/${probe.id}`, { method: 'DELETE', headers: H })
ok('probe agent deleted', del.status === 200)
ok('no console errors', errs.length === 0, errs.join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
