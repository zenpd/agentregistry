// Phase 2 browser check: owner and backup owner, away and deputy, ranked approvals with
// a Decided tab, classification (propose, see in Approvals, confirm), approved tools,
// controls, versions, the tool-call line, and the retirement steps.
// Works on a probe user, a probe agent and a probe tool, and removes them at the end.
import { chromium } from 'playwright'
import fs from 'node:fs'
const SP = process.argv[2], B = 'http://localhost:5174', API = 'http://127.0.0.1:8002/api/v1'
const TOKEN = fs.readFileSync(`${SP}/ar-token`, 'utf8').trim()
const H = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }
const R = []; const ok = (n, c, e = '') => R.push([c ? 'PASS' : 'FAIL', n, String(e ?? '').slice(0, 300)])
const j = async (method, path, body) => { const r = await fetch(`${API}${path}`, { method, headers: H, body: body ? JSON.stringify(body) : undefined }); return { status: r.status, body: await r.json().catch(() => null) } }
const cleanup = []
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await ctx.addInitScript(([k, t]) => localStorage.setItem(k, t), ['airegistry_token', TOKEN])
const page = await ctx.newPage()
const errs = []
page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 160)) })
page.on('pageerror', e => errs.push('pageerror ' + String(e).slice(0, 160)))
const text = async sel => (await page.textContent(sel).catch(() => '')) || ''

