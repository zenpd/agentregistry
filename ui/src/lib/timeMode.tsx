import { useEffect, useState } from 'react'

// Job times are stored as UTC clock times. People read them in their own time
// zone by default; a switch shows the UTC times for anyone who needs them.
export type TimeMode = 'local' | 'utc'
const KEY = 'ar-time-mode'
const EVENT = 'ar-time-mode-changed'

function read(): TimeMode {
  try { return localStorage.getItem(KEY) === 'utc' ? 'utc' : 'local' } catch { return 'local' }
}

export function useTimeMode(): [TimeMode, (m: TimeMode) => void] {
  const [mode, setMode] = useState<TimeMode>(read)
  useEffect(() => {
    const sync = () => setMode(read())
    window.addEventListener(EVENT, sync)
    return () => window.removeEventListener(EVENT, sync)
  }, [])
  return [mode, (m: TimeMode) => {
    try { localStorage.setItem(KEY, m) } catch { /* the choice just is not remembered */ }
    window.dispatchEvent(new Event(EVENT))
  }]
}

/** "01:00" (a UTC clock time) as the time to show: in the viewer's time zone, or still UTC. */
export function clockTime(utcHHMM: string, mode: TimeMode): string {
  if (mode === 'utc') return `${utcHHMM} UTC`
  const [h, m] = utcHHMM.split(':').map(Number)
  if (Number.isNaN(h) || Number.isNaN(m)) return utcHHMM
  const d = new Date(Date.UTC(2026, 0, 15, h, m))   // a date outside any daylight-saving change
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}

export function zoneName(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone } catch { return 'your time zone' }
}

export function TimeModeToggle() {
  const [mode, setMode] = useTimeMode()
  const opt = (m: TimeMode, label: string) => (
    <button type="button" onClick={() => setMode(m)} aria-pressed={mode === m} data-testid={`time-${m}`}
      className={`px-2.5 py-1 text-[12px] font-semibold ${mode === m ? 'bg-zen-600 text-white' : 'bg-white text-slate-700 hover:bg-slate-50'}`}>{label}</button>
  )
  return (
    <div className="inline-flex items-center gap-2 text-[12.5px] text-slate-600" data-testid="time-toggle">
      Show times in
      <span className="inline-flex overflow-hidden rounded-lg ring-1 ring-slate-200">{opt('local', `My time (${zoneName()})`)}{opt('utc', 'UTC')}</span>
    </div>
  )
}
