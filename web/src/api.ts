import type {
  AskResponse,
  Audience,
  AudienceAlert,
  DatesResponse,
  DateLayers,
  FeatureCollection,
  Summary,
} from './types'

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
    if (body.detail) return JSON.stringify(body.detail)
  } catch {
    /* response was not JSON */
  }
  return res.statusText || 'Request failed'
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!res.ok) throw new Error(await readError(res))
  const type = res.headers.get('content-type') || ''
  if (type.includes('text/markdown') || type.includes('text/plain')) {
    return (await res.text()) as T
  }
  return res.json() as Promise<T>
}

export function getDates() {
  return api<DatesResponse>('/api/dates')
}

export function getSummary(date: string) {
  return api<Summary>(`/api/dates/${encodeURIComponent(date)}/summary`)
}

export function getNormalLayer() {
  return api<FeatureCollection>('/api/layers/normal')
}

export function getLayer(date: string, kind: 'extra' | 'ice' | 'water') {
  return api<FeatureCollection>(`/api/dates/${encodeURIComponent(date)}/layers/${kind}`)
}

export async function getDateLayers(date: string): Promise<DateLayers> {
  const [extra, ice] = await Promise.all([getLayer(date, 'extra'), getLayer(date, 'ice')])
  return { extra, ice }
}

export function askQuestion(question: string, history: { role: 'user' | 'assistant'; content: string }[]) {
  return api<AskResponse>('/api/ask', {
    method: 'POST',
    body: JSON.stringify({ question, history }),
  })
}

export function getAudienceAlert(date: string, audience: Audience) {
  return api<AudienceAlert>('/api/alert', {
    method: 'POST',
    body: JSON.stringify({ date, audience }),
  })
}

export function getReport() {
  return api<string>('/api/report')
}
