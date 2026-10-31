import { daysAgo, LEVEL_CLASSES, type SensorAnomalies } from './types'

export function CountChips({ counts }: { counts: SensorAnomalies['counts'] }) {
  return (
    <p className="counts">
      нашли мы: <b>{counts.ours}</b> · корпоративная система: <b>{counts.corporate}</b>
    </p>
  )
}

export default function AnomalyList({ data, onSelect }: { data: SensorAnomalies; onSelect: (id: string) => void }) {
  return (
    <ul className="anomaly-list">
      {data.anomalies.map((a) => (
        <li key={a.id}>
          <button className="anomaly" onClick={() => onSelect(a.id)}>
            <span className={`dot ${LEVEL_CLASSES[a.level]}`} aria-hidden />
            <span className="a-main">
              <strong>{a.type_label}</strong>
              <span>
                {a.level_label}, {a.category_label} · {a.duration_label} · {a.starts_label}
              </span>
            </span>
            <span className="a-meta">
              {a.is_mega && <span className="mega">МЕГА</span>}
              <span className="muted">{a.source === 'ours' ? 'мы' : 'корп.'}</span>
              <span className="muted">{daysAgo(a.days_ago)}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