try {
  // Setup
  let u = await j('POST', '/admin/users', { email: 'probe.deputy@example.com', name: 'Probe Deputy', role: 'Architect Steward', password: 'probe-pass-123' })
  if (!u.body?.id) {      // left from an earlier run: users are deactivated, never deleted
    const old = (await j('GET', '/admin/users')).body.find(x => x.email === 'probe.deputy@example.com')
    if (old) { await j('PUT', `/admin/users/${old.id}`, { isActive: true }); u = { body: { id: old.id } } }
  }
  const probeUser = u.body?.id
  ok('probe user created', !!probeUser, JSON.stringify(u.body))
  cleanup.push(() => j('DELETE', `/admin/users/${probeUser}`))
  const a = await j('POST', '/agents/', { name: 'Probe Phase Two', dept: 'dept-finance', owner: 'Probe Team', description: 'Temporary probe agent for the Phase 2 browser check',
    ai_type: 'Autonomous Agent', stage: 'Ideation', stage_reason: '', mcp_servers: ['probe-payments-mcp'] })
  const agentId = a.body?.id
  ok('probe agent created', !!agentId, JSON.stringify(a.body).slice(0, 200))
  cleanup.push(() => j('DELETE', `/agents/${agentId}`))

  // Owner and backup owner on the Overview
  await page.goto(`${B}/agents/${agentId}`); await page.waitForSelector('[data-testid=owner-fact]', { timeout: 30000 })
  ok('Overview shows the backup owner as none set', /none set/.test(await text('[data-testid=backup-owner]')))
  await page.click('[data-testid=change-owner]')
  await page.selectOption('[data-testid=owner-select]', 'user-admin')
  await page.selectOption('[data-testid=backup-select]', probeUser)
  await page.click('[data-testid=save-owner]')
  await page.waitForFunction(() => /Probe Deputy/.test(document.querySelector('[data-testid=backup-owner]')?.textContent || ''), null, { timeout: 15000 }).catch(() => {})
  const ag = (await j('GET', `/agents/${agentId}`)).body
  ok('owner and backup owner saved', ag.ownerUserId === 'user-admin' && ag.backupOwnerUserId === probeUser && ag.owner === 'Registry Admin', JSON.stringify({ o: ag.owner, b: ag.backupOwnerUserId }))
  ok('Overview shows the classification as not confirmed', /Not confirmed/.test(await text('[data-testid=classification-status]')))

  // Settings: approved tools, controls, away and deputy
  await page.goto(`${B}/settings`); await page.waitForSelector('[data-testid=approved-tools]', { timeout: 30000 })
  const chip = page.locator('[data-testid=tool-candidates] button', { hasText: 'probe-payments-mcp' })
  await chip.first().waitFor({ timeout: 20000 }).catch(() => {})
  ok('the declared tool is offered as a candidate', await chip.count() === 1)
  await chip.click(); await page.selectOption('[data-testid=tool-class]', 'HIGH'); await page.click('[data-testid=add-tool]')
  await page.waitForSelector('[data-testid=tool-row]:has-text("probe-payments-mcp")', { timeout: 15000 }).catch(() => {})
  const tool = (await j('GET', '/tools/approved')).body.tools.find(t => t.name === 'probe-payments-mcp')
  ok('the tool is on the approved list as HIGH', tool?.riskClass === 'HIGH')
  if (tool) cleanup.push(() => j('DELETE', `/tools/approved/${tool.id}`))
  ok('Settings lists the controls with their state', await page.locator('[data-testid=control-row]').count() >= 15, await page.locator('[data-testid=control-row]').count())
  const until = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10)
  await page.fill('[data-testid=away-until]', until); await page.selectOption('[data-testid=away-deputy]', probeUser); await page.click('[data-testid=save-away]')
  await page.waitForSelector('[data-testid=away-settings] [role=status]', { timeout: 10000 })
  const me1 = (await j('GET', '/auth/me')).body
  ok('away period and deputy saved', me1.awayUntil === until && me1.deputyUserId === probeUser, JSON.stringify(me1).slice(0, 200))
  await page.click('[data-testid=clear-away]'); await page.waitForTimeout(800)
  ok('"I am back" clears the away period', (await j('GET', '/auth/me')).body.awayUntil === null)
  await page.screenshot({ path: `${SP}/shots/p2-settings.png` })

  // Classification on the Governance tab
  await page.goto(`${B}/agents/${agentId}?tab=governance`); await page.waitForSelector('[data-testid=classification]', { timeout: 30000 })
  ok('tool class HIGH comes from the approved tool', /HIGH from probe-payments-mcp/.test(await text('[data-testid=tool-risk]')), await text('[data-testid=tool-risk]'))
  const stageOptions = await page.locator('select:near(:text("Change stage to")) option').allTextContents()
  ok('the stage list has no Deprecated (retire through the steps)', !stageOptions.includes('Deprecated'), stageOptions.join(','))
  await page.click('[data-testid=classify]')
  const pick = async (q, label) => page.locator(`[data-testid=q-${q}] label`, { hasText: new RegExp('^\\s*' + label) }).first().locator('input').check()
  await pick('area', 'None of these'); await pick('interacts', 'Yes'); await pick('audience', 'Only people inside'); await pick('data', 'Personal data'); await pick('retention', 'Up to 1 year'); await pick('decisions', 'It only suggests')
  await page.waitForFunction(() => /Answer every question/.test(document.querySelector('[data-testid=classification-suggestion]')?.textContent || '') === false
    && /Limited Risk/.test(document.querySelector('[data-testid=classification-suggestion]')?.textContent || ''), null, { timeout: 10000 }).catch(() => {})
  const sug = await text('[data-testid=classification-suggestion]')
  ok('the suggestion is Limited Risk, MEDIUM from the answers, raised to HIGH by the tool', /Limited Risk/.test(sug) && /from the answers: MEDIUM/.test(sug) && /Raised to HIGH/.test(sug), sug.slice(0, 300))
  await page.click('[data-testid=save-proposal]')
  await page.waitForSelector('[data-testid=classification-pending]', { timeout: 15000 })
  ok('the proposal waits for confirmation', /Waiting for confirmation/.test(await text('[data-testid=classification-pending]')))

  // Approvals: the proposal is in the queue, reviews show who can decide, Decided tab
  await page.goto(`${B}/approvals`); await page.waitForSelector('[data-testid=queue-reviews]', { timeout: 30000 })
  ok('Approvals lists the classification proposal', await page.locator('[data-testid=classification-row]', { hasText: 'Probe Phase Two' }).count() === 1)
  const reviewRows = await page.locator('[data-testid=review-row]').count()
  ok('each review row says who can decide', reviewRows === 0 || await page.locator('[data-testid=deciders]').count() === reviewRows, `rows ${reviewRows}`)
  await page.screenshot({ path: `${SP}/shots/p2-approvals.png` })

  // Confirm the classification
  await page.goto(`${B}/agents/${agentId}?tab=governance`); await page.waitForSelector('[data-testid=confirm-classification]', { timeout: 30000 })
  await page.click('[data-testid=confirm-classification]')
  await page.waitForFunction(() => /confirmed by/.test(document.querySelector('[data-testid=classification-current]')?.textContent || ''), null, { timeout: 15000 }).catch(() => {})
  ok('the classification is confirmed by the signed-in person', /Limited Risk.*confirmed by Registry Admin/s.test(await text('[data-testid=classification-current]')), await text('[data-testid=classification-current]'))
  ok('the agent now has risk level HIGH', (await j('GET', `/agents/${agentId}`)).body.riskLevel === 'HIGH')
  await page.waitForSelector('[data-testid=tool-calls-line]', { timeout: 30000 }).catch(() => {})
  ok('the tool-call line explains there is no approval to compare with', /No Security Review approval/.test(await text('[data-testid=tool-calls-line]')), await text('[data-testid=tool-calls-line]'))
  await page.screenshot({ path: `${SP}/shots/p2-governance.png`, fullPage: true })

  // Versions on Integrate
  await page.goto(`${B}/agents/${agentId}?tab=integrate`); await page.waitForSelector('[data-testid=versions]', { timeout: 30000 })
  await page.click('[data-testid=release-version]'); await page.fill('[data-testid=version-input]', '1.0'); await page.fill('[data-testid=changelog-input]', 'First release of the probe agent')
  await page.click('[data-testid=confirm-release]')
  await page.waitForSelector('[data-testid=version-row]', { timeout: 15000 }).catch(() => {})
  ok('the released version is listed with its changelog', /First release of the probe agent/.test(await text('[data-testid=version-row]')))

  // Retirement steps. The check makes requests faster than a person (300 a minute
  // per person is the limit), so it lets the window pass first.
  await page.waitForTimeout(61000)
  await page.goto(`${B}/agents/${agentId}?tab=governance`); await page.waitForSelector('[data-testid=retirement]', { timeout: 30000 })
  await page.click('[data-testid=start-retirement]'); await page.fill('[data-testid=retire-reason]', 'Probe agent retired at the end of the browser check')
  await page.click('[data-testid=confirm-start]'); await page.waitForSelector('[data-testid=step-traffic]', { timeout: 15000 })
  ok('traffic needs a person to confirm (no tracing link)', /cannot see its calls/.test(await text('[data-testid=step-traffic]')))
  await page.locator('[data-testid=step-traffic] input').fill('No tracing link, the probe agent has never been deployed anywhere')
  await page.locator('[data-testid=step-traffic] button', { hasText: 'Confirm' }).click(); await page.waitForTimeout(800)
  await page.click('[data-testid=revoke]'); await page.waitForTimeout(800)
  ok('finish is possible once the steps are done', await page.isEnabled('[data-testid=finish-retirement]'))
  await page.click('[data-testid=finish-retirement]'); await page.waitForTimeout(1200)
  ok('the agent is retired (Deprecated)', (await j('GET', `/agents/${agentId}`)).body.stage === 'Deprecated')

  // Decided tab
  await page.goto(`${B}/approvals`); await page.click('[data-testid=view-decided]')
  await page.waitForSelector('[data-testid=decided-row]', { timeout: 15000 }).catch(() => {})
  const decided = await page.locator('[data-testid=decided-row]', { hasText: 'Probe Phase Two' }).allTextContents()
  ok('Decided lists the classification and the retirement', decided.some(t => /Classification confirmed/.test(t)) && decided.some(t => /Agent retired/.test(t)), decided.join(' | ').slice(0, 300))

  // Executive renders the lifecycle section exactly when there are signals
  const att = (await j('GET', '/portfolio/attention')).body
  await page.goto(`${B}/`); await page.waitForTimeout(2500)
  const n = att.silent.length + att.runningAfterRetirement.length + att.callsRetired.length + att.stalled.length + att.ownerless.length
  ok('Executive shows lifecycle signals exactly when there are any', await page.locator('[data-testid=lifecycle-attention]').count() === (n > 0 ? 1 : 0), `signals ${n}`)
} catch (e) {
  ok('the check ran to the end', false, String(e).slice(0, 300))
} finally {
  for (const c of cleanup.reverse()) await c().catch(() => {})
  await j('PUT', '/auth/me/away', { awayUntil: null, deputyUserId: null })
}
ok('probe agent removed', !(await j('GET', '/agents/?limit=100')).body.data.some(a => a.name === 'Probe Phase Two'))
ok('probe tool removed', !(await j('GET', '/tools/approved')).body.tools.some(t => t.name === 'probe-payments-mcp'))
ok('probe user deactivated', !(await j('GET', '/admin/users')).body.some(u => u.email === 'probe.deputy@example.com' && u.isActive))
ok('no console errors', errs.length === 0, errs.join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
