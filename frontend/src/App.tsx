import { useState } from 'react'
import AnomalyList, { CountChips } from './AnomalyList'
import { get, urls } from './api'
import Chart from './Chart'
import DetailOverlay from './Detail'
import MapSection from './Map'
import { useAsync } from './useAsync'
import { GRANULARITY_LABELS, type Granularity, type Meta, type Period, type SensorAnomalies, type SensorMap, type Series } from './types'

type Tab = 'overview' | 'map' | 'compare'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Обзор' },
  { id: 'map', label: 'Карта' },
  { id: 'compare', label: 'Сравнение алгоритмов' },
]

const NONE: Promise<null> = Promise.resolve(null)

export default function App() {
  const [dark, setDark] = useState(() => document.documentElement.dataset.theme === 'dark')
  const [tab, setTab] = useState<Tab>('overview')
  const [road, setRoad] = useState('')
  const [periodEdit, setPeriodEdit] = useState<Period | null>(null)
  const [sensorPick, setSensorPick] = useState<string | null>(null)
  const [granularity, setGranularity] = useState<Granularity>('hour')
  const [detailId, setDetailId] = useState<string | null>(null)

  const meta = useAsync(get<Meta>(urls.meta()), [])
  const roadCode = road || (meta.data?.roads[0].code ?? '')
  const period = periodEdit ?? meta.data?.period
  const sensors = useAsync(meta.data ? get<SensorMap>(urls.sensors(roadCode, period?.from ?? '', period?.to ?? '')) : NONE, [meta.data, roadCode, period?.from, period?.to])
  // First sensor by default; a picked one wins if it exists in the loaded road. Same for road and period: state only stores edits.
  const sensor = sensors.data?.features.some((f) => f.properties.id === sensorPick) ? sensorPick : (sensors.data?.features[0]?.properties.id ?? null)

  const series = useAsync(sensor ? get<Series>(urls.series(sensor, period?.from ?? '', period?.to ?? '', granularity)) : NONE, [sensor, period?.from, period?.to, granularity])
  const anomalies = useAsync(sensor ? get<SensorAnomalies>(urls.anomalies(sensor, period?.from ?? '', period?.to ?? '')) : NONE, [sensor, period?.from, period?.to])
  const sensorName = sensors.data?.features.find((f) => f.properties.id === sensor)?.properties.name ?? ''

  const toggleTheme = () => {
    setDark((d) => {
      document.documentElement.dataset.theme = d ? 'light' : 'dark'
      return !d
    })
  }

  if (meta.error) return <main className="boot">Сервер недоступен: {meta.error}</main>
  if (!meta.data || !period || !sensors.data) return <main className="boot">Загрузка…</main>

  const features = sensors.data.features

  return (
    <main className="app">
      <header className="top">
        <div>
          <h1>Аномалии трафика</h1>
          <p className="muted">
            Прототип панели на тестовых данных <code>analysis/output/_example</code>
          </p>
        </div>
        {meta.data.roads.length > 1 ? (
          <select id="road" name="road" value={roadCode} onChange={(e) => setRoad(e.target.value)} aria-label="Дорога">
            {meta.data.roads.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        ) : (
          <span className="road-name">{meta.data.roads[0].name}</span>
        )}
        <div className="period">
          <label htmlFor="date-from">
            с{' '}
            <input id="date-from" type="date" min={meta.data.period.from} max={meta.data.period.to} value={period.from} onChange={(e) => setPeriodEdit({ ...period, from: e.target.value })} />
          </label>
          <label htmlFor="date-to">
            по{' '}
            <input id="date-to" type="date" min={meta.data.period.from} max={meta.data.period.to} value={period.to} onChange={(e) => setPeriodEdit({ ...period, to: e.target.value })} />
          </label>
        </div>
        <button onClick={toggleTheme} aria-label="Переключить тему">
          {dark ? 'Светлая тема' : 'Тёмная тема'}
        </button>
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} aria-pressed={tab === t.id} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'overview' && (
        <section className="board">
          <div className="card filters">
            <select id="sensor" name="sensor" value={sensor ?? ''} onChange={(e) => setSensorPick(e.target.value)} aria-label="Датчик">
              {features.map((f) => (
                <option key={f.properties.id} value={f.properties.id}>
                  Датчик {f.properties.name}
                </option>
              ))}
            </select>
            <div className="seg">
              {(Object.keys(GRANULARITY_LABELS) as Granularity[]).map((g) => (
                <button key={g} aria-pressed={granularity === g} onClick={() => setGranularity(g)}>
                  {GRANULARITY_LABELS[g]}
                </button>
              ))}
            </div>
          </div>
          {series.error ? <div className="card chart-card">Данные не загрузились: {series.error}</div> : series.data ? <Chart points={series.data.points} name={sensorName} dark={dark} /> : <div className="card chart-card">Загрузка…</div>}
          <aside className="card side">
            <h3>Аномалии датчика</h3>
            <CountChips counts={anomalies.data?.counts ?? { ours: 0, corporate: 0 }} />
            {anomalies.data && <AnomalyList data={anomalies.data} onSelect={setDetailId} />}
            <button className="map-link" onClick={() => setTab('map')}>
              посмотреть на карте →
            </button>
          </aside>
        </section>
      )}

      {tab === 'map' && <MapSection features={features} sensor={sensor} setSensor={setSensorPick} focus={sensorPick} anomalies={anomalies.data} openDetail={setDetailId} dark={dark} />}

      {tab === 'compare' && (
        <section className="compare">
          <div className="card">
            <h3>Наш алгоритм против корпоративной системы</h3>
            <p>
              Совпадения, только наши и только корпоративные аномалии по каждому датчику появятся, когда будет готов API сравнения (issue{' '}
              <a href="https://github.com/donutello/traffic-analytics/issues/7">#7</a>).
            </p>
            <p className="muted">Числа счётчиков в панели датчика уже разделены по источникам: «нашли мы» и «корпоративная система».</p>
            <span className="mega">в разработке</span>
          </div>
        </section>
      )}

      {detailId && <DetailOverlay id={detailId} onClose={() => setDetailId(null)} />}
    </main>
  )
}
