import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { shortDate } from '../format'
import type { Summary } from '../types'

interface Props {
  summaries: Record<string, Summary>
  dates: string[]
  selected: string
  onSelect: (date: string) => void
  loading: boolean
}

export default function BottomChart({ summaries, dates, selected, onSelect, loading }: Props) {
  const rows = dates.map((date) => {
    const summary = summaries[date]
    const frozenValues = summary
      ? Object.values(summary.ice?.near_towns ?? {})
          .map((town) => town.pct_frozen)
          .filter((value): value is number => value != null)
      : []
    return {
      date,
      label: shortDate(date),
      extra: summary?.stats.extra_water_km2 ?? null,
      frozen: frozenValues.length ? Math.max(...frozenValues) : null,
    }
  })

  return (
    <section className="pointer-events-auto absolute bottom-4 left-4 right-4 z-20 h-36 rounded-2xl border border-white/10 bg-slate-950/80 px-4 py-2 shadow-2xl backdrop-blur-md">
      <div className="flex items-center justify-between text-xs text-slate-300">
        <span className="font-medium text-slate-100">Across the flood</span>
        <span className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-slate-400" /> Extra water (km²)
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-0.5 w-3 bg-sky-400" /> Frozen near towns (%)
          </span>
        </span>
      </div>
      <div className="h-24">
        {loading ? (
          <div className="mt-3 h-16 animate-pulse rounded-lg bg-white/10" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={rows}
              margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
              onClick={(state) => {
                const date = state?.activePayload?.[0]?.payload?.date as string | undefined
                if (date) onSelect(date)
              }}
            >
              <CartesianGrid vertical={false} stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="label"
                axisLine={false}
                tickLine={false}
                tick={(props) => {
                  const { x, y, payload, index } = props as {
                    x: number
                    y: number
                    payload: { value: string }
                    index: number
                  }
                  const row = rows[index]
                  return (
                    <text
                      x={x}
                      y={y}
                      dy={14}
                      textAnchor="middle"
                      fill={row?.date === selected ? '#38bdf8' : '#cbd5e1'}
                      fontSize={12}
                      style={{ cursor: 'pointer' }}
                      onClick={() => row && onSelect(row.date)}
                    >
                      {payload.value}
                    </text>
                  )
                }}
              />
              <YAxis
                yAxisId="water"
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={32}
              />
              <YAxis
                yAxisId="ice"
                orientation="right"
                domain={[0, 100]}
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={28}
              />
              <Tooltip
                contentStyle={{ background: '#020617', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 12 }}
                labelStyle={{ color: '#e2e8f0' }}
              />
              <Bar
                yAxisId="water"
                dataKey="extra"
                name="Extra water (km²)"
                radius={[4, 4, 0, 0]}
                cursor="pointer"
                onClick={(row) => {
                  const date = (row as { date?: string }).date
                  if (date) onSelect(date)
                }}
              >
                {rows.map((row) => (
                  <Cell key={row.date} fill={row.date === selected ? '#38bdf8' : '#64748b'} />
                ))}
              </Bar>
              <Line
                yAxisId="ice"
                type="monotone"
                dataKey="frozen"
                name="Frozen near towns (%)"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={{ r: 3, fill: '#38bdf8' }}
                connectNulls={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  )
}
