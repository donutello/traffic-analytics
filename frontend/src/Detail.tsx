import type { ReactNode } from 'react'
import { get, urls } from './api'
import { Spinner, ErrorState } from './States'
import { useAsync } from './useAsync'
import { daysAgo, LEVEL_CLASSES, type AnomalyDetail } from './types'

const num = (v: number | null | undefined, unit = ''): string => (v === null || v === undefined ? '—' : `${v.toLocaleString('ru-RU')}${unit}`)

function row(label: string, value: ReactNode) {
  return (
    <tr>
      <th>{label}</th>
      <td>{value}</td>
    </tr>
  )
}

/** Minimal fields for one anomaly, inline in the side column (issue #11). The full side panel with the event comes in #12. */
export default function DetailPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error } = useAsync(get<AnomalyDetail>(urls.anomaly(id)), [id])

  return (
    <div className="detail-panel" role="region" aria-label="Выбранная аномалия">
      {error && <ErrorState message={error} />}
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="detail-head">
            <h4>
              <span className={`dot ${LEVEL_CLASSES[data.level]}`} aria-hidden /> {data.type_label}
              {data.is_mega && <span className="mega">МЕГА</span>}
            </h4>
            <button className="close" onClick={onClose} aria-label="Закрыть">
              ✕
            </button>
          </div>
          <table className="kv">
            <tbody>
              {row('время', `${data.starts_label} — ${data.ends_label} (${data.duration_label})${data.days_ago ? `, ${daysAgo(data.days_ago)}` : ''}`)}
              {row('уровень', <span className={LEVEL_CLASSES[data.level]}>{data.level_label}</span>)}
              {row('датчик', `${data.sensor_name}`)}
              {row('нашёл', data.source_label)}
              {row('категория', data.category_label)}
              {row('факт / норма', `${num(data.actual)} / ${num(data.expected)} (${num(data.deviation_pct, ' %')})`)}
            </tbody>
          </table>
          {data.description && <p className="desc">{data.description}</p>}
          <details>
            <summary>ответ API (JSON)</summary>
            <pre>{JSON.stringify(data, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  )
}
