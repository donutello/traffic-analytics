import { useState } from 'react'
import AnomalyList, { CountChips } from './AnomalyList'
import { get, urls } from './api'
import Chart from './Chart'
import DetailPanel from './Detail'
import Placeholder from './Placeholder'
import { EmptyState, ErrorState, Spinner } from './States'
import { THEME_KEY, applyTheme, type Theme } from './theme'
import { useAsync } from './useAsync'
import { GRANULARITY_LABELS, longDate, ZOOM_ORDER, type AnomalyItem, type Granularity, type Meta, type Point, type SensorAnomalies, type SensorMap, type Series, type TimeWindow } from './types'

type Tab = 'overview' | 'map' | 'compare'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Обзор' },
  { id: 'map', label: 'Карта' },
  { id: 'compare', label: 'Сравнение алгоритмов' },
]

const NONE: Promise<null> = Promise.resolve(null)
const NO_POINTS: Point[] = []
const NO_ANOMALIES: AnomalyItem[] = []

/** Code of the fictional sample road in /api/meta; every other road is real project data. Names are still taken from the API, never from here. */
const SAMPLE_ROAD = '_example'

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'))
  const [tab, setTab] = useState<Tab>('overview')
  const [road, setRoad] = useState('')
  const [sensorPick, setSensorPick] = useState<string | null>(null)
  const [level, setLevel] = useState<Granularity>('week')
  const [view, setView] = useState<TimeWindow | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)

  const meta = useAsync(get<Meta>(urls.meta()), [])
  const roads = meta.data?.roads ?? []
  // Default the first real road: the sample is fictional and would mislead on first open.
  const roadCode = road || (roads.find((r) => r.code !== SAMPLE_ROAD) ?? roads[0])?.code || ''
  const period = meta.data?.period
  const sensors = useAsync(meta.data ? get<SensorMap>(urls.sensors(roadCode, period?.from ?? '', period?.to ?? '')) : NONE, [meta.data, roadCode, period?.from, period?.to])
  // First sensor by default; a picked one wins if it exists in the loaded road. State only stores edits.
  const sensor = sensors.data?.features.some((f) => f.properties.id === sensorPick) ? sensorPick : (sensors.data?.features[0]?.properties.id ?? null)

  const span = view ?? (period ? { from: period.from, to: period.to } : null)
  const series = useAsync(sensor && span ? get<Series>(urls.series(sensor, span.from, span.to, level)) : NONE, [sensor, span?.from, span?.to, level])
  const anomalies = useAsync(sensor && span ? get<SensorAnomalies>(urls.anomalies(sensor, span.from, span.to)) : NONE, [sensor, span?.from, span?.to])
  const sensorName = sensors.data?.features.find((f) => f.properties.id === sensor)?.properties.name ?? ''

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    localStorage.setItem(THEME_KEY, next)
    setTheme(next)
  }
  const changeRoad = (code: string) => {
    setRoad(code)
    setSensorPick(null)
    setLevel('week')
    setView(null)
    setDetailId(null)
  }
  const drillDown = (fromTs: string, toTs: string) => {
    const next = ZOOM_ORDER[ZOOM_ORDER.indexOf(level) + 1]
    if (!next) return // hour is the finest stored level: finer selection just zooms the loaded window
    setView({ from: fromTs, to: toTs })
    setLevel(next)
    setDetailId(null)
  }
  const resetView = () => {
    setLevel('week')
    setView(null)
    setDetailId(null)
  }

  if (meta.error)
    return (
      <main className="boot">
        <ErrorState message={`Сервер недоступен. ${meta.error}`} />
      </main>
    )
  if (!meta.data || !period)
    return (
      <main className="boot">
        <Spinner label="Загрузка данных о дорогах…" />
      </main>
    )

  const features = sensors.data?.features ?? []
  const points = series.data?.points ?? NO_POINTS

  return (
    <main className="app">
      <header className="top">
        <div>
          <h1>Аномалии трафика</h1>
          <p className="muted">
            Данные с {longDate(period.from)} по {longDate(period.to)}
          </p>
        </div>
        <select id="road" name="road" value={roadCode} onChange={(e) => changeRoad(e.target.value)} aria-label="Дорога">
          {roads.map((r) => (
            <option key={r.code} value={r.code}>
              {r.name}
            </option>
          ))}
        </select>
        <button onClick={toggleTheme} aria-label="Переключить тему">
          {theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
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
            <select
              id="sensor"
              name="sensor"
              value={sensor ?? ''}
              onChange={(e) => {
                setSensorPick(e.target.value)
                setDetailId(null)
              }}
              aria-label="Датчик"
            >
              {features.map((f) => (
                <option key={f.properties.id} value={f.properties.id}>
                  {f.properties.name}
                </option>
              ))}
            </select>
            <div className="seg" role="group" aria-label="Детализация">
              {ZOOM_ORDER.map((g) => (
                <button
                  key={g}
                  aria-pressed={level === g}
                  onClick={() => {
                    setLevel(g)
                    setDetailId(null)
                  }}
                >
                  {GRANULARITY_LABELS[g]}
                </button>
              ))}
            </div>
            {view && (
              <>
                <span className="window-chip muted">
                  {longDate(view.from)} — {longDate(view.to)}
                </span>
                <button onClick={resetView}>к началу периода</button>
              </>
            )}
          </div>

          {sensors.error && (
            <div className="card chart-card">
              <ErrorState message={sensors.error} />
            </div>
          )}
          {!sensors.data && !sensors.error && (
            <div className="card chart-card">
              <Spinner />
            </div>
          )}
          {sensors.data && features.length === 0 && (
            <div className="card chart-card">
              <EmptyState message="На этой дороге нет датчиков." />
            </div>
          )}
          {sensor && series.error && (
            <div className="card chart-card">
              <ErrorState message={series.error} />
            </div>
          )}
          {sensor && !series.data && !series.error && (
            <div className="card chart-card">
              <Spinner />
            </div>
          )}
          {sensor && series.data && points.length === 0 && (
            <div className="card chart-card">
              <EmptyState message="За выбранный период у датчика нет измерений." />
            </div>
          )}
          {sensor && series.data && points.length > 0 && <Chart points={points} anomalies={anomalies.data?.anomalies ?? NO_ANOMALIES} level={level} dark={theme === 'dark'} name={sensorName} onZoom={drillDown} onAnomalyClick={setDetailId} />}

          <aside className="card side">
            <h3>Аномалии датчика</h3>
            {sensors.error ? (
              <ErrorState message={sensors.error} />
            ) : !sensor ? (
              sensors.data ? (
                <EmptyState message="На этой дороге нет датчиков." />
              ) : (
                <Spinner />
              )
            ) : (
              <>
                {detailId && <DetailPanel id={detailId} onClose={() => setDetailId(null)} />}
                {anomalies.error && <ErrorState message={anomalies.error} />}
                {!anomalies.data && !anomalies.error && <Spinner label="Загрузка аномалий…" />}
                {anomalies.data && (
                  <>
                    <CountChips counts={anomalies.data.counts} />
                    {anomalies.data.anomalies.length === 0 ? <p className="muted small">За выбранный период аномалий нет.</p> : <AnomalyList data={anomalies.data} onSelect={setDetailId} />}
                  </>
                )}
              </>
            )}
          </aside>
        </section>
      )}

      {tab === 'map' && <Placeholder title="Карта аномалий" text="Точки датчиков на OpenStreetMap, подсветка мега-аномалий и панель подробностей по клику." issue={12} />}

      {tab === 'compare' && <Placeholder title="Сравнение алгоритмов" text="Где наш алгоритм и корпоративная система находят одно и то же, где расходятся и насколько новый подход лучше (FR4)." issue={13} />}
    </main>
  )
}
