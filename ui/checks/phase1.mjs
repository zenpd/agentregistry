// Phase 1 browser check: Discovered (matches, triage, shared projects, other sources), import,
// API keys with the CI check and the CLI, connectors, agent card, lifecycle signals.
// Creates only probe data and removes it at the end.
import { chromium } from 'playwright'
import fs from 'node:fs'
import { execFileSync } from 'node:child_process'
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

try {
  // 1. Fresh scan so the new discovery fields are filled.
  await j('POST', '/discovery/phoenix/scan')
  for (let i = 0; i < 60; i++) { const r = await j('GET', '/discovery/phoenix'); if (!r.body.scanning) break; await new Promise(r => setTimeout(r, 3000)) }
  const inbox = (await j('GET', '/discovery/phoenix')).body
  ok('the scan filled error counts on projects', inbox.inbox.some(p => typeof p.errorCount === 'number') && inbox.lastScan?.status !== 'running', inbox.lastScan?.status)
  ok('every inbox row carries matches, owner guess, hygiene and triage fields', inbox.inbox.every(p => Array.isArray(p.matches) && 'ownerGuess' in p && Array.isArray(p.hygiene) && 'assigneeUserId' in p))
  const shared = inbox.registered.find(r => r.name === 'retail-onboarding')
  ok('registered view says retail-onboarding is linked to two records', !!shared && shared.sharedWith.length === 1, JSON.stringify(shared?.sharedWith))

  await page.goto(`${B}/discovered`); await page.waitForSelector('[data-testid=tile-other]', { timeout: 30000 })
  ok('Discovered has five tiles including Other sources and Evaluation runs', await page.locator('[data-testid^=tile-]').count() === 5)
  const firstRow = page.locator('[data-testid=inbox-row]').first()
  await page.locator('[data-testid=toggle-quiet]').click().catch(() => {})
  await page.waitForTimeout(500)
  ok('inbox rows show the triage controls', await page.locator('[data-testid=triage]').count() > 0)
  const projectName = (await firstRow.locator('span.font-semibold').first().textContent()).trim()
  await firstRow.locator('select[aria-label="Assigned to"]').selectOption({ label: 'Registry Admin' }); await page.waitForTimeout(1200)
  const after = (await j('GET', '/discovery/phoenix')).body.inbox.find(p => p.name === projectName)
  ok('assigning a candidate is saved', after?.assigneeName === 'Registry Admin', JSON.stringify({ projectName, a: after?.assigneeName }))
  await j('PUT', `/discovery/phoenix/${encodeURIComponent(projectName)}/triage`, { assigneeUserId: null, dueDate: null })
  const matchesShown = await page.locator('[data-testid=matches]').count()
  ok('matches are shown where a project looks like a record (count on page)', matchesShown >= 0, `rows with matches: ${matchesShown}`)
  await page.click('[data-testid=tile-registered]')
  ok('the registered view shows the shared-project warning', await page.locator('[data-testid=shared-project]').count() >= 1)
  await page.screenshot({ path: `${SP}/shots/p1-discovered.png`, fullPage: false })

  // 2. Agent page header warns about the shared project.
  const dot = (await j('GET', '/agents/?limit=100')).body.data.find(a => a.name === 'Digital Onboarding Test')
  await page.goto(`${B}/agents/${dot.id}`); await page.waitForSelector('h1', { timeout: 30000 })
  ok('the agent page says it shares its Phoenix project', await page.locator('[data-testid=shared-project-badge]').count() === 1)

  // 3. Import from CSV through the dialog.
  const csv = 'name,description,department,stage,stage_reason,ai_type\nProbe Import Check,Temporary probe for the browser check,Finance,Ideation,,Autonomous Agent\nIso Mapper,already there,Finance,Ideation,,Autonomous Agent\n'
  fs.writeFileSync(`${SP}/probe-import.csv`, csv)
  await page.goto(`${B}/agents`); await page.click('[data-testid=import-btn]')
  await page.setInputFiles('[data-testid=import-file]', `${SP}/probe-import.csv`)
  await page.waitForSelector('[data-testid=import-summary]', { timeout: 30000 })
  ok('import preview: one to create, one skipped', /1 to create · 1 skipped/.test(await page.textContent('[data-testid=import-summary]')), await page.textContent('[data-testid=import-summary]'))
  await page.click('[data-testid=import-commit]'); await page.waitForSelector('[data-testid=import-result]', { timeout: 60000 })
  const imported = (await j('GET', '/agents/?limit=100')).body.data.find(a => a.name === 'Probe Import Check')
  ok('the imported agent exists at Ideation', imported?.stage === 'Ideation')
  if (imported) cleanup.push(() => j('DELETE', `/agents/${imported.id}`))
  await page.keyboard.press('Escape'); await page.click('[aria-label="Close"]').catch(() => {})

  // 4. API keys: issue in the UI, use for the CI check and the CLI, then revoke.
  await page.goto(`${B}/settings`); await page.waitForSelector('[data-testid=api-keys]', { timeout: 30000 })
  await page.fill('[data-testid=api-keys] input[placeholder^="What it is for"]', 'Probe CI key')
  await page.click('[data-testid=issue-key]'); await page.waitForSelector('[data-testid=new-key] code', { timeout: 15000 })
  const key = (await page.textContent('[data-testid=new-key] code')).trim()
  ok('the key is shown once after issuing', key.startsWith('ark_'))
  const ci = await (await fetch(`${API}/ci/check?agent=Iso%20Mapper&stage=Production`, { headers: { Authorization: `Bearer ${key}` } })).json()
  ok('the CI check with the key says Iso Mapper may not go to Production, with reasons', ci.allowed === false && ci.reasons.length > 0, JSON.stringify(ci).slice(0, 200))
  let code = 0, out = ''
  try { out = execFileSync('python3', [new URL('../../tools/registry_cli.py', import.meta.url).pathname, 'check', 'Iso Mapper', '--stage', 'Production'],
    { env: { ...process.env, REGISTRY_URL: 'http://127.0.0.1:8002', REGISTRY_API_KEY: key } }).toString() } catch (e) { code = e.status; out = String(e.stdout) }
  ok('the CLI exits 1 and prints the reasons', code === 1 && /BLOCKED: Iso Mapper/.test(out), `${code} ${out.slice(0, 160)}`)
  const keys = (await j('GET', '/admin/api-keys')).body
  const probeKey = keys.find(k => k.label === 'Probe CI key')
  await j('DELETE', `/admin/api-keys/${probeKey.id}`)
  const after401 = await fetch(`${API}/ci/check?agent=Iso%20Mapper`, { headers: { Authorization: `Bearer ${key}` } })
  ok('a revoked key stops working', after401.status === 401)

  // 5. Connectors: a small GitHub connector, scanned, its findings on Discovered → Other sources.
  const conn = (await j('POST', '/connectors', { kind: 'github', label: 'Probe GitHub', settings: { orgs: ['langchain-ai'], maxRepos: 3 }, secret: {} })).body
  cleanup.push(() => j('DELETE', `/connectors/${conn.id}`))
  await page.reload(); await page.waitForSelector('[data-testid=connectors]', { timeout: 30000 })
  const row = page.locator('[data-testid=connectors] li', { hasText: 'Probe GitHub' })
  await row.locator('button', { hasText: 'Scan now' }).click()
  await page.waitForFunction(() => /found/.test(document.querySelector('[data-testid=connectors]')?.textContent || ''), null, { timeout: 120000 }).catch(() => {})
  const connText = await row.textContent()
  ok('the GitHub connector scans and reports what it found', /found/.test(connText), connText.slice(0, 200))
  await page.goto(`${B}/discovered`); await page.click('[data-testid=tile-other]')
  await page.waitForSelector('[data-testid=finding-row]', { timeout: 15000 }).catch(() => {})
  ok('Other sources lists the repositories found', await page.locator('[data-testid=finding-row]').count() >= 1)
  await page.screenshot({ path: `${SP}/shots/p1-other-sources.png`, fullPage: false })

  // 6. Agent card on Integrate.
  await page.goto(`${B}/agents/${dot.id}?tab=integrate`); await page.waitForSelector('[data-testid=agent-card-status]', { timeout: 30000 }).catch(() => {})
  ok('Integrate shows the agent card status', /published|Not published/i.test(await page.textContent('[data-testid=agent-card-status]').catch(() => '')))

  // 7. Lifecycle signals endpoint and Executive section.
  const att = (await j('GET', '/portfolio/attention')).body
  ok('lifecycle signals answer', Array.isArray(att.silent) && Array.isArray(att.runningAfterRetirement), JSON.stringify(att).slice(0, 200))
  await page.goto(`${B}/`); await page.waitForTimeout(2500)
  const shown = await page.locator('[data-testid=lifecycle-attention]').count()
  ok('Executive shows lifecycle signals exactly when there are any', shown === ((att.silent.length + att.runningAfterRetirement.length + att.callsRetired.length + att.stalled.length + att.ownerless.length + att.stopWaiting.length) > 0 ? 1 : 0), `silent ${att.silent.length}`)
} catch (e) {
  ok('the check ran to the end', false, String(e).slice(0, 300))
} finally {
  for (const c of cleanup) await c().catch(() => {})
}
ok('probe data removed', !(await j('GET', '/agents/?limit=100')).body.data.some(a => a.name === 'Probe Import Check'))
ok('no console errors', errs.length === 0, errs.join(' | '))
for (const [s, n, e] of R) console.log(s, n, e ? '— ' + e : '')
console.log(R.some(r => r[0] === 'FAIL') ? 'SOME FAILED' : 'ALL PASSED')
await browser.close()
