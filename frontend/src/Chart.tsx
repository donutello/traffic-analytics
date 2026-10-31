import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'
import { STATE_LABELS, type Point, type State } from './types'

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** Consecutive anomaly hours as red background bands. Ends open on the next point so single-hour bands stay visible. */
function anomalyBands(points: Point[]): [string, string][] {
  const bands: [string, string][] = []
  for (let i = 0, start = -1; i <= points.length; i++) {
    const isAnomaly = i < points.length && points[i].state === 'anomaly'
    if (isAnomaly && start < 0) start = i
    if (!isAnomaly && start >= 0) {
      bands.push([points[start].ts, points[Math.min(i, points.length - 1)].ts])
      start = -1
    }
  }
  return bands
}

export default function Chart({ points, dark, name }: { points: Point[]; dark: boolean; name: string }) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<ReturnType<typeof echarts.init> | null>(null)

  useEffect(() => {
    const onResize = () => chart.current?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.current?.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    if (!el.current || points.length === 0) return
    chart.current ??= echarts.init(el.current)
    const stateColor: Record<State, string> = { normal: cssVar('--color-normal'), anomaly: cssVar('--color-anomaly'), imputed: cssVar('--color-imputed') }
    const muted = cssVar('--color-muted')
    const border = cssVar('--color-border')
    const dot = (color: string) => `<span style="color:${color}">●</span>`
    chart.current.setOption(
      {
        animation: false,
        grid: { left: 56, right: 20, top: 24, bottom: 64 },
        tooltip: {
          trigger: 'axis',
          formatter: (items: unknown) => {
            const p = points[(items as { dataIndex: number }[])[0].dataIndex]
            return `${p.label}<br/>${p.volume} авт./ч<br/>${dot(stateColor[p.state])} ${STATE_LABELS[p.state]}`
          },
        },
        textStyle: { color: muted },
        xAxis: {
          // Categories are the unique timestamps (labels repeat every day at hour grain), shown short.
          type: 'category',
          data: points.map((p) => p.ts),
          axisLabel: { formatter: (_: string, index: number) => points[index].label },
          axisLine: { lineStyle: { color: border } },
          axisTick: { show: false },
        },
        yAxis: { type: 'value', name: 'авт./ч', splitLine: { lineStyle: { color: border } } },
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 22, bottom: 12 }],
        series: [
          {
            type: 'line',
            data: points.map((p) => p.volume),
            showSymbol: points.length < 10,
            symbolSize: 8,
            lineStyle: { color: stateColor.normal, width: 2 },
            areaStyle: { color: stateColor.normal, opacity: dark ? 0.12 : 0.07 },
            markArea: {
              silent: true,
              itemStyle: { color: stateColor.anomaly, opacity: 0.12 },
              data: anomalyBands(points).map(([a, b]) => [{ xAxis: a }, { xAxis: b }]),
            },
          },
          ...(['anomaly', 'imputed'] as State[]).map((state) => ({
            type: 'scatter',
            symbolSize: state === 'anomaly' ? 8 : 6,
            itemStyle: { color: stateColor[state], borderColor: cssVar('--color-surface'), borderWidth: 1 },
            data: points.map((p, i) => (p.state === state ? [i, p.volume] : null)).filter((v): v is [number, number] => v !== null),
          })),
        ],
      },
      true,
    )
  }, [points, dark])

  return (
    <div className="chart-card card">
      <h3 className="chart-title">Датчик {name}</h3>
      <div ref={el} style={{ height: 400 }} />
      <p className="chart-hint">Колесом или ползунком внизу — зум по времени. Точки в цветовой схеме состояний: норма / аномалия / восстановлено.</p>
    </div>
  )
}
