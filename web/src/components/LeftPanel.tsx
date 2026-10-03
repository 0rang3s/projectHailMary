import { useEffect } from 'react'
import { shortDate, shortTown, statusFromMeters, statusLabel, townPct } from '../format'
import type { Ice, Lifeline, Status, Summary } from '../types'

const PILL: Record<Status, string> = {
  red: 'bg-red-500/20 text-red-200',
  yellow: 'bg-amber-500/20 text-amber-200',
  green: 'bg-emerald-500/20 text-emerald-200',
  no_data: 'bg-slate-500/30 text-slate-300',
}

interface Props {
  selected: string
  normalDate: string | null
  summary: Summary | null
  baseline: Summary | null
  loading: boolean
  selectedLifeline: string | null
  onSelectLifeline: (id: string) => void
}

export default function LeftPanel({
  selected,
  normalDate,
  summary,
  baseline,
  loading,
  selectedLifeline,
  onSelectLifeline,
}: Props) {
  const normalMode = selected === 'normal'
  const lifelines = (normalMode ? baseline?.lifelines : summary?.lifelines) ?? []
  const ordered = [...lifelines].sort((a, b) => {
    const da = normalMode ? a.dist_normal_m : a.dist_flood_m
    const db = normalMode ? b.dist_normal_m : b.dist_flood_m
    if (da == null) return 1
    if (db == null) return -1
    return da - db
  })

  useEffect(() => {
    if (!selectedLifeline) return
    document.getElementById(`lifeline-${selectedLifeline}`)?.scrollIntoView({ block: 'nearest' })
  }, [selectedLifeline])

  return (
    <aside className="pointer-events-auto absolute bottom-[10.75rem] left-4 top-[6.5rem] z-20 flex w-[20rem] max-w-[calc(100vw-2rem)] flex-col gap-3 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/80 p-4 shadow-2xl backdrop-blur-md">
      <div>
        <p className="text-xs uppercase tracking-wide text-slate-400">This scene</p>
        <h2 className="text-lg font-semibold text-white">
          {normalMode && normalDate ? `Normal (${shortDate(normalDate)})` : selected ? shortDate(selected) : '—'}
        </h2>
      </div>

      {loading && <Skeleton />}

      {!loading && normalMode && baseline && (
        <div className="rounded-xl border border-white/10 bg-white/5 p-3">
          <p className="text-xs text-slate-400">Normal river extent</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums text-white">
            {baseline.stats.normal_water_km2}
            <span className="ml-1 text-base font-medium text-slate-300">km²</span>
          </p>
          <p className="mt-1 text-sm text-slate-300">
            Summer baseline. Lifelines show the usual gap to the river.
          </p>
        </div>
      )}

      {!loading && !normalMode && summary && (
        <>
          {summary.ice?.jam_risk && <JamCard ice={summary.ice} />}
          <div className="rounded-xl border border-white/10 bg-white/5 p-3">
            <p className="text-xs text-slate-400">Extra water vs normal</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums text-white">
              {summary.stats.extra_water_km2}
              <span className="ml-1 text-base font-medium text-slate-300">km²</span>
            </p>
            <p className="mt-1 text-sm text-slate-300">
              Open water {summary.stats.flood_water_km2} km² · normal river {summary.stats.normal_water_km2} km²
            </p>
          </div>
        </>
      )}

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-slate-300">Lifelines</h3>
        {ordered.map((item) => (
          <LifelineCard
            key={item.id}
            item={item}
            normalMode={normalMode}
            active={selectedLifeline === item.id}
            onSelect={onSelectLifeline}
          />
        ))}
      </div>

      {!loading && !normalMode && summary?.ice && <Gauges ice={summary.ice} />}
    </aside>
  )
}

function JamCard({ ice }: { ice: Ice }) {
  const kashechewan = townPct(ice.near_towns, 'kashechewan')
  const albany = townPct(ice.near_towns, 'fort albany')
  const parts = [
    kashechewan != null ? `${kashechewan}% frozen near Kashechewan` : null,
    albany != null ? `${albany}% near Fort Albany` : null,
  ].filter(Boolean)
  const upstream = ice.upstream_pct_frozen != null ? `, only ${ice.upstream_pct_frozen}% upstream` : ''
  return (
    <div className="rounded-xl border border-red-400/50 bg-red-950/70 p-3 text-sm leading-relaxed text-red-50">
      Ice-jam pattern: river {parts.join(', ')}
      {upstream}.
      <p className="mt-2 text-red-100/80">Open water can&apos;t be seen under the ice.</p>
    </div>
  )
}

function LifelineCard({
  item,
  normalMode,
  active,
  onSelect,
}: {
  item: Lifeline
  normalMode: boolean
  active: boolean
  onSelect: (id: string) => void
}) {
  const dist = normalMode ? item.dist_normal_m : item.dist_flood_m
  const status = normalMode ? statusFromMeters(item.dist_normal_m) : item.status
  const closer = item.closer_by_m
  return (
    <button
      id={`lifeline-${item.id}`}
      type="button"
      onClick={() => onSelect(item.id)}
      className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
        active ? 'border-sky-400 bg-sky-400/10 ring-2 ring-sky-400' : 'border-white/10 bg-white/5 hover:bg-white/10'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-medium text-white">{item.name}</p>
          <p className="text-xs capitalize text-slate-400">{item.type}</p>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${PILL[status]}`}>
          {statusLabel(status)}
        </span>
      </div>
      <p className="mt-2 text-sm tabular-nums text-slate-200">
        {dist == null ? 'Not covered by this scene' : `${dist} m to water`}
        {!normalMode && item.dist_normal_m != null ? ` · normally ${item.dist_normal_m} m` : ''}
      </p>
      {!normalMode && closer != null && dist != null && (
        <p className="text-xs text-slate-400">
          {closer > 0 ? `closer by ${closer} m` : closer < 0 ? `farther by ${Math.abs(closer)} m` : 'same distance as normal'}
        </p>
      )}
      {!item.verified && <p className="mt-1 text-xs text-amber-200/90">approx. location</p>}
    </button>
  )
}

function Gauges({ ice }: { ice: Ice }) {
  const rows = [
    ...Object.entries(ice.near_towns).map(([name, value]) => ({
      label: `${shortTown(name)} (5 km)`,
      pct: value.pct_frozen,
    })),
    { label: 'Upstream (15+ km)', pct: ice.upstream_pct_frozen },
  ]
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-slate-300">River ice</h3>
      {rows.map((row) => (
        <div key={row.label}>
          <div className="flex justify-between text-xs text-slate-300">
            <span>{row.label}</span>
            <span className="tabular-nums">{row.pct == null ? '—' : `${row.pct}%`}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-sky-400 transition-all duration-500"
              style={{ width: `${Math.max(0, Math.min(100, row.pct ?? 0))}%` }}
            />
          </div>
        </div>
      ))}
      <p className="text-xs leading-relaxed text-slate-400">{ice.rule}</p>
    </div>
  )
}

function Skeleton() {
  return (
    <div className="space-y-3">
      <div className="h-24 animate-pulse rounded-xl bg-white/10" />
      <div className="h-16 animate-pulse rounded-xl bg-white/10" />
      <div className="h-16 animate-pulse rounded-xl bg-white/10" />
    </div>
  )
}
