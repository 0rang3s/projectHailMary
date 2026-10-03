import { shortDate } from '../format'
import type { DatesResponse } from '../types'

interface Props {
  catalog: DatesResponse | null
  selected: string
  playing: boolean
  onSelect: (id: string) => void
  onTogglePlay: () => void
  drawerOpen: boolean
  onToggleDrawer: () => void
}

export default function TopBar({
  catalog,
  selected,
  playing,
  onSelect,
  onTogglePlay,
  drawerOpen,
  onToggleDrawer,
}: Props) {
  const stops = catalog
    ? [
        ...catalog.flood_dates.map((date) => ({ id: date, label: shortDate(date) })),
        { id: 'normal', label: `Normal (${shortDate(catalog.normal_date)})` },
      ]
    : []

  return (
    <header className="pointer-events-auto absolute left-4 right-4 top-4 z-20 flex flex-wrap items-center gap-4 rounded-2xl border border-white/10 bg-slate-950/80 px-4 py-3 shadow-2xl backdrop-blur-md">
      <div className="flex min-w-0 items-center gap-3">
        <span className="h-9 w-1 shrink-0 rounded-full bg-sky-400" />
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-white">Cut Off</h1>
          <p className="text-xs leading-snug text-slate-300">
            Radar view of the 2025 Albany River ice-jam flood · Fort Albany & Kashechewan First Nations
          </p>
        </div>
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-1 rounded-full bg-white/5 p-1">
          {stops.length === 0 && <span className="px-3 py-1 text-sm text-slate-400">Loading dates…</span>}
          {stops.map((stop) => {
            const active = selected === stop.id
            return (
              <button
                key={stop.id}
                type="button"
                onClick={() => onSelect(stop.id)}
                className={`rounded-full px-3 py-1.5 text-sm font-medium transition ${
                  active ? 'bg-sky-400 text-slate-950' : 'text-slate-200 hover:bg-white/10'
                }`}
              >
                {stop.label}
              </button>
            )
          })}
        </div>
        <button
          type="button"
          onClick={onTogglePlay}
          disabled={!catalog}
          className="rounded-full border border-white/10 px-3 py-1.5 text-sm font-medium text-white hover:bg-white/10 disabled:opacity-40"
        >
          {playing ? 'Pause' : 'Play'}
        </button>
        <button
          type="button"
          onClick={onToggleDrawer}
          className={`rounded-full px-3 py-1.5 text-sm font-medium ${
            drawerOpen ? 'bg-white/15 text-white' : 'bg-sky-400 text-slate-950'
          }`}
        >
          Ask Cut Off
        </button>
      </div>
    </header>
  )
}
