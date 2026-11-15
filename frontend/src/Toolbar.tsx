import type { UrlState } from './urlState'
import { GRANULARITY_LABELS, LEVEL_CLASSES, LEVEL_LABELS, SOURCE_FILTER_LABELS, ZOOM_ORDER, type Level, type Period, type Road, type SensorFeature } from './types'

/* The compact filter row of issue #14. Every control only edits the shared URL state, so
   all sections (chart, map, anomaly list) react to the same click and the view is shareable.
   The type names come from the API (type_label of the loaded window); nothing is duplicated here. */

interface Props {
  state: UrlState
  roads: Road[]
  /** Resolved values to show, while the URL may still hold the empty defaults. */
  road: string
  sensor: string | null
  features: SensorFeature[]
  typeLabels: Record<string, string>
  period: Period | null
  onPatch: (patch: Partial<UrlState>) => void
}

const LEVEL_CODES = Object.keys(LEVEL_LABELS) as Level[]

export default function Toolbar({ state, roads, road, sensor, features, typeLabels, period, onPatch }: Props) {
  const zoomed = state.from !== '' || state.to !== '' || state.granularity !== 'week'
  // options of open-ended detector codes: what the window has, plus the shared ?type= even if absent
  const typeCodes = [...new Set([...Object.keys(typeLabels), ...(state.type ? [state.type] : [])])]
  // Only the comparison section knows the "every road" view (issue #13); elsewhere an empty road resolves to the first one.
  const compareAll = state.section === 'compare'

  return (
    <div className="card toolbar" role="group" aria-label="Фильтры">
      <label className="tb-field">
        <span>Дорога</span>
        <select
          value={compareAll ? state.road || '*' : road}
          onChange={(e) => onPatch({ road: e.target.value === '*' ? '' : e.target.value, sensor: '', anomaly: '', from: '', to: '', granularity: 'week' })}
        >
          {compareAll && <option value="*">все дороги</option>}
          {roads.map((r) => (
            <option key={r.code} value={r.code}>
              {r.name}
            </option>
          ))}
        </select>
      </label>

      <label className="tb-field">
        <span>Датчик</span>
        <select value={sensor ?? ''} onChange={(e) => onPatch({ sensor: e.target.value, anomaly: '' })}>
          {features.map((f) => (
            <option key={f.properties.id} value={f.properties.id}>
              {f.properties.name}
            </option>
          ))}
        </select>
      </label>

      <label className="tb-field">
        <span>Период с</span>
        <input type="date" value={state.from.slice(0, 10)} onChange={(e) => onPatch({ from: e.target.value, anomaly: '' })} />
      </label>
      <label className="tb-field">
        <span>по</span>
        <input type="date" value={state.to.slice(0, 10)} onChange={(e) => onPatch({ to: e.target.value, anomaly: '' })} />
      </label>
      {period && (state.from || state.to) && (
        <button className="tb-plain" onClick={() => onPatch({ from: '', to: '' })} title={`${period.from} — ${period.to}`}>
          весь период
        </button>
      )}

      <label className="tb-field">
        <span>Тип аномалии</span>
        <select value={state.type} onChange={(e) => onPatch({ type: e.target.value })}>
          <option value="">все типы</option>
          {typeCodes
            .sort((a, b) => (typeLabels[a] ?? a).localeCompare(typeLabels[b] ?? b, 'ru'))
            .map((code) => (
              <option key={code} value={code}>
                {typeLabels[code] ?? code}
              </option>
            ))}
        </select>
      </label>

      <div className="tb-field">
        <span>Источник</span>
        <div className="seg" role="group" aria-label="Источник аномалий">
          {(['all', 'ours', 'corporate'] as const).map((s) => (
            <button key={s} aria-pressed={(state.source || 'all') === s} onClick={() => onPatch({ source: s === 'all' ? '' : s })}>
              {SOURCE_FILTER_LABELS[s]}
            </button>
          ))}
        </div>
      </div>

      <div className="tb-field">
        <span>Уровень</span>
        <div className="seg" role="group" aria-label="Уровень аномалий">
          <button aria-pressed={state.level === ''} onClick={() => onPatch({ level: '' })}>
            все
          </button>
          {LEVEL_CODES.map((l) => (
            <button key={l} className={LEVEL_CLASSES[l]} aria-pressed={state.level === l} onClick={() => onPatch({ level: state.level === l ? '' : l })}>
              {LEVEL_LABELS[l]}
            </button>
          ))}
        </div>
      </div>

      <div className="tb-field">
        <span>Детализация</span>
        <div className="seg" role="group" aria-label="Детализация графика">
          {ZOOM_ORDER.map((g) => (
            <button key={g} aria-pressed={state.granularity === g} onClick={() => onPatch({ granularity: g, anomaly: '' })}>
              {GRANULARITY_LABELS[g]}
            </button>
          ))}
        </div>
      </div>

      {zoomed && (
        <button className="tb-plain" onClick={() => onPatch({ from: '', to: '', granularity: 'week', anomaly: '' })}>
          к началу периода
        </button>
      )}
    </div>
  )
}
