import { useEffect, type ReactNode } from 'react'
import AnomalyList, { CountChips } from './AnomalyList'
import { get, urls } from './api'
import { ErrorState, Spinner } from './States'
import { useAsync } from './useAsync'
import { daysAgo, LEVEL_CLASSES, type AnomalyDetail, type AnomalyItem, type Road, type SensorFeature } from './types'

/** The one side panel of issues #12/#14: opens from a chart anomaly (anomaly mode) or a map
 *  sensor click (sensor mode). Which mode it shows lives in the URL (?anomaly= / ?sensor=),
 *  so a shared link opens the very same panel. Labels are the API's Russian ones. */

const num = (v: number | null | undefined, unit = ''): string => (v === null || v === undefined ? '—' : `${v.toLocaleString('ru-RU')}${unit}`)

function row(label: string, value: ReactNode) {
  return (
    <tr>
      <th>{label}</th>
      <td>{value}</td>
    </tr>
  )
}

interface Props {
  /** Anomaly mode: /api/anomalies/{anomalyId} carries the item and its event. */
  anomalyId?: string
  /** Sensor mode: the clicked /api/sensors feature plus its anomalies in the current window and filters. */
  sensor?: SensorFeature
  items?: AnomalyItem[]
  roads: Road[]
  features?: SensorFeature[]
  onSelectAnomaly: (id: string) => void
  onClose: () => void
}

export default function SidePanel(props: Props) {
  const { anomalyId, onClose } = props

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="side-panel" role="region" aria-label="Панель аномалии">
      {anomalyId ? <AnomalyView {...props} id={anomalyId} /> : <SensorView {...props} />}
    </div>
  )
}

function Close({ onClose }: { onClose: () => void }) {
  return (
    <button className="close" onClick={onClose} aria-label="Закрыть">
      ✕
    </button>
  )
}

function roadNameOf(roads: Road[], code: string): string {
  return roads.find((r) => r.code === code)?.name ?? code
}

/** Name, road name and km of a sensor, when it is among the loaded features; else its API name. */
function sensorLine(features: SensorFeature[] | undefined, roads: Road[], id: string, fallbackName: string): string {
  const f = features?.find((x) => x.properties.id === id)
  if (!f) return fallbackName
  return `${f.properties.name} · ${roadNameOf(roads, f.properties.road)} · км ${num(f.properties.km)}`
}

function AnomalyView({ id, roads, features, onClose }: Props & { id: string }) {
  const { data, error } = useAsync(get<AnomalyDetail>(urls.anomaly(id)), [id])
  // The API answers 404 for unknown ids; a shared link with a stale id deserves a friendly hint, not a raw error (issue #15).
  const notFound = !!error && /: 404$/.test(error)

  return (
    <>
      {notFound && (
        <>
          <div className="detail-head">
            <h4>Аномалия не найдена</h4>
            <Close onClose={onClose} />
          </div>
          <p className="muted small">
            В ссылке указан номер, которого нет в базе — возможно, данные импортировали заново. Выберите дорогу и период на панели фильтров, затем откройте аномалию на графике, карте или в разделе
            сравнения.
          </p>
        </>
      )}
      {error && !notFound && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="detail-head">
            <h4>
              <span className={`dot ${LEVEL_CLASSES[data.level]}`} aria-hidden /> {data.type_label}
              {data.is_mega && <span className="mega">МЕГА</span>}
            </h4>
            <Close onClose={onClose} />
          </div>
          <div className="badges">
            <span className={`badge ${LEVEL_CLASSES[data.level]}`}>{data.level_label}</span>
            <span className="badge">{data.category_label}</span>
            <span className="muted small">{data.source_label}</span>
          </div>
          <table className="kv">
            <tbody>
              {row('время', `${data.starts_label} — ${data.ends_label} (${data.duration_label})${data.days_ago ? `, ${daysAgo(data.days_ago)}` : ''}`)}
              {row('датчик', sensorLine(features, roads, data.sensor_id, data.sensor_name))}
              {row('факт / норма', `${num(data.actual)} / ${num(data.expected)}`)}
              {row('отклонение', num(data.deviation_pct, ' %'))}
              {row('оценка', num(data.score))}
            </tbody>
          </table>
          {data.description && <p className="desc">{data.description}</p>}
          {data.event && (
            <div className="event">
              <h5>
                Что произошло · {data.event.category_label} · {data.event.date_label}
              </h5>
              <p>
                <strong>{data.event.title}</strong>
              </p>
              {data.event.description && <p>{data.event.description}</p>}
              <a href={data.event.source_url} target="_blank" rel="noreferrer">
                источник
              </a>
            </div>
          )}
          <details>
            <summary>ответ API (JSON)</summary>
            <pre>{JSON.stringify(data, null, 2)}</pre>
          </details>
        </>
      )}
    </>
  )
}

function SensorView({ sensor, items = [], roads, onClose, onSelectAnomaly }: Props) {
  if (!sensor) return null
  const p = sensor.properties
  const counts = { ours: items.filter((a) => a.source === 'ours').length, corporate: items.filter((a) => a.source === 'corporate').length }

  return (
    <>
      <div className="detail-head">
        <h4>
          {p.name}
          {p.is_mega && <span className="mega">МЕГА</span>}
        </h4>
        <Close onClose={onClose} />
      </div>
      <table className="kv">
        <tbody>
          {row('дорога', roadNameOf(roads, p.road))}
          {row('км', num(p.km))}
          {row('направления', `${p.directions.direct} / ${p.directions.reverse}`)}
          {row('аномалий в окне', num(items.length))}
        </tbody>
      </table>
      <CountChips counts={counts} />
      {items.length === 0 ? <p className="muted small">За выбранный период и фильтры аномалий нет.</p> : <AnomalyList data={{ counts, anomalies: items }} onSelect={onSelectAnomaly} />}
    </>
  )
}
