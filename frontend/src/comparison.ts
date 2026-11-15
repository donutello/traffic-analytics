import { LEVEL_ORDER, type AnomalyItem, type ComparisonTotals } from './types'

/* Pure logic of the comparison section (issue #13): bar shares, table sorting and
   timeline positions. No DOM here, so vitest covers it directly. */

/** Percent with one decimal, 0 for an empty whole — same shape the backend reports. */
export function sharePct(part: number, whole: number): number {
  return whole > 0 ? Math.round((1000 * part) / whole) / 10 : 0
}

export interface BarParts {
  /** Segment sizes of the stacked bar: matching pairs, then findings only ours, then only the corporate system's. */
  match: number
  onlyOurs: number
  onlyCorporate: number
  total: number
  matchPct: number
  onlyOursPct: number
  onlyCorporatePct: number
}

export function barParts(t: ComparisonTotals): BarParts {
  const total = t.both + t.only_ours + t.only_corporate
  return {
    match: t.both,
    onlyOurs: t.only_ours,
    onlyCorporate: t.only_corporate,
    total,
    matchPct: sharePct(t.both, total),
    onlyOursPct: sharePct(t.only_ours, total),
    onlyCorporatePct: sharePct(t.only_corporate, total),
  }
}

export type SortKey = 'time' | 'sensor' | 'type' | 'level'
export const SORT_LABELS: Record<SortKey, string> = { time: 'время', sensor: 'датчик', type: 'тип', level: 'уровень' }

export function anomalyComparator(key: SortKey): (a: AnomalyItem, b: AnomalyItem) => number {
  switch (key) {
    case 'time':
      // Contract times share format and offset, so text order is time order (as in the backend).
      return (a, b) => (a.starts_at < b.starts_at ? -1 : a.starts_at > b.starts_at ? 1 : 0)
    case 'sensor':
      return (a, b) => a.sensor_name.localeCompare(b.sensor_name, 'ru')
    case 'type':
      return (a, b) => a.type_label.localeCompare(b.type_label, 'ru')
    case 'level':
      return (a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]
  }
}

/** Copy of rows sorted by one column and direction; ids break ties, so clicks never shuffle equal rows. */
export function sortRows<T>(rows: T[], key: SortKey, dir: 1 | -1, item: (row: T) => AnomalyItem): T[] {
  const cmp = anomalyComparator(key)
  return [...rows].sort((x, y) => {
    const a = item(x)
    const b = item(y)
    return dir * cmp(a, b) || a.id.localeCompare(b.id)
  })
}

/** Russian count agreement (the grammar of daysAgo, generalized): 1 пара, 2 пары, 5 пар. */
export function pluralRu(n: number, one: string, few: string, many: string): string {
  const a = n % 10
  const b = n % 100
  if (a === 1 && b !== 11) return one
  if (a >= 2 && a <= 4 && !(b >= 12 && b <= 14)) return few
  return many
}

/** Percent position of an item's start inside the [lo, hi] window; clamped, 0 when the window or the time is broken. */
export function timePct(lo: number, hi: number, iso: string): number {
  const t = Date.parse(iso)
  if (!(hi > lo) || Number.isNaN(t)) return 0
  return Math.min(100, Math.max(0, (100 * (t - lo)) / (hi - lo)))
}

/** Evenly spaced axis timestamps, both ends included. Empty for a broken window. */
export function axisTicks(lo: number, hi: number, parts = 4): number[] {
  if (!(hi > lo) || parts < 1) return []
  return Array.from({ length: parts + 1 }, (_, i) => lo + ((hi - lo) * i) / parts)
}
