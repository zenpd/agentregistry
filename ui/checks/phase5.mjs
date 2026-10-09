// Phase 5 browser check: compliance packs and coverage, control evidence export, the decision
// log check, an evidence pack checked back by its hash, the data report and GRC export,
// incidents with a stop request shown on Executive and acknowledged, and an Auditor with an
// end date whose requests are logged. Probe agent and probe auditor are removed at the end
// (the auditor's row by the caller, since users are only deactivated).
import { chromium } from 'playwright'
import fs from 'node:fs'
const SP = process.argv[2], B = 'http://localhost:5174', API = 'http://127.0.0.1:8002/api/v1'
const TOKEN = fs.readFileSync(`${SP}/ar-token`, 'utf8').trim()
const H = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }
const R = []; const ok = (n, c, e = '') => R.push([c ? 'PASS' : 'FAIL', n, String(e ?? '').slice(0, 300)])
const j = async (method, path, body, headers = H) => { const r = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }); return { status: r.status, body: await r.json().catch(() => null) } }
const cleanup = []
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
await ctx.addInitScript(([k, t]) => localStorage.setItem(k, t), ['airegistry_token', TOKEN])
const page = await ctx.newPage()
const errs = []
page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 160)) })
page.on('pageerror', e => errs.push('pageerror ' + String(e).slice(0, 160)))
const text = async sel => (await page.textContent(sel).catch(() => '')) || ''
const download = async (click) => { const dl = page.waitForEvent('download', { timeout: 30000 }).catch(() => null); await click(); const f = await dl; return f ? fs.readFileSync(await f.path()) : null }

