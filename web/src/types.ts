export type Status = 'red' | 'yellow' | 'green' | 'no_data'

export interface Stats {
  mock: boolean
  normal_date: string
  flood_date: string
  normal_water_km2: number
  flood_water_km2: number
  extra_water_km2: number
  lifelines_red: number
  lifelines_yellow: number
  lifelines_no_data: number
}

export interface Lifeline {
  id: string
  name: string
  type: string
  lat: number
  lon: number
  verified: boolean
  source: string
  status: Status
  dist_flood_m: number | null
  dist_normal_m: number | null
  closer_by_m: number | null
}

export interface IceTown {
  river_km2_seen: number
  pct_frozen: number | null
}

export interface Ice {
  river_km2_seen: number
  pct_frozen_overall: number | null
  near_towns: Record<string, IceTown>
  upstream_pct_frozen: number | null
  jam_risk: boolean
  jam_towns: string[]
  rule: string
}

export interface Summary {
  stats: Stats
  ice: Ice | null
  lifelines: Lifeline[]
  alert: { text: string; source: string; mock?: boolean } | null
}

export interface DatesResponse {
  flood_dates: string[]
  normal_date: string
}

import type { FeatureCollection as GeoFeatureCollection } from 'geojson'

export type FeatureCollection = GeoFeatureCollection

export interface ToolUse {
  name: string
  input: Record<string, unknown>
}

export interface AskResponse {
  answer: string
  tools_used: ToolUse[]
  dates_cited: string[]
}

export interface AudienceAlert {
  text: string
  source: string
}

export type Audience = 'coordinator' | 'community' | 'pilots'

export interface DateLayers {
  extra: FeatureCollection
  ice: FeatureCollection
}
