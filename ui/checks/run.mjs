// Runs the given browser checks one after another, with a pause between them so the
// per-person request limit (1,000 a minute by default) starts fresh for each.
import { execFileSync } from 'node:child_process'
const SP = process.argv[2]
const names = process.argv.slice(3)
for (const [i, n] of names.entries()) {
  if (i > 0) await new Promise(r => setTimeout(r, 65000))
  let out
  try { out = execFileSync('node', [`${new URL('.', import.meta.url).pathname}${n}`, SP], { cwd: SP, timeout: 600000 }).toString() } catch (e) { out = String(e.stdout || e) }
  const lines = out.trim().split('\n')
  const fails = lines.filter(l => l.startsWith('FAIL'))
  console.log(`== ${n}: ${lines.filter(l => l.startsWith('PASS')).length} passed, ${fails.length} failed, ${lines[lines.length - 1]}`)
  for (const f of fails) console.log('   ' + f)
}
