import { describe, expect, it } from 'vitest'
import { axisTicks, barParts, pluralRu, sharePct, sortRows, timePct } from './comparison'
import type { AnomalyItem, ComparisonTotals } from './types'

const totals = (o: Partial<ComparisonTotals>): ComparisonTotals => ({ ours: 0, corporate: 0, both: 0, only_ours: 0, only_corporate: 0, ...o })

const item = (id: string, over: Partial<AnomalyItem>): AnomalyItem =>
  ({
    id,
    sensor_id: 's',
    sensor_name: 's',
    starts_at: '2025-01-01T00:00:00+03:00',
    ends_at: '2025-01-01T01:00:00+03:00',
    starts_label: '',
    ends_label: '',
    duration_label: '',
    days_ago: 0,
    category: 'traffic',
    category_label: '',
    type: 't',
    type_label: 't',
    detector: 'd',
    level: 'low',
    level_label: '',
    metric: 'volume',
    actual: null,
    expected: null,
    deviation_pct: null,
    score: null,
    is_mega: false,
    event_id: null,
    description: null,
    source: 'ours',
    source_label: '',
    ...over,
  }) as AnomalyItem

describe('sharePct', () => {
  it('is zero for an empty whole instead of dividing by zero', () => {
    expect(sharePct(0, 0)).toBe(0)
    expect(sharePct(7, 0)).toBe(0)
    expect(sharePct(0, 9)).toBe(0)
  })
  it('rounds to one decimal', () => {
    expect(sharePct(30, 80)).toBe(37.5)
    expect(sharePct(1, 3)).toBe(33.3)
    expect(sharePct(2, 3)).toBe(66.7)
    expect(sharePct(5, 5)).toBe(100)
  })
})

describe('barParts', () => {
  it('sizes the three segments and their percent shares', () => {
    const b = barParts(totals({ ours: 12, corporate: 6, both: 4, only_ours: 8, only_corporate: 2 }))
    expect(b.total).toBe(14)
    expect([b.match, b.onlyOurs, b.onlyCorporate]).toEqual([4, 8, 2])
    expect([b.matchPct, b.onlyOursPct, b.onlyCorporatePct]).toEqual([28.6, 57.1, 14.3])
  })
  it('survives an empty comparison (no findings at all)', () => {
    const b = barParts(totals({}))
    expect(b.total).toBe(0)
    expect([b.matchPct, b.onlyOursPct, b.onlyCorporatePct]).toEqual([0, 0, 0])
  })
  it('handles the 0-ours / 0-both road (only corporate findings)', () => {
    const b = barParts(totals({ corporate: 5, only_corporate: 5 }))
    expect([b.matchPct, b.onlyOursPct, b.onlyCorporatePct]).toEqual([0, 0, 100])
  })
})

describe('pluralRu', () => {
  it('agrees with Russian counting', () => {
    const p = (n: number) => pluralRu(n, 'пара', 'пары', 'пар')
    expect(p(1)).toBe('пара')
    expect(p(21)).toBe('пара')
    expect(p(2)).toBe('пары')
    expect(p(24)).toBe('пары')
    expect(p(5)).toBe('пар')
    expect(p(11)).toBe('пар')
    expect(p(114)).toBe('пар')
  })
})

describe('sortRows', () => {
  const rows = [
    item('b', { starts_at: '2025-03-01T00:00:00+03:00', level: 'critical', sensor_name: 'км 9' }),
    item('a', { starts_at: '2025-01-01T00:00:00+03:00', level: 'low', sensor_name: 'км 2' }),
    item('c', { starts_at: '2025-02-01T00:00:00+03:00', level: 'high', sensor_name: 'км 5' }),
  ]
  const ids = (list: AnomalyItem[]) => list.map((x) => x.id)

  it('sorts by time ascending and descending, without touching the source', () => {
    expect(ids(sortRows(rows, 'time', 1, (x) => x))).toEqual(['a', 'c', 'b'])
    expect(ids(sortRows(rows, 'time', -1, (x) => x))).toEqual(['b', 'c', 'a'])
    expect(ids(rows)).toEqual(['b', 'a', 'c'])
  })
  it('sorts by level severity and by sensor name', () => {
    expect(ids(sortRows(rows, 'level', 1, (x) => x))).toEqual(['a', 'c', 'b'])
    expect(ids(sortRows(rows, 'sensor', 1, (x) => x))).toEqual(['a', 'c', 'b'])
  })
  it('breaks ties by id, so equal rows never shuffle', () => {
    const same = [item('z', {}), item('y', {})]
    expect(ids(sortRows(same, 'time', 1, (x) => x))).toEqual(['y', 'z'])
  })
})

describe('timePct and axisTicks', () => {
  const lo = Date.parse('2025-01-01T00:00:00Z')
  const hi = Date.parse('2025-01-03T00:00:00Z')

  it('places times inside the window and clamps outside it', () => {
    expect(timePct(lo, hi, '2025-01-02T00:00:00Z')).toBeCloseTo(50)
    expect(timePct(lo, hi, '2024-06-01T00:00:00Z')).toBe(0)
    expect(timePct(lo, hi, '2026-06-01T00:00:00Z')).toBe(100)
  })
  it('falls back to 0 for broken windows and broken times', () => {
    expect(timePct(hi, hi, '2025-01-02T00:00:00Z')).toBe(0)
    expect(timePct(lo, hi, 'not a date')).toBe(0)
  })
  it('draws evenly spaced axis ticks including both ends', () => {
    expect(axisTicks(0, 100)).toEqual([0, 25, 50, 75, 100])
    expect(axisTicks(100, 0)).toEqual([])
  })
})
