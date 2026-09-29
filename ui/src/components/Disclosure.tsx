import { useState } from 'react'

// One quiet line that states the point, with the explanation behind
// "Details" — for standing information that should not shout on every visit.
export default function Disclosure({ summary, children, tone = 'muted', testId }: {
  summary: React.ReactNode; children: React.ReactNode; tone?: 'muted' | 'warn'; testId?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`text-xs ${tone === 'warn' ? 'text-amber-800' : 'text-gray-500'}`} data-testid={testId}>
      <span>{summary}</span>{' '}
      <button type="button" className="font-semibold underline hover:no-underline" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        {open ? 'Hide' : 'Details'}
      </button>
      {open && (
        <div className={`mt-1.5 rounded-lg px-3 py-2 ${tone === 'warn' ? 'bg-amber-50 ring-1 ring-amber-200 text-amber-900' : 'bg-gray-50 ring-1 ring-gray-200 text-gray-600'}`}>
          {children}
        </div>
      )}
    </div>
  )
}
