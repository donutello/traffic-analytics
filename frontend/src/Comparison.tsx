import { useMemo, useState } from 'react'
import { get, urls } from './api'
import { barParts, pluralRu, SORT_LABELS, sortRows, timePct, axisTicks, type BarParts, type SortKey } from './comparison'
import { EmptyState, ErrorState, Spinner } from './States'
import { useAsync } from './useAsync'
import { LEVEL_CLASSES, longDate, type AnomalyItem, type ComparisonOut, type ComparisonShares, type ComparisonTotals, type RoadComparison } from './types'

/* The comparison section of issue #13 (FR4): our findings against the corporate system's.
   The three blocks answer the three questions in order: how much we agree (bars), WHEN we
   differ (parallel timelines) and WHAT exactly differs (tables). Row and tick clicks open
   the shared side panel through ?anomaly= (#12/#14), so a comparison view stays shareable. */

const PCT = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const TS = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: '2-digit', timeZone: 'Europe/Moscow' })

interface Props {
  /** The raw URL road filter: empty means every road (the section shows a row per road then). */
  road: string
  from: string
  to: string
  /** Road codes whose per-road breakdown is skipped in the all-roads view (the fictional sample). */
  skipRoad?: string
  onSelectAnomaly: (id: string) => void
  onSelectRoad: (code: string) => void
}

export default function Comparison({ road, from, to, skipRoad, onSelectAnomaly, onSelectRoad }: Props) {
  const request = useMemo(() => get<ComparisonOut>(urls.comparison(road, from, to)), [road, from, to])
  const res = useAsync(request, [request])

  if (res.error)
    return (
      <div className="cmp card">
        <ErrorState message={res.error} />
      </div>
    )
  if (!res.data)
    return (
      <div className="cmp card">
        <Spinner label="Загрузка сравнения алгоритмов…" />
      </div>
    )

  const roads = res.data.roads
  if (roads.length === 0)
    return (
      <div className="cmp card">
        <EmptyState message="По выбранным фильтрам нет ни наших, ни корпоративных находок — поменяйте дорогу или период." />
      </div>
    )

  // One selected road, or the response's first real road when the section covers all of them
  // (the timeline and the tables always dig into exactly one road; App passes the sample code to skip).
  const focus = roads.find((r) => r.road !== skipRoad) ?? roads[0]
  const showAll = roads.length > 1

  return (
    <div className="cmp">
      <div className="card">
        <h3>Совпадение и различия находок</h3>
        <p className="muted small">
          Период с {longDate(from)} по {longDate(to)}. «Совпало» — находки на одном датчике с перекрывающимся временем; одна находка может совпасть с несколькими.
        </p>
        <CmpLegend />
        <div className="cmp-cards">
          {roads.map((r) => (
            <RoadCard key={r.road} code={r.road} label={r.road_name} totals={r.totals} shares={r.shares} selectable={showAll} onPick={onSelectRoad} />
          ))}
          {showAll && <RoadCard code="" label="в сумме" totals={res.data.totals} shares={res.data.shares} selectable={false} />}
        </div>
      </div>

      <div className="card">
        <h3>Шкала времени — {focus.road_name}</h3>
        <p className="muted small">
          Каждая метка — находка за период: наш алгоритм сверху, корпоративная система снизу. Зелёные подтверждены второй стороной, пунктир связывает совпавшие; обводка — мега-аномалия. Клик по
          метке открывает подробности{showAll ? '; дорогу для разбора выбирайте карточкой или фильтром' : ''}.
        </p>
        <Timeline road={focus} from={from} to={to} onSelect={onSelectAnomaly} />
      </div>

      <DiffTables road={focus} onSelect={onSelectAnomaly} />
    </div>
  )
}

function CmpLegend() {
  return (
    <p className="cmp-legend">
      <span>
        <i className="swatch sw-match" /> совпало
      </span>
      <span>
        <i className="swatch sw-ours" /> только наш алгоритм
      </span>
      <span>
        <i className="swatch sw-corporate" /> только корпоративная система
      </span>
    </p>
  )
}

export function RoadBar({ totals }: { totals: ComparisonTotals }) {
  const b = barParts(totals)
  if (b.total === 0) return <p className="muted small">за период нет ни одной находки</p>
  return <BarInner b={b} />
}

function BarInner({ b }: { b: BarParts }) {
  const seg = (key: string, kind: string, n: number, pct: number, name: string) =>
    n > 0 && (
      <span key={key} className={`cmp-seg ${kind}`} style={{ flexGrow: n }} title={`${name}: ${n} (${PCT.format(pct)} %)`} aria-hidden>
        {pct >= 8 && <em>{PCT.format(pct)}%</em>}
      </span>
    )
  return (
    <div className="cmp-bar" role="img" aria-label={`совпало ${b.match} ${pluralRu(b.match, 'пара', 'пары', 'пар')}, только наш алгоритм ${b.onlyOurs}, только корпоративная система ${b.onlyCorporate}`}>
      {seg('match', 'seg-match', b.match, b.matchPct, 'совпало')}
      {seg('ours', 'seg-ours', b.onlyOurs, b.onlyOursPct, 'только наш алгоритм')}
      {seg('corporate', 'seg-corporate', b.onlyCorporate, b.onlyCorporatePct, 'только корпоративная система')}
    </div>
  )
}

