// Hand-rolled SVG pie chart, no charting library (matches this codebase's
// existing convention — BarChart/NetworkGraph are hand-rolled too, and
// package.json carries no chart dependency to build on).
interface Slice {
  label: string
  count: number
  color: string
}

interface Props {
  data: Slice[]
  size?: number
}

export default function RiskPie({ data, size = 180 }: Props) {
  const total = data.reduce((s, d) => s + d.count, 0)
  const r = size / 2
  const cx = r
  const cy = r

  if (total === 0) {
    return (
      <div style={{ width: size, height: size }} className="flex items-center justify-center rounded-full border-2 border-dashed border-gray-200 text-xs text-gray-400 text-center px-4">
        No open findings
      </div>
    )
  }

  let angle = -90 // start at 12 o'clock
  const slices = data
    .filter(d => d.count > 0)
    .map(d => {
      const sweep = (d.count / total) * 360
      const startAngle = angle
      const endAngle = angle + sweep
      angle = endAngle
      const large = sweep > 180 ? 1 : 0
      const toXY = (deg: number) => {
        const rad = (deg * Math.PI) / 180
        return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]
      }
      const [x1, y1] = toXY(startAngle)
      const [x2, y2] = toXY(endAngle)
      const path = sweep >= 359.99
        ? `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z` // full circle edge case
        : `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`
      return { ...d, path }
    })

  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {slices.map(s => (
          <path key={s.label} d={s.path} fill={s.color} stroke="#ffffff" strokeWidth={1.5} opacity={0.9}>
            <title>{s.label}: {s.count}</title>
          </path>
        ))}
        <circle cx={cx} cy={cy} r={r * 0.45} fill="#ffffff" />
        <text x={cx} y={cy - 4} textAnchor="middle" fontSize={20} fontWeight={700} fill="#111827" fontFamily="Inter">{total}</text>
        <text x={cx} y={cy + 14} textAnchor="middle" fontSize={9} fill="#9ca3af" fontFamily="Inter">findings</text>
      </svg>
      <div className="space-y-1.5">
        {data.map(d => (
          <div key={d.label} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: d.color }} />
            <span className="text-gray-600">{d.label}</span>
            <span className="text-gray-400 font-mono">{d.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
