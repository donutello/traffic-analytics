import { LineChart } from 'echarts/charts'
import {
  BrushComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkPointComponent,
  ToolboxComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import { STATE_LABELS, type AnomalyItem, type Granularity, type Point, type State } from './types'

/* Only what this chart uses (docs/adr/0008), so the bundle stays sane. */
echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent, BrushComponent, ToolboxComponent, CanvasRenderer])

const BUCKET_MS: Record<Granularity, number> = { hour: 3_600_000, day: 86_400_000, week: 7 * 86_400_000 }

const HINTS: Record<Granularity, string> = {
  week: 'Выделите мышью фрагмент (кнопка выделения в правом верхнем углу графика) — загрузится уровень «день». Флажок и подсветка — аномалия, клик по ней покажет подробности. Колесо мыши и ползунок — обычный зум.',
  day: 'Выделите фрагмент — загрузится уровень «час». Колесо мыши и ползунок — обычный зум.',
  hour: 'Это самый детальный уровень: выделение и ползунок только приближают окно.',
}

const DATE_FMT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Moscow' })
const DATETIME_FMT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' })
const SHORT_DATE_FMT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: 'Europe/Moscow' })
const NUM = new Intl.NumberFormat('ru-RU')

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** cssVar() returns a '#rrggbb' token; markArea shading needs a translucent form. */
function rgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const n = parseInt(full, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/** Point indexes whose buckets overlap [starts_at, ends_at) — markArea endpoints must be real axis values. */
function bucketRange(points: Point[], a: AnomalyItem, level: Granularity): [number, number] | null {
  const start = Date.parse(a.starts_at)
  const end = Date.parse(a.ends_at)
  let first = -1
  let last = -1
  for (let i = 0; i < points.length; i++) {
    const t = Date.parse(points[i].ts)
    if (t < end && start < t + BUCKET_MS[level]) {
      if (first < 0) first = i
      last = i
    }
  }
  return first < 0 ? null : [first, last]
}

/** The anomaly whose interval overlaps the hovered point's bucket — its title joins the tooltip ("+ anomaly title" of #11). */
function coveringAnomaly(points: Point[], idx: number, level: Granularity, anomalies: AnomalyItem[]): AnomalyItem | undefined {
  const t = Date.parse(points[idx].ts)
  const bucketEnd = t + BUCKET_MS[level]
  return anomalies.find((a) => Date.parse(a.starts_at) < bucketEnd && Date.parse(a.ends_at) > t)
}

function pointTitle(p: Point, level: Granularity): string {
  const d = new Date(p.ts)
  if (level === 'hour') return DATETIME_FMT.format(d)
  if (level === 'day') return DATE_FMT.format(d)
  return `неделя с ${DATE_FMT.format(d)}`
}

interface Props {
  points: Point[]
  anomalies: AnomalyItem[]
  level: Granularity
  dark: boolean
  name: string
  /** The user brush-selected a window: the ts values (week/day are dates, hour is ISO time) of both ends. */
  onZoom: (fromTs: string, toTs: string) => void
  /** The user clicked an anomaly marker or band; the id goes to the detail (full panel comes in #12). */
  onAnomalyClick: (id: string) => void
}

export default function Chart({ points, anomalies, level, dark, name, onZoom, onAnomalyClick }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<ReturnType<typeof echarts.init> | null>(null)
  const pointsRef = useRef<Point[]>(points)
  const onZoomRef = useRef(onZoom)
  const onAnomalyClickRef = useRef(onAnomalyClick)

  // Handlers bound at mount read the latest props through refs, so they never need rebinding.
  useEffect(() => {
    pointsRef.current = points
    onZoomRef.current = onZoom
    onAnomalyClickRef.current = onAnomalyClick
  })

  useEffect(() => {
    if (!el.current) return
    const c = echarts.init(el.current)
    chart.current = c
    c.on('click', (params) => {
      const data = params.data as { id?: string } | undefined
      if ((params.componentType === 'markPoint' || params.componentType === 'markArea') && data?.id) onAnomalyClickRef.current(String(data.id))
    })
    // lineX brush = the "select a period with the mouse" of FR1; the final selection (not the moving preview) steps the level.
    c.on('brushSelected', (params) => {
      const batch = (params as { batch?: { ismoving?: boolean; areas?: { coordRange?: number[] }[] }[] }).batch?.[0]
      if (!batch || batch.ismoving) return
      const range = batch.areas?.find((a) => a.coordRange)?.coordRange
      if (!range) return
      const pts = pointsRef.current
      if (pts.length < 2) return
      const i = Math.max(0, Math.min(pts.length - 1, Math.floor(range[0])))
      const j = Math.max(i, Math.min(pts.length - 1, Math.ceil(range[1])))
      c.dispatchAction({ type: 'brush', areas: [] })
      if (j > i) onZoomRef.current(pts[i].ts, pts[j].ts)
    })
    const onResize = () => c.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      c.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    if (!chart.current || points.length === 0) return
    const stateColor: Record<State, string> = { normal: cssVar('--color-normal'), anomaly: cssVar('--color-anomaly'), imputed: cssVar('--color-imputed') }
    const megaColor = cssVar('--color-mega')
    const muted = cssVar('--color-muted')
    const border = cssVar('--color-border')
    const surface = cssVar('--color-surface')
    const dot = (color: string) => `<span style="color:${color}">●</span>`
    const values = (state: State) => points.map((p) => (p.state === state ? p.volume : null))

    const marks = anomalies
      .map((a) => ({ a, range: bucketRange(points, a, level) }))
      .filter((m): m is { a: AnomalyItem; range: [number, number] } => m.range !== null)

    const markAreas = marks.map(({ a, range }) => {
      const first = range[0]
      const lastTs = points[Math.min(range[1] + 1, points.length - 1)].ts
      const style = a.is_mega
        ? { color: rgba(megaColor, 0.18), borderColor: megaColor, borderWidth: 2, borderType: 'solid' as const }
        : a.category === 'technical'
          ? { color: rgba(stateColor.imputed, 0.12), borderColor: stateColor.imputed, borderWidth: 1, borderType: 'dashed' as const }
          : { color: rgba(stateColor.anomaly, 0.13), borderWidth: 0 }
      return [{ name: a.type_label, id: a.id, xAxis: points[first].ts, itemStyle: style, cursor: 'pointer', label: { show: a.is_mega, position: 'insideTop' as const, color: megaColor, fontSize: 11, fontWeight: 700 as const, formatter: 'МЕГА' } }, { xAxis: lastTs }]
    })

    const pins = marks.map(({ a, range }) => ({
      name: a.type_label,
      id: a.id,
      coord: [range[0], points[range[0]].volume] as [number, number],
      symbol: 'pin',
      symbolSize: a.is_mega ? 34 : 24,
      itemStyle: { color: a.is_mega ? megaColor : a.category === 'technical' ? stateColor.imputed : stateColor.anomaly },
    }))

    chart.current.setOption(
      {
        animation: false,
        grid: { left: 64, right: 24, top: 52, bottom: 68 },
        legend: { top: 4, left: 0, data: [STATE_LABELS.normal, STATE_LABELS.anomaly, STATE_LABELS.imputed], textStyle: { color: muted }, inactiveColor: border },
        toolbox: {
          top: 0,
          right: 8,
          itemSize: 16,
          iconStyle: { borderColor: muted },
          feature: { brush: { type: ['lineX', 'clear'], title: { lineX: 'выделить промежуток', clear: 'убрать выделение' } } },
        },
        brush: { xAxisIndex: 0, brushLink: 'all', outOfBrush: { colorAlpha: 0.35 }, throttleType: 'debounce', throttleDelay: 150 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: surface,
          borderColor: border,
          textStyle: { color: cssVar('--color-text') },
          formatter: (items: unknown) => {
            const arr = items as { dataIndex: number }[]
            const p = points[arr?.[0]?.dataIndex]
            if (!p) return ''
            const inside = coveringAnomaly(points, arr[0].dataIndex, level, anomalies)
            return [
              pointTitle(p, level),
              `${NUM.format(p.volume)} авт./ч`,
              `${dot(stateColor[p.state])} ${STATE_LABELS[p.state]}`,
              ...(inside ? [`${dot(inside.is_mega ? megaColor : stateColor.anomaly)} ${inside.type_label}`] : []),
            ].join('<br/>')
          },
        },
        textStyle: { color: muted },
        xAxis: {
          // Categories are the unique timestamps (labels repeat every day at hour grain), shown short.
          type: 'category',
          boundaryGap: false,
          data: points.map((p) => p.ts),
          axisLabel: {
            formatter: (_: string, index: number) => (level === 'hour' && points[index].label === '00:00' ? SHORT_DATE_FMT.format(new Date(points[index].ts)) : points[index].label),
          },
          axisLine: { lineStyle: { color: border } },
          axisTick: { show: false },
        },
        yAxis: { type: 'value', name: 'авт./ч', splitLine: { lineStyle: { color: border } } },
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 22, bottom: 14, borderColor: border, fillerColor: rgba(stateColor.normal, 0.15), textStyle: { color: muted } }],
        series: [
          {
            // One series per state, gaps elsewhere: each state draws only its own contiguous runs (FR2).
            id: 'normal',
            name: STATE_LABELS.normal,
            type: 'line',
            data: values('normal'),
            connectNulls: false,
            // A whole road period at hour grain is 20k+ points: decimate for drawing only; zoomed windows stay exact.
            sampling: points.length > 5000 ? 'lttb' : undefined,
            showSymbol: points.length < 10,
            symbolSize: 6,
            lineStyle: { color: stateColor.normal, width: 2, type: 'solid' },
            itemStyle: { color: stateColor.normal },
            areaStyle: { color: stateColor.normal, opacity: dark ? 0.12 : 0.07 },
            markArea: { data: markAreas },
            markPoint: { data: pins, silent: false },
          },
          {
            id: 'anomaly',
            name: STATE_LABELS.anomaly,
            type: 'line',
            data: values('anomaly'),
            connectNulls: false,
            showSymbol: true,
            symbol: 'diamond',
            symbolSize: 8,
            lineStyle: { color: stateColor.anomaly, width: 2, type: 'solid' },
            itemStyle: { color: stateColor.anomaly, borderColor: surface, borderWidth: 1 },
            z: 3,
          },
          {
            // Dashed, run by run (nulls between runs break the line): a filled gap never looks like measured data (FR2).
            id: 'imputed',
            name: STATE_LABELS.imputed,
            type: 'line',
            data: values('imputed'),
            connectNulls: false,
            showSymbol: true,
            symbolSize: 5,
            lineStyle: { color: stateColor.imputed, width: 2, type: 'dashed' },
            itemStyle: { color: stateColor.imputed, borderColor: surface, borderWidth: 1 },
            z: 2,
          },
        ],
      },
      true,
    )
  }, [points, anomalies, level, dark])

  return (
    <div className="chart-card card">
      <h3 className="chart-title">Датчик {name}</h3>
      <div ref={el} className="chart-canvas" />
      <p className="chart-hint">{HINTS[level]}</p>
    </div>
  )
}
