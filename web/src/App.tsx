import { useEffect, useState } from 'react'
import { getDateLayers, getDates, getNormalLayer, getSummary } from './api'
import BottomChart from './components/BottomChart'
import ChatDrawer from './components/ChatDrawer'
import LeftPanel from './components/LeftPanel'
import Legend from './components/Legend'
import MapView from './components/MapView'
import TopBar from './components/TopBar'
import type { DatesResponse, FeatureCollection, Summary } from './types'

interface Focus {
  id: string
  lon: number
  lat: number
  nonce: number
}

export default function App() {
  const [catalog, setCatalog] = useState<DatesResponse | null>(null)
  const [summaries, setSummaries] = useState<Record<string, Summary>>({})
  const [normalLayer, setNormalLayer] = useState<FeatureCollection | null>(null)
  const [layers, setLayers] = useState<Record<string, { extra: FeatureCollection; ice: FeatureCollection }>>({})
  const [selected, setSelected] = useState('normal')
  const [playing, setPlaying] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(true)
  const [selectedLifeline, setSelectedLifeline] = useState<string | null>(null)
  const [focus, setFocus] = useState<Focus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancel = false
    async function load() {
      try {
        const dates = await getDates()
        if (cancel) return
        setCatalog(dates)
        setSelected(dates.flood_dates[0] ?? 'normal')
        const [summaryList, normal, dateLayers] = await Promise.all([
          Promise.all(dates.flood_dates.map((date) => getSummary(date))),
          getNormalLayer(),
          Promise.all(dates.flood_dates.map(async (date) => ({ date, ...(await getDateLayers(date)) }))),
        ])
        if (cancel) return
        const nextSummaries: Record<string, Summary> = {}
        dates.flood_dates.forEach((date, index) => {
          nextSummaries[date] = summaryList[index]
        })
        const nextLayers: Record<string, { extra: FeatureCollection; ice: FeatureCollection }> = {}
        dateLayers.forEach((entry) => {
          nextLayers[entry.date] = { extra: entry.extra, ice: entry.ice }
        })
        setSummaries(nextSummaries)
        setNormalLayer(normal)
        setLayers(nextLayers)
        setLoading(false)
      } catch (err) {
        if (!cancel) {
          setError(err instanceof Error ? err.message : 'The API could not be reached.')
          setLoading(false)
        }
      }
    }
    void load()
    return () => {
      cancel = true
    }
  }, [])

  useEffect(() => {
    if (!playing || !catalog) return
    const stops = [...catalog.flood_dates, 'normal']
    const timer = window.setInterval(() => {
      setSelected((current) => {
        const index = stops.indexOf(current)
        return stops[(index + 1) % stops.length]
      })
    }, 2000)
    return () => window.clearInterval(timer)
  }, [playing, catalog])

  function selectDate(id: string) {
    setPlaying(false)
    setSelected(id)
  }

  function selectLifelineFromMap(id: string) {
    setSelectedLifeline(id)
  }

  function selectLifelineFromCard(id: string) {
    setSelectedLifeline(id)
    const pool = Object.values(summaries)[0]?.lifelines ?? []
    const item = pool.find((lifeline) => lifeline.id === id)
    if (!item) return
    setFocus({ id, lon: item.lon, lat: item.lat, nonce: Date.now() })
  }

  const baseline = catalog ? summaries[catalog.flood_dates[0]] ?? null : null
  const summary = selected === 'normal' ? null : summaries[selected] ?? null
  const lifelines = (selected === 'normal' ? baseline?.lifelines : summary?.lifelines) ?? []

  return (
    <div className="relative h-full w-full overflow-hidden bg-slate-950 text-slate-100">
      <MapView
        normal={normalLayer}
        layers={layers}
        floodDates={catalog?.flood_dates ?? []}
        selected={selected}
        normalDate={catalog?.normal_date ?? null}
        lifelines={lifelines}
        selectedLifeline={selectedLifeline}
        focus={focus}
        onSelectLifeline={selectLifelineFromMap}
      />
      <TopBar
        catalog={catalog}
        selected={selected}
        playing={playing}
        onSelect={selectDate}
        onTogglePlay={() => setPlaying((value) => !value)}
        drawerOpen={drawerOpen}
        onToggleDrawer={() => setDrawerOpen((value) => !value)}
      />
      <LeftPanel
        selected={selected}
        normalDate={catalog?.normal_date ?? null}
        summary={summary}
        baseline={baseline}
        loading={loading && !error}
        selectedLifeline={selectedLifeline}
        onSelectLifeline={selectLifelineFromCard}
      />
      <ChatDrawer open={drawerOpen} selected={selected} onClose={() => setDrawerOpen(false)} />
      <Legend />
      <BottomChart
        summaries={summaries}
        dates={catalog?.flood_dates ?? []}
        selected={selected}
        onSelect={selectDate}
        loading={loading && !error}
      />
      {error && (
        <div className="pointer-events-auto absolute left-1/2 top-28 z-30 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 rounded-2xl border border-red-400/40 bg-slate-950/95 p-4 text-sm shadow-2xl">
          <p className="font-medium text-white">Can&apos;t reach the API.</p>
          <p className="mt-1 text-slate-300">{error}</p>
          <p className="mt-2 text-slate-400">Start it with uvicorn api.main:app --reload</p>
        </div>
      )}
    </div>
  )
}
