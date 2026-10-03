import { useEffect, useMemo, useRef, useState } from 'react'
import Map, { Layer, ScaleControl, Source, type MapLayerMouseEvent, type MapRef } from 'react-map-gl/maplibre'
import type { FeatureCollection, Lifeline, Status } from '../types'
import { statusFromMeters } from '../format'

const MAP_STYLE = {
  version: 8 as const,
  sources: {
    esri: {
      type: 'raster' as const,
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      ],
      tileSize: 256,
      attribution:
        'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    },
  },
  layers: [{ id: 'esri', type: 'raster' as const, source: 'esri' }],
}

const STATUS_COLOR: Record<Status, string> = {
  red: '#ef4444',
  yellow: '#f59e0b',
  green: '#22c55e',
  no_data: '#94a3b8',
}

interface Hover {
  x: number
  y: number
  text: string
}

interface Focus {
  id: string
  lon: number
  lat: number
  nonce: number
}

interface Props {
  normal: FeatureCollection | null
  layers: Record<string, { extra: FeatureCollection; ice: FeatureCollection }>
  floodDates: string[]
  selected: string
  normalDate: string | null
  lifelines: Lifeline[]
  selectedLifeline: string | null
  focus: Focus | null
  onSelectLifeline: (id: string) => void
}

export default function MapView({
  normal,
  layers,
  floodDates,
  selected,
  normalDate,
  lifelines,
  selectedLifeline,
  focus,
  onSelectLifeline,
}: Props) {
  const mapRef = useRef<MapRef>(null)
  const [hover, setHover] = useState<Hover | null>(null)
  const normalMode = selected === 'normal'
  const when = normalMode ? `normal ${normalDate ?? ''}` : selected

  const points = useMemo(() => {
    return {
      type: 'FeatureCollection' as const,
      features: lifelines.map((item) => {
        const dist = normalMode ? item.dist_normal_m : item.dist_flood_m
        const status = normalMode ? statusFromMeters(item.dist_normal_m) : item.status
        const text =
          dist == null
            ? `${item.name} — not covered by this scene · ${when}`
            : normalMode
              ? `${item.name} — ${dist} m to water · ${when}`
              : `${item.name} — ${dist} m to water (normally ${item.dist_normal_m ?? '—'} m) · ${when}`
        return {
          type: 'Feature' as const,
          properties: {
            id: item.id,
            status,
            text,
          },
          geometry: { type: 'Point' as const, coordinates: [item.lon, item.lat] },
        }
      }),
    }
  }, [lifelines, normalMode, when])

  useEffect(() => {
    if (!focus) return
    mapRef.current?.flyTo({ center: [focus.lon, focus.lat], zoom: 12, duration: 700 })
  }, [focus])

  function onMove(event: MapLayerMouseEvent) {
    const feature = event.features?.[0]
    const text = feature?.properties?.text
    if (!text) {
      setHover(null)
      return
    }
    setHover({ x: event.point.x, y: event.point.y, text: String(text) })
  }

  return (
    <div className="map-root absolute inset-0">
      <Map
        ref={mapRef}
        initialViewState={{ longitude: -81.8, latitude: 52.215, zoom: 10.5 }}
        mapStyle={MAP_STYLE}
        interactiveLayerIds={['lifelines']}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        onClick={(event) => {
          const id = event.features?.[0]?.properties?.id
          if (id) onSelectLifeline(String(id))
        }}
        cursor={hover ? 'pointer' : 'grab'}
      >
        {normal && (
          <Source id="normal-water" type="geojson" data={normal}>
            <Layer
              id="normal-water-fill"
              type="fill"
              paint={{
                'fill-color': '#38bdf8',
                'fill-opacity': normalMode ? 0.62 : 0.38,
                'fill-opacity-transition': { duration: 550 },
              }}
            />
          </Source>
        )}
        {floodDates.map((date) => {
          const pack = layers[date]
          if (!pack) return null
          const active = !normalMode && selected === date
          return (
            <Source key={`extra-${date}`} id={`extra-${date}`} type="geojson" data={pack.extra}>
              <Layer
                id={`extra-fill-${date}`}
                type="fill"
                paint={{
                  'fill-color': '#e11d48',
                  'fill-opacity': active ? 0.58 : 0,
                  'fill-opacity-transition': { duration: 550 },
                }}
              />
            </Source>
          )
        })}
        {floodDates.map((date) => {
          const pack = layers[date]
          if (!pack) return null
          const active = !normalMode && selected === date
          return (
            <Source key={`ice-${date}`} id={`ice-${date}`} type="geojson" data={pack.ice}>
              <Layer
                id={`ice-fill-${date}`}
                type="fill"
                paint={{
                  'fill-color': '#ffffff',
                  'fill-opacity': active ? 0.88 : 0,
                  'fill-opacity-transition': { duration: 550 },
                }}
              />
              <Layer
                id={`ice-line-${date}`}
                type="line"
                paint={{
                  'line-color': '#22d3ee',
                  'line-width': 1.4,
                  'line-opacity': active ? 1 : 0,
                  'line-opacity-transition': { duration: 550 },
                }}
              />
            </Source>
          )
        })}
        <Source id="lifelines" type="geojson" data={points}>
          <Layer
            id="lifelines"
            type="circle"
            paint={{
              'circle-radius': [
                'case',
                ['==', ['get', 'id'], selectedLifeline ?? ''],
                11,
                8,
              ],
              'circle-color': [
                'match',
                ['get', 'status'],
                'red',
                STATUS_COLOR.red,
                'yellow',
                STATUS_COLOR.yellow,
                'green',
                STATUS_COLOR.green,
                STATUS_COLOR.no_data,
              ],
              'circle-stroke-color': '#020617',
              'circle-stroke-width': [
                'case',
                ['==', ['get', 'id'], selectedLifeline ?? ''],
                3,
                1.5,
              ],
              'circle-opacity': 0.95,
            }}
          />
        </Source>
        <ScaleControl position="bottom-left" />
      </Map>
      {hover && (
        <div
          className="pointer-events-none absolute z-10 max-w-xs rounded-lg border border-white/10 bg-slate-950/90 px-3 py-2 text-sm shadow-xl"
          style={{ left: hover.x + 14, top: hover.y + 14 }}
        >
          {hover.text}
        </div>
      )}
    </div>
  )
}
