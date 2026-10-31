import { useEffect } from 'react'
import { get, urls } from './api'
import { useAsync } from './useAsync'
import { daysAgo, LEVEL_CLASSES, type AnomalyDetail } from './types'

const num = (v: number | null, unit = ''): string => (v === null ? '—' : `${v.toLocaleString('ru-RU')}${unit}`)

function row(label: string, value: string) {
  return (
    <tr>
      <th>{label}</th>
      <td>{value}</td>
    </tr>
  )
}

export default function DetailOverlay({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error } = useAsync(get<AnomalyDetail>(urls.anomaly(id)), [id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="overlay" onClick={onClose}>
      <div className="detail card" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        {!data && <p className="muted">{error ?? 'Загрузка…'}</p>}
        {data && (
          <>
            <div className="detail-head">
              <h3>
                <span className={`dot ${LEVEL_CLASSES[data.level]}`} aria-hidden /> {data.type_label} ·{' '}
                <span className={LEVEL_CLASSES[data.level]}>{data.level_label} уровень</span>
              </h3>
              <button className="close" onClick={onClose} aria-label="Закрыть">
                ✕
              </button>
            </div>
            <table className="kv">
              <tbody>
                {row('время', `${data.starts_label} — ${data.ends_label} (${data.duration_label})${data.days_ago ? `, ${daysAgo(data.days_ago)}` : ''}`)}
                {row('датчик', data.sensor_name)}
                {row('нашёл', data.source_label)}
                {row('алгоритм', data.detector)}
                {row('категория', data.category_label)}
                {row('факт / норма', `${num(data.actual)} / ${num(data.expected)} (${num(data.deviation_pct, ' %')})`)}
                {row('оценка', num(data.score))}
                {data.is_mega && row('статус', 'мега-аномалия')}
              </tbody>
            </table>
            {data.description && <p className="desc">{data.description}</p>}
            {data.event && (
              <div className="event">
                <h4>
                  {data.event.title} <span className="muted">· {data.event.category_label}, {data.event.date_label}</span>
                </h4>
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
      </div>
    </div>
  )
}
