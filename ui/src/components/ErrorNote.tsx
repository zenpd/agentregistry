import { useState } from 'react'
import { AlertTriangle, X } from 'lucide-react'

// An error, shown only when something failed: the short message first, the
// advice behind "What can I do?", and a way to dismiss it.
export default function ErrorNote({ message, hint, onDismiss, testId }: {
  message: string; hint?: string | null; onDismiss?: () => void; testId?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900" role="alert" data-testid={testId}>
      <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600" />
      <div className="flex-1 min-w-0">
        <p>{message}</p>
        {hint && (
          open
            ? <p className="mt-1 text-amber-800/90">{hint}</p>
            : <button type="button" className="mt-0.5 font-semibold underline hover:no-underline" onClick={() => setOpen(true)}>What can I do?</button>
        )}
      </div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="shrink-0 text-amber-700 hover:text-amber-900" aria-label="Dismiss"><X size={14} /></button>
      )}
    </div>
  )
}
