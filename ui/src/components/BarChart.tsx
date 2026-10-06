interface BarChartProps {
  data: { label: string; value: number }[]
  // How a value reads at the end of its bar, e.g. fmtMoney. Defaults to a count.
  format?: (value: number) => string
  // One measure per category is one series, so every bar shares one hue; the
  // label, not the colour, says which category it is.
  color?: string
  // Accessible name for the chart as a whole.
  label?: string
}

// Horizontal bars, largest first: label | bar | value in one row, so a long
// label never collides with its bar. Plain HTML, so it uses the app's font.
export default function BarChart({ data, format = n => n.toLocaleString(), color = '#6366f1', label }: BarChartProps) {
  const rows = [...data].sort((a, b) => b.value - a.value)
  const max = Math.max(...rows.map(d => d.value), 1)
  return (
    <ul className="space-y-2" aria-label={label}>
      {rows.map(d => (
        <li key={d.label} className="grid grid-cols-[minmax(0,38%)_1fr_4.5rem] items-center gap-3" title={`${d.label}: ${format(d.value)}`}>
          <span className="truncate text-[13px] text-slate-700">{d.label}</span>
          <span className="h-4 rounded-r bg-gray-100">
            {d.value > 0 && (
              <span className="block h-full rounded-r" style={{ width: `${(d.value / max) * 100}%`, background: color }} />
            )}
          </span>
          <span className="text-right font-mono text-[12px] tabular-nums text-slate-900">{format(d.value)}</span>
        </li>
      ))}
    </ul>
  )
}
