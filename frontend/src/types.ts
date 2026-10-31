export type State = 'normal' | 'anomaly' | 'imputed'
export type Granularity = 'hour' | 'day' | 'week'
export type Level = 'low' | 'medium' | 'high' | 'critical'

export const STATE_LABELS: Record<State, string> = { normal: 'норма', anomaly: 'аномалия', imputed: 'восстановлено' }
export const GRANULARITY_LABELS: Record<Granularity, string> = { hour: 'час', day: 'день', week: 'неделя' }
export const LEVEL_CLASSES: Record<Level, string> = { low: 'lv-low', medium: 'lv-medium', high: 'lv-high', critical: 'lv-critical' }

/** "N дней назад" with Russian agreement; the numbers come from the data, the grammar lives here. Empty for the last data day. */
export function daysAgo(n: number): string {
  if (n === 0) return ''
  const a = n % 10
  const b = n % 100
  if (a === 1 && b !== 11) return `${n} день назад`
  if (a >= 2 && a <= 4 && !(b >= 12 && b <= 14)) return `${n} дня назад`
  return `${n} дней назад`
}

export interface Road { code: string; name: string; sensors: number }
export interface Period { from: string; to: string }
export interface Meta { roads: Road[]; period: Period }

export interface Point { ts: string; label: string; volume: number; state: State }
export interface Series { points: Point[] }

export interface SensorProps { id: string; name: string; road: string; km: number; anomaly_count: number; is_mega: boolean; directions: { direct: string; reverse: string } }
export interface SensorFeature { type: 'Feature'; geometry: { type: 'Point'; coordinates: [number, number] }; properties: SensorProps }
export type SensorMap = { type: 'FeatureCollection'; features: SensorFeature[] }

export interface AnomalyItem {
  id: string
  sensor_id: string
  sensor_name: string
  starts_at: string
  ends_at: string
  starts_label: string
  ends_label: string
  duration_label: string
  days_ago: number
  category: string
  category_label: string
  type: string
  type_label: string
  detector: string
  level: Level
  level_label: string
  metric: string
  actual: number | null
  expected: number | null
  deviation_pct: number | null
  score: number | null
  is_mega: boolean
  event_id: string | null
  description: string | null
  source: 'ours' | 'corporate'
  source_label: string
}
export interface EventItem { id: string; date: string; date_label: string; category: string; category_label: string; title: string; description: string | null; source_url: string }
export interface AnomalyDetail extends AnomalyItem { event: EventItem | null }
export interface SensorAnomalies { counts: { ours: number; corporate: number }; anomalies: AnomalyItem[] }