try {
  const a = await j('POST', '/agents/', { name: 'Probe Phase Five', dept: 'dept-finance', owner: 'Probe Team', ai_type: 'Autonomous Agent',
    description: 'Temporary probe agent for the Phase 5 browser check', stage: 'Ideation', stage_reason: '' })
  const id = a.body?.id
  ok('probe agent created', !!id)
  cleanup.push(() => j('DELETE', `/agents/${id}`))

  // Compliance page
  await page.goto(`${B}/compliance`); await page.waitForSelector('[data-testid=pack-detail]', { timeout: 90000 })
  ok('four packs are shown with their coverage', await page.locator('[role=tablist][aria-label=Packs] button').count() === 4)
  ok('ISO 42001 coverage reads "n of 38 controls evidenced"', /ISO\/IEC 42001: \d+ of 38 controls evidenced/.test(await text('[data-testid=pack-summary]')), await text('[data-testid=pack-summary]'))
  await page.locator('[data-testid=control-line] button', { hasText: 'A.6.2.8' }).click()
  ok('opening a control names the agents missing evidence', /Runtime tracing is linked/.test(await text('[data-testid=pack-detail]')))
  const ctlCsv = await download(() => page.locator('[data-testid=control-detail] button', { hasText: 'CSV' }).click())
  ok('a control\'s evidence downloads as CSV', ctlCsv && ctlCsv.toString().startsWith('pack,control,title'))
  await page.waitForSelector('[data-testid=decision-log] p', { timeout: 30000 })
  ok('the decision log check says the sealed decisions match', /sealed decisions match/.test(await text('[data-testid=decision-log]')), await text('[data-testid=decision-log]'))
  ok('the data and retention report lists agents', (await page.locator('[data-testid=data-report] tbody tr').count()) >= 1)
  const grc = await download(() => page.click('[data-testid=grc-controls]'))
  ok('the GRC controls export downloads', grc && grc.toString().startsWith('framework,control_id'))
  await page.screenshot({ path: `${SP}/shots/p5-compliance.png`, fullPage: true })

  // Evidence pack from the Governance tab, then checked back by its hash
  await page.goto(`${B}/agents/${id}?tab=governance`); await page.waitForSelector('[data-testid=evidence-pack]', { timeout: 30000 })
  const pdf = await download(() => page.click('[data-testid=evidence-pdf]'))
  ok('the evidence pack downloads as a PDF', pdf && pdf.subarray(0, 8).toString().startsWith('%PDF-1.4'))
  await page.waitForSelector('[data-testid=evidence-hash]', { timeout: 15000 })
  fs.writeFileSync(`${SP}/probe-evidence.pdf`, pdf)
  await page.goto(`${B}/compliance`); await page.waitForSelector('[data-testid=check-file]', { timeout: 90000 })
  await page.setInputFiles('[data-testid=check-file]', `${SP}/probe-evidence.pdf`)
  await page.waitForSelector('[data-testid=export-check] [role=status]', { timeout: 15000 })
  ok('the downloaded pack is recognised as unchanged', /Unchanged/.test(await text('[data-testid=export-check] [role=status]')), await text('[data-testid=export-check] [role=status]'))
  fs.writeFileSync(`${SP}/probe-evidence-changed.pdf`, Buffer.concat([pdf, Buffer.from('x')]))
  await page.setInputFiles('[data-testid=check-file]', `${SP}/probe-evidence-changed.pdf`)
  await page.waitForFunction(() => /No export/.test(document.querySelector('[data-testid=export-check] [role=status]')?.textContent || ''), null, { timeout: 15000 }).catch(() => {})
  ok('a changed copy is not recognised', /No export with this content/.test(await text('[data-testid=export-check] [role=status]')))

  // Incident with a stop request
  await page.goto(`${B}/agents/${id}?tab=risk`); await page.waitForSelector('[data-testid=incidents]', { timeout: 30000 })
  await page.click('[data-testid=link-incident]'); await page.fill('[data-testid=incident-title]', 'Probe incident: wrong answers')
  await page.selectOption('[data-testid=incident-severity]', 'high'); await page.click('[data-testid=save-incident]')
  await page.waitForSelector('[data-testid=incident-row]', { timeout: 15000 })
  await page.locator('[data-testid=incident-row] input').fill('Probe: it gives wrong answers to customers')
  await page.click('[data-testid=request-stop]'); await page.waitForSelector('[data-testid=stop-state]', { timeout: 15000 })
  ok('the stop request waits for the owner', /Waiting for the owner/.test(await text('[data-testid=stop-state]')))
  const att = (await j('GET', '/portfolio/attention')).body
  ok('Executive signals list the waiting stop request', att.stopWaiting.some(x => x.agentId === id))
  await page.locator('[data-testid=incident-row] input').fill('Probe: queue switched off by the admin')
  await page.click('[data-testid=ack-stop]'); await page.waitForFunction(() => /Acknowledged by/.test(document.querySelector('[data-testid=stop-state]')?.textContent || ''), null, { timeout: 15000 }).catch(() => {})
  ok('the admin acknowledges the stop', /Acknowledged by/.test(await text('[data-testid=stop-state]')))

  // An Auditor with an end date, whose requests are logged
  const until = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10)
  await page.goto(`${B}/settings`); await page.waitForSelector('[data-testid=user-list]', { timeout: 30000 })
  await page.getByRole('button', { name: /Add user/ }).first().click()
  await page.fill('#u-name', 'Probe Auditor'); await page.fill('#u-email', 'probe.auditor@example.com')
  await page.selectOption('#u-role', 'Auditor'); await page.fill('[data-testid=auditor-until]', until); await page.fill('#u-password', 'probe-auditor-1')
  await page.click('[data-testid=save-user]'); await page.waitForTimeout(1200)
  let aud = (await j('GET', '/admin/users')).body.find(u => u.email === 'probe.auditor@example.com')
  if (aud && aud.accessUntil !== until) {   // left from an earlier day: users are deactivated, never deleted
    await j('PUT', `/admin/users/${aud.id}`, { isActive: true, accessUntil: until })
    aud = (await j('GET', '/admin/users')).body.find(u => u.email === 'probe.auditor@example.com')
  }
  ok('the Auditor is added with an end date', aud?.accessUntil === until, JSON.stringify(aud))
  if (aud) cleanup.push(() => j('PUT', `/admin/users/${aud.id}`, { isActive: false }))
  // Left from an earlier run: users are deactivated, never deleted, so the form could not add it again.
  if (aud && aud.isActive === false) await j('PUT', `/admin/users/${aud.id}`, { isActive: true })
  const login = await j('POST', '/auth/login', { email: 'probe.auditor@example.com', password: 'probe-auditor-1' }, { 'Content-Type': 'application/json' })
  const at = login.body?.access_token || login.body?.token
  const viewed = await fetch(`${API}/agents/${id}`, { headers: { Authorization: `Bearer ${at}` } })
  ok('the Auditor can read', viewed.status === 200, viewed.status)
  const log = (await j('GET', `/audit?action=auditor.access&kind=all`)).body
  ok('the Auditor\'s request is in the audit trail', (log.rows || []).some(r => r.actorId === aud?.id), JSON.stringify(log).slice(0, 200))
} catch (e) {
  ok('the check ran to the end', false, String(e).slice(0, 300))
} finally {
  for (const c of cleanup.reverse()) await c().catch(() => {})
}
ok('probe agent removed', !(await j('GET', '/agents/?limit=100')).body.data.some(a => a.name === 'Probe Phase Five'))
ok('no console errors', errs.length === 0, errs.join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