function RoadCard({ code, label, totals, shares, selectable, onPick }: { code: string; label: string; totals: ComparisonTotals; shares: ComparisonShares; selectable: boolean; onPick?: (code: string) => void }) {
  // The card doubles as the «в сумме» grand total (not selectable) — then there is no road to pick.
  return (
    <div className="cmp-card">
      <h4>{selectable && onPick ? <button className="cmp-road" onClick={() => onPick(code)} title="показать сравнение по этой дороге">{label}</button> : <span>{label}</span>}</h4>
      <p className="counts">
        наш алгоритм: <b>{totals.ours}</b> · корпоративная система: <b>{totals.corporate}</b> · совпало пар: <b>{totals.both}</b>
      </p>
      <RoadBar totals={totals} />
      <p className="cmp-shares">
        <span title="доля наших находок, которые подтверждены корпоративной системой">наш алгоритм подтверждён корпоративным: <b>{PCT.format(shares.ours_found_pct)} %</b></span>
        <span title="доля находок корпоративной системы, которые нашёл и наш алгоритм">корпоративный подтверждён нашим: <b>{PCT.format(shares.corporate_found_pct)} %</b></span>
      </p>
    </div>
  )
}

interface Tick {
  item: AnomalyItem
  matched: boolean
}

function buildLanes(r: RoadComparison): { ours: Tick[]; corp: Tick[] } {
  const ours = new Map<string, Tick>()
  const corp = new Map<string, Tick>()
  for (const p of r.both_found) {
    ours.set(p.ours.id, { item: p.ours, matched: true })
    corp.set(p.corporate.id, { item: p.corporate, matched: true })
  }
  for (const a of r.only_ours) if (!ours.has(a.id)) ours.set(a.id, { item: a, matched: false })
  for (const a of r.only_corporate) if (!corp.has(a.id)) corp.set(a.id, { item: a, matched: false })
  return { ours: [...ours.values()], corp: [...corp.values()] }
}

function Timeline({ road: r, from, to, onSelect }: { road: RoadComparison; from: string; to: string; onSelect: (id: string) => void }) {
  const { ours, corp } = useMemo(() => buildLanes(r), [r])
  if (ours.length === 0 && corp.length === 0) return <p className="muted small">за период нет ни одной находки</p>

  const lo = Date.parse(from)
  const hi = Date.parse(to)
  const ticks = axisTicks(lo, hi)

  const lane = (list: Tick[], cls: string) => (
    <div className={`cmp-lane ${cls}`}>
      {list.map((t) => (
        <button
          key={t.item.id}
          className={`cmp-tick ${t.matched ? 't-match' : cls === 'lane-ours' ? 't-ours' : 't-corporate'}${t.item.is_mega ? ' t-mega' : ''}`}
          style={{ left: `${timePct(lo, hi, t.item.starts_at)}%` }}
          title={`${t.item.starts_label} · ${t.item.type_label}`}
          aria-label={`${t.item.starts_label} · ${t.item.type_label}`}
          onClick={() => onSelect(t.item.id)}
        />
      ))}
    </div>
  )

  return (
    <div className="cmp-timeline">
      <div className="cmp-plot">
        <div className="cmp-rows">
          <div className="cmp-ylabel">наш алгоритм</div>
          {lane(ours, 'lane-ours')}
          <div className="cmp-ylabel">корпоративная система</div>
          {lane(corp, 'lane-corporate')}
        </div>
        <svg className="cmp-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          {r.both_found.map((p, i) => (
            <line key={i} x1={timePct(lo, hi, p.ours.starts_at)} y1={25} x2={timePct(lo, hi, p.corporate.starts_at)} y2={75} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
      </div>
      <div className="cmp-axis">
        {ticks.map((t, i) => (
          <span key={i} style={{ left: `${(100 * i) / Math.max(1, ticks.length - 1)}%`, transform: i === 0 ? 'none' : i === ticks.length - 1 ? 'translateX(-100%)' : 'translateX(-50%)' }}>
            {TS.format(t)}
          </span>
        ))}
      </div>
    </div>
  )
}

type Sort = { key: SortKey; dir: 1 | -1 }

