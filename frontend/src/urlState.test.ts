import { describe, expect, it } from 'vitest'
import { DEFAULT_STATE, parseState, serializeState, type UrlState } from './urlState'

const edited: UrlState = {
  road: 'a134',
  sensor: 'a134-km8-100',
  from: '2025-03-08T09:00:00+03:00',
  to: '2025-03-15',
  granularity: 'hour',
  type: 'volume_drop',
  source: 'corporate',
  level: 'critical',
  anomaly: 'a134-corp-0004',
  section: 'compare',
}

describe('urlState round trip', () => {
  it('keeps every edited value across serialize → parse', () => {
    expect(parseState(serializeState(edited))).toEqual(edited)
  })
  it('keeps the default state too (it serializes to nothing and parses back the same)', () => {
    expect(serializeState(DEFAULT_STATE)).toBe('')
    expect(parseState('')).toEqual(DEFAULT_STATE)
  })
  it('drops values equal to the defaults and keeps only the edits', () => {
    const s = serializeState({ ...DEFAULT_STATE, road: 'a133', section: 'overview' })
    expect(s).toBe('?road=a133')
  })
})

describe('parseState against a hostile link', () => {
  it('falls back to defaults for unknown enum values', () => {
    const s = parseState('?section=moon&granularity=century&source=alien&level=impossible')
    expect(s.section).toBe('overview')
    expect(s.granularity).toBe('week')
    expect(s.source).toBe('')
    expect(s.level).toBe('')
  })
  it('drops malformed dates and keeps a plain date or a drill-down ISO time', () => {
    expect(parseState('?from=yesterday&to=2025-13-99').from).toBe('')
    const ok = parseState('?from=2025-03-08&to=2025-03-15T13:00:00%2B03:00')
    expect(ok.from).toBe('2025-03-08')
    expect(ok.to).toBe('2025-03-15T13:00:00+03:00')
  })
  it('trims blanks and never throws on garbage', () => {
    const s = parseState('?road=%20%20a134%20&anomaly=&&&&&&=&&sensor=+')
    expect(s.road).toBe('a134')
    expect(s.sensor).toBe('')
    expect(s.anomaly).toBe('')
  })
  it('ignores repeated keys without crashing and takes the first', () => {
    const s = parseState('?road=a133&road=a134')
    expect(s.road).toBe('a133')
  })
})
