import { useState } from 'react'

interface BarChartProps {
  data: { label: string; value: number; color?: string }[]
  width?: number
  height?: number
}

const COLORS = ['#3DDBD9', '#8C7CF0', '#F0A85A', '#57C785', '#6EA8FE', '#E06B85']

export default function BarChart({ data, width = 400, height = 200 }: BarChartProps) {
  const max = Math.max(...data.map(d => d.value), 1)
  const barH = 24
  const gap = 8
  const chartH = data.length * (barH + gap)

  return (
    <svg width={width} height={Math.max(chartH, height)} viewBox={`0 0 ${width} ${Math.max(chartH, height)}`}>
      {data.map((d, i) => {
        const y = i * (barH + gap)
        const w = (d.value / max) * (width - 120)
        const color = d.color || COLORS[i % COLORS.length]
        return (
          <g key={d.label}>
            <text x={width - 124} y={y + 17} textAnchor="end" fill="#8C9AAB" fontSize={12} fontFamily="Inter">
              {d.label}
            </text>
            <rect x={0} y={y} width={w} height={barH} rx={4} fill={color} opacity={0.85} />
            <text x={w + 8} y={y + 17} fill="#E9EEF3" fontSize={11} fontFamily="JetBrains Mono">
              {d.value.toLocaleString()}
            </text>
          </g>
        )
      })}
    </svg>
  )
}