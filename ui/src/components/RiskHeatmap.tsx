// Category x Severity grid — the classic risk-heatmap shape, cell color
// intensity driven by count so a reviewer's eye goes straight to the
// worst category/severity combination without reading numbers first.
interface HeatCell {
  category: string
  label: string
  counts: Record<string, number>
}

interface Props {
  rows: HeatCell[]
  severities: string[]
}

const SEVERITY_BASE_COLOR: Record<string, string> = {
  LOW: '16, 185, 129',      // emerald
  MEDIUM: '245, 158, 11',   // amber
  HIGH: '249, 115, 22',     // orange
  CRITICAL: '225, 29, 72',  // rose
}

export default function RiskHeatmap({ rows, severities }: Props) {
  const max = Math.max(1, ...rows.flatMap(r => severities.map(s => r.counts[s] || 0)))

  return (
    <div className="overflow-x-auto">
      <table className="text-xs border-separate" style={{ borderSpacing: 4 }}>
        <thead>
          <tr>
            <th className="text-left font-medium text-gray-400 pr-2 pb-1"></th>
            {severities.map(s => (
              <th key={s} className="font-medium text-gray-400 pb-1 px-1" style={{ minWidth: 56 }}>{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.category}>
              <td className="text-gray-600 font-medium pr-2 whitespace-nowrap">{row.label}</td>
              {severities.map(s => {
                const count = row.counts[s] || 0
                const intensity = count === 0 ? 0.04 : 0.15 + 0.65 * (count / max)
                const rgb = SEVERITY_BASE_COLOR[s] || '107, 114, 128'
                return (
                  <td key={s}>
                    <div
                      className="rounded-lg flex items-center justify-center font-mono font-semibold"
                      style={{
                        width: 56, height: 36,
                        backgroundColor: `rgba(${rgb}, ${intensity})`,
                        color: count > 0 ? `rgb(${rgb})` : '#d1d5db',
                      }}
                      title={`${row.label} · ${s}: ${count}`}
                    >
                      {count || ''}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
