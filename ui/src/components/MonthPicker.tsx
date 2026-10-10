import { useState } from 'react'

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export interface PeriodPreset { key: string; label: string }

// A year and a period. For the current year the period is one of the presets (for example "Last 30 days") or a
// month up to the present one. For an earlier year it is a month. value is a preset key or "YYYY-MM".
export default function MonthPicker({ value, onChange, presets, testId = 'period-picker' }: {
  value: string; onChange: (value: string) => void; presets: PeriodPreset[]; testId?: string
}) {
  const now = new Date()
  const thisYear = now.getFullYear(), thisMonth = now.getMonth() + 1
  const isMonth = /^\d{4}-\d{2}$/.test(value)
  const [year, setYear] = useState<number>(isMonth ? Number(value.slice(0, 4)) : thisYear)
  const years = [thisYear - 2, thisYear - 1, thisYear]
  const key = (y: number, m: number) => `${y}-${String(m).padStart(2, '0')}`
  const months = MONTHS.slice(0, year === thisYear ? thisMonth : 12)

  function changeYear(y: number) {
    setYear(y)
    // The current year opens on its first preset. An earlier year has months only, so it opens on its last month.
    onChange(y === thisYear ? presets[0].key : key(y, 12))
  }
  return (
    <div className="inline-flex flex-wrap items-center gap-1.5" data-testid={testId}>
      <select className="input !w-auto !py-0.5 !text-xs" aria-label="Year" value={year} onChange={e => changeYear(Number(e.target.value))}>
        {years.map(y => <option key={y} value={y}>{y}</option>)}
      </select>
      <select className="input !w-auto !py-0.5 !text-xs" aria-label="Period" value={value} onChange={e => onChange(e.target.value)}>
        {year === thisYear && presets.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
        {months.map((n, i) => <option key={n} value={key(year, i + 1)}>{n}</option>)}
      </select>
    </div>
  )
}

export const isMonthKey = (value: string) => /^\d{4}-\d{2}$/.test(value)

export function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return `${MONTHS[m - 1]} ${y}`
}
