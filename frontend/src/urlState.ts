import { useCallback, useEffect, useRef, useState } from 'react'
import { ZOOM_ORDER, type Granularity, type Level } from './types'

/** The shareable view (issue #14): every field lands in a query parameter of the SPA URL.
 *  An empty string means "not set": App resolves it against the data defaults from /api/meta. */
export interface UrlState {
  road: string
  sensor: string
  from: string
  to: string
  granularity: Granularity
  type: string
  source: string
  level: string
  anomaly: string
  section: Section
}

export type Section = 'overview' | 'map' | 'compare'

const SECTIONS: string[] = ['overview', 'map', 'compare']
const LEVELS: Level[] = ['low', 'medium', 'high', 'critical']
const SOURCES: string[] = ['ours', 'corporate']

export const DEFAULT_STATE: UrlState = { road: '', sensor: '', from: '', to: '', granularity: 'week', type: '', source: '', level: '', anomaly: '', section: 'overview' }

/** a plain date or an ISO moment (drill-down to hours keeps its time) */
const TIME = /^\d{4}-\d{2}-\d{2}(?:T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?)?$/

const one = (p: URLSearchParams, key: string): string => p.get(key)?.trim() ?? ''

/** Whatever a shared link holds: unknown or malformed values fall back to the defaults. */
export function parseState(search: string): UrlState {
  const p = new URLSearchParams(search)
  const s: UrlState = { ...DEFAULT_STATE }
  s.road = one(p, 'road')
  s.sensor = one(p, 'sensor')
  for (const key of ['from', 'to'] as const) {
    const v = one(p, key)
    if (TIME.test(v)) s[key] = v
  }
  const pick = (key: string, allowed: string[]): string => {
    const v = one(p, key)
    return allowed.includes(v) ? v : ''
  }
  s.granularity = (pick('granularity', ZOOM_ORDER) || DEFAULT_STATE.granularity) as Granularity
  s.section = (pick('section', SECTIONS) || DEFAULT_STATE.section) as Section
  s.source = pick('source', SOURCES)
  s.level = pick('level', LEVELS.map(String))
  s.type = one(p, 'type')
  s.anomaly = one(p, 'anomaly')
  return s
}

/** Only the user's edits go into the URL; what equals a default is dropped, so links stay short. */
function serialize(s: UrlState): string {
  const p = new URLSearchParams()
  if (s.road) p.set('road', s.road)
  if (s.sensor) p.set('sensor', s.sensor)
  if (s.from) p.set('from', s.from)
  if (s.to) p.set('to', s.to)
  if (s.granularity !== DEFAULT_STATE.granularity) p.set('granularity', s.granularity)
  if (s.type) p.set('type', s.type)
  if (s.source) p.set('source', s.source)
  if (s.level) p.set('level', s.level)
  if (s.anomaly) p.set('anomaly', s.anomaly)
  if (s.section !== DEFAULT_STATE.section) p.set('section', s.section)
  const q = p.toString()
  return q ? `?${q}` : ''
}

/** The hook every section reads its view from: edits push a history entry, so the back
 *  button walks the views the user visited, and a popstate (back/forward) re-reads the URL. */
export function useUrlState(): [UrlState, (patch: Partial<UrlState>) => void] {
  const [state, setState] = useState<UrlState>(() => parseState(window.location.search))
  const mounted = useRef(false)

  useEffect(() => {
    const onPop = () => setState(parseState(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // The first sync only rewrites the address bar when a shared link carries redundant
  // defaults (replace, not push: no back-button trap). After that a user edit differs
  // from the address bar and becomes a new history entry; a back/forward popstate does not.
  useEffect(() => {
    const wanted = serialize(state)
    if (window.location.search !== wanted) {
      const url = `${window.location.pathname}${wanted}`
      if (mounted.current) window.history.pushState(null, '', url)
      else window.history.replaceState(null, '', url)
    }
    mounted.current = true
  }, [state])

  const patch = useCallback((next: Partial<UrlState>) => setState((prev) => ({ ...prev, ...next })), [])
  return [state, patch]
}
