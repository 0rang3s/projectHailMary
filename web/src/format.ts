import type { Status } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function shortDate(iso: string) {
  const [, month, day] = iso.split('-').map(Number)
  return `${MONTHS[(month || 1) - 1]} ${day}`
}

export function statusFromMeters(meters: number | null): Status {
  if (meters == null) return 'no_data'
  if (meters <= 200) return 'red'
  if (meters <= 1000) return 'yellow'
  return 'green'
}

export function statusLabel(status: Status) {
  if (status === 'red') return '≤ 200 m'
  if (status === 'yellow') return '≤ 1 km'
  if (status === 'green') return 'Clear'
  return 'No data'
}

export function townPct(towns: Record<string, { pct_frozen: number | null }>, needle: string) {
  const hit = Object.entries(towns).find(([name]) => name.toLowerCase().includes(needle))
  return hit?.[1]?.pct_frozen ?? null
}

export function shortTown(name: string) {
  return name.split(' (')[0]
}