function DiffTables({ road: r, onSelect }: { road: RoadComparison; onSelect: (id: string) => void }) {
  const [sorts, setSorts] = useState<Record<'ours' | 'corporate' | 'pairs', Sort>>({ ours: { key: 'time', dir: 1 }, corporate: { key: 'time', dir: 1 }, pairs: { key: 'time', dir: 1 } })
  const toggle = (table: 'ours' | 'corporate' | 'pairs') => (key: SortKey) =>
    setSorts((s) => ({ ...s, [table]: { key, dir: s[table].key === key && s[table].dir === 1 ? -1 : 1 } }))

  return (
    <div className="card">
      <h3>Различия — {r.road_name}</h3>
      {r.totals.ours + r.totals.corporate === 0 ? (
        <p className="muted small">за период нет ни одной находки</p>
      ) : (
        <>
          <h4>Найдено только нами · {r.only_ours.length}</h4>
          {r.only_ours.length === 0 ? <EmptyLine text="наш алгоритм не нашёл ничего, чего нет у корпоративной системы" /> : <ItemsTable items={sortRows(r.only_ours, sorts.ours.key, sorts.ours.dir, (x) => x)} sort={sorts.ours} onSort={toggle('ours')} onSelect={onSelect} />}

          <h4>Только корпоративной системой · {r.only_corporate.length}</h4>
          {r.only_corporate.length === 0 ? <EmptyLine text="корпоративная система не нашла ничего, чего нет у нас" /> : <ItemsTable items={sortRows(r.only_corporate, sorts.corporate.key, sorts.corporate.dir, (x) => x)} sort={sorts.corporate} onSort={toggle('corporate')} onSelect={onSelect} />}

          <h4>
            Совпало · {r.both_found.length} {pluralRu(r.both_found.length, 'пара', 'пары', 'пар')}
          </h4>
          {r.both_found.length === 0 ? <EmptyLine text="совпадений нет" /> : <PairTable rows={sortRows(r.both_found, sorts.pairs.key, sorts.pairs.dir, (p) => p.ours)} sort={sorts.pairs} onSort={toggle('pairs')} onSelect={onSelect} />}
        </>
      )}
    </div>
  )
}

function EmptyLine({ text }: { text: string }) {
  return <p className="muted small">{text}</p>
}

function Th({ label, k, sort, onSort }: { label: string; k: SortKey; sort: Sort; onSort: (k: SortKey) => void }) {
  return (
    <th aria-sort={sort.key === k ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button onClick={() => onSort(k)}>
        {label}
        {sort.key === k && <span aria-hidden> {sort.dir === 1 ? '▲' : '▼'}</span>}
      </button>
    </th>
  )
}

const SORT_KEYS: SortKey[] = ['time', 'sensor', 'type', 'level']

function Row({ item, onClick, cols }: { item: AnomalyItem; onClick: () => void; cols: number }) {
  return (
    <tr tabIndex={0} role="button" onClick={onClick} onKeyDown={(e) => e.key === 'Enter' && onClick()} aria-label={`${item.starts_label} · ${item.sensor_name} · ${item.type_label}`}>
      <td>{item.starts_label}</td>
      <td>{item.sensor_name}</td>
      <td>{item.type_label}</td>
      <td>
        <span className={`dot ${LEVEL_CLASSES[item.level]}`} aria-hidden /> {item.level_label}
      </td>
      {Array.from({ length: Math.max(0, cols - 4) }, (_, i) => (
        <td key={i} />
      ))}
    </tr>
  )
}

function ItemsTable({ items, sort, onSort, onSelect }: { items: AnomalyItem[]; sort: Sort; onSort: (k: SortKey) => void; onSelect: (id: string) => void }) {
  return (
    <div className="cmp-table-wrap">
      <table className="cmp-table">
        <thead>
          <tr>
            {SORT_KEYS.map((k) => (
              <Th key={k} label={SORT_LABELS[k]} k={k} sort={sort} onSort={onSort} />
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((a) => (
            <Row key={a.id} item={a} cols={4} onClick={() => onSelect(a.id)} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PairTable({ rows, sort, onSort, onSelect }: { rows: { ours: AnomalyItem; corporate: AnomalyItem }[]; sort: Sort; onSort: (k: SortKey) => void; onSelect: (id: string) => void }) {
  return (
    <div className="cmp-table-wrap">
      <table className="cmp-table">
        <thead>
          <tr>
            {SORT_KEYS.map((k) => (
              <Th key={k} label={SORT_LABELS[k]} k={k} sort={sort} onSort={onSort} />
            ))}
            <th>корп. время</th>
            <th>корп. уровень</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={`${p.ours.id}~${p.corporate.id}`} tabIndex={0} role="button" onClick={() => onSelect(p.ours.id)} onKeyDown={(e) => e.key === 'Enter' && onSelect(p.ours.id)} aria-label={`${p.ours.starts_label} · ${p.ours.sensor_name} · ${p.ours.type_label}`}>
              <td>{p.ours.starts_label}</td>
              <td>{p.ours.sensor_name}</td>
              <td>{p.ours.type_label}</td>
              <td>
                <span className={`dot ${LEVEL_CLASSES[p.ours.level]}`} aria-hidden /> {p.ours.level_label}
              </td>
              <td>{p.corporate.starts_label}</td>
              <td>
                <span className={`dot ${LEVEL_CLASSES[p.corporate.level]}`} aria-hidden /> {p.corporate.level_label}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
