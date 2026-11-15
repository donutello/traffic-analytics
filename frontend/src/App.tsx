import { useCallback, useMemo, useState } from 'react'
import AnomalyList, { CountChips } from './AnomalyList'
import { get, urls } from './api'
import Chart from './Chart'
import Comparison from './Comparison'
import MapSection, { MapStates } from './MapSection'
import SidePanel from './SidePanel'
import { EmptyState, ErrorState, Spinner } from './States'
import Toolbar from './Toolbar'
import { THEME_KEY, applyTheme, type Theme } from './theme'
import { useUrlState } from './urlState'
import { useAsync } from './useAsync'
import { LEVEL_ORDER, longDate, ZOOM_ORDER, type Meta, type Point, type SensorAnomalies, type SensorHeat, type SensorMap, type Series } from './types'

const TABS: { id: 'overview' | 'map' | 'compare'; label: string }[] = [
  { id: 'overview', label: 'Обзор' },
  { id: 'map', label: 'Карта' },
  { id: 'compare', label: 'Сравнение алгоритмов' },
]

const NONE: Promise<null> = Promise.resolve(null)
const NO_POINTS: Point[] = []

/** Code of the fictional sample road in /api/meta; every other road is real project data. Names are still taken from the API, never from here. */
const SAMPLE_ROAD = '_example'

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'))
  // One shared view state for every section (issue #14): the URL is its single source.
  const [url, patch] = useUrlState()

  const meta = useAsync(get<Meta>(urls.meta()), [])
  const roads = meta.data?.roads ?? []
  // Default the first real road: the sample is fictional and would mislead on first open.
  const road = url.road || (roads.find((r) => r.code !== SAMPLE_ROAD) ?? roads[0])?.code || ''
  const period = meta.data?.period
  const from = url.from || period?.from || ''
  const to = url.to || period?.to || ''

  const sensors = useAsync(meta.data && road ? get<SensorMap>(urls.sensors(road, from, to)) : NONE, [meta.data, road, from, to])
  const anomalies = useAsync(meta.data && road ? get<SensorAnomalies>(urls.anomalies(road, from, to)) : NONE, [meta.data, road, from, to])
  const features = useMemo(() => sensors.data?.features ?? [], [sensors.data])
  // First sensor by default; a picked one wins if it exists in the loaded road. The URL only stores edits.
  const sensor = features.some((f) => f.properties.id === url.sensor) ? url.sensor : (features[0]?.properties.id ?? '')
  const sensorFeature = features.find((f) => f.properties.id === sensor) ?? null

  const series = useAsync(sensor ? get<Series>(urls.series(sensor, from, to, url.granularity)) : NONE, [sensor, from, to, url.granularity])

  // Type/source/level filters applied client-side over the window (issue #14): the same
  // filtered items drive the chart overlay, the anomaly list and the map marker colors.
  const all = useMemo(() => anomalies.data?.anomalies ?? [], [anomalies.data])
  const filtered = useMemo(
    () => all.filter((a) => (!url.type || a.type === url.type) && (!url.source || a.source === url.source) && (!url.level || a.level === url.level)),
    [all, url.type, url.source, url.level],
  )
  const sensorItems = useMemo(() => filtered.filter((a) => a.sensor_id === sensor), [filtered, sensor])
  const listData: SensorAnomalies = useMemo(
    () => ({ counts: { ours: sensorItems.filter((a) => a.source === 'ours').length, corporate: sensorItems.filter((a) => a.source === 'corporate').length }, anomalies: sensorItems }),
    [sensorItems],
  )

  const heat = useMemo(() => {
    const h: Record<string, SensorHeat> = {}
    for (const a of filtered) {
      const s = (h[a.sensor_id] ??= { count: 0, level: null })
      s.count += 1
      if (!s.level || LEVEL_ORDER[a.level] > LEVEL_ORDER[s.level]) s.level = a.level
    }
    return h
  }, [filtered])

  // The names in the type filter stay server-driven: labels collected from this window's API items.
  const typeLabels = useMemo(() => {
    const m: Record<string, string> = {}
    for (const a of all) m[a.type] = a.type_label
    return m
  }, [all])

  const sensorName = sensorFeature?.properties.name ?? ''

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    localStorage.setItem(THEME_KEY, next)
    setTheme(next)
  }
  const openAnomaly = useCallback((id: string) => patch({ anomaly: id }), [patch])
  const closeAnomaly = useCallback(() => patch({ anomaly: '' }), [patch])
  /** The comparison section's per-road cards: show one road without touching the period. */
  const pickRoad = useCallback((code: string) => patch({ road: code, sensor: '', anomaly: '' }), [patch])
  /** A map marker click selects the sensor and opens its summary (sensor mode of the panel). */
  const pickSensor = useCallback((id: string) => patch({ sensor: id, anomaly: '' }), [patch])
  const drillDown = (fromTs: string, toTs: string) => {
    const next = ZOOM_ORDER[ZOOM_ORDER.indexOf(url.granularity) + 1]
    if (!next) return // hour is the finest stored level: finer selection just zooms the loaded window
    patch({ from: fromTs, to: toTs, granularity: next, anomaly: '' })
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

  const points = series.data?.points ?? NO_POINTS
  const anomaliesLoading = !!road && !anomalies.data && !anomalies.error
  // The URL alone decides what the panel shows: ?anomaly= opens it from the chart or a link,
  // an explicit ?sensor= on the map opens it from a marker click — one panel for both (#12).
  const panel = url.anomaly ? (
    <SidePanel anomalyId={url.anomaly} roads={roads} features={features} onSelectAnomaly={openAnomaly} onClose={closeAnomaly} />
  ) : url.section === 'map' && sensorFeature && url.sensor === sensorFeature.properties.id ? (
    <SidePanel sensor={sensorFeature} items={sensorItems} roads={roads} onSelectAnomaly={openAnomaly} onClose={() => patch({ sensor: '' })} />
  ) : null

  return (
    <main className="app">
      <header className="top">
        <div>
          <h1>Аномалии трафика</h1>
          <p className="muted">
            Данные с {longDate(period.from)} по {longDate(period.to)}
          </p>
        </div>
        <button onClick={toggleTheme} aria-label="Переключить тему">
          {theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
        </button>
      </header>

      <Toolbar state={url} roads={roads} road={road} sensor={sensor || null} features={features} typeLabels={typeLabels} period={period} onPatch={patch} />

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} aria-pressed={url.section === t.id} onClick={() => patch({ section: t.id })}>
            {t.label}
          </button>
        ))}
      </nav>

      {url.section === 'overview' && (
        <section className="board">
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
          {sensor && series.data && points.length > 0 && <Chart points={points} anomalies={sensorItems} level={url.granularity} dark={theme === 'dark'} name={sensorName} onZoom={drillDown} onAnomalyClick={openAnomaly} />}

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
                {panel}
                {anomalies.error && <ErrorState message={anomalies.error} />}
                {anomaliesLoading && <Spinner label="Загрузка аномалий…" />}
                {anomalies.data && (
                  <>
                    <CountChips counts={listData.counts} />
                    {sensorItems.length === 0 ? <p className="muted small">За выбранный период и фильтры аномалий нет.</p> : <AnomalyList data={listData} onSelect={openAnomaly} />}
                  </>
                )}
              </>
            )}
          </aside>
        </section>
      )}

      {url.section === 'map' && (
        <section className="board">
          <div className="card map-card">
            <h3>Карта аномалий</h3>
            <MapStates error={sensors.error} loading={!sensors.data && !sensors.error} empty={!!sensors.data && features.length === 0} />
            {features.length > 0 && (
              <>
                <MapSection features={features} heat={heat} selectedId={sensor || null} dark={theme === 'dark'} onSelectSensor={pickSensor} />
                <div className="map-legend">
                  <span>размер точки — число аномалий за выбранный период (серая — ни одной)</span>
                  <span className="legend-levels">
                    цвет — самый частый уровень за период: <i className="dot lv-low" /> низкий · <i className="dot lv-medium" /> средний · <i className="dot lv-high" /> высокий · <i className="dot lv-critical" />{' '}
                    критический
                  </span>
                  <span>
                    <i className="dot ring-mega" /> кольцо — датчик с мега-аномалией; клик по точке выбирает датчик
                  </span>
                </div>
              </>
            )}
          </div>

          <aside className="card side">
            <h3>Подробнее</h3>
            {panel ?? <p className="muted small">Кликните по датчику на карте или по аномалии на графике — здесь появятся аномалии датчика и подробности. Фильтры действуют и на карту.</p>}
          </aside>
        </section>
      )}

      {url.section === 'compare' && (
        <section className="board">
          <Comparison road={url.road} from={from} to={to} skipRoad={SAMPLE_ROAD} onSelectAnomaly={openAnomaly} onSelectRoad={pickRoad} />
          <aside className="card side">
            <h3>Подробнее</h3>
            {panel ?? <p className="muted small">Кликните по метке на шкале времени или по строке таблицы различий — здесь появятся подробности аномалии. Фильтр дороги и периода действует и на сравнение.</p>}
          </aside>
        </section>
      )}
    </main>
  )
}
