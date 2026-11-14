import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef, useState } from 'react'
import AnomalyList, { CountChips } from './AnomalyList'
import type { SensorAnomalies, SensorFeature, SensorProps } from './types'

const CENTRE: L.LatLngExpression = [51.6, 39.2]

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function sensorLayer(features: SensorFeature[], selected: string | null, onClick: (id: string) => void): L.GeoJSON {
  const normal = cssVar('--color-normal')
  const anomaly = cssVar('--color-anomaly')
  return L.geoJSON(
    { type: 'FeatureCollection', features } as unknown as GeoJSON.FeatureCollection,
    {
      pointToLayer: (feature, latlng) => {
        const f = feature as unknown as SensorFeature
        const props = f.properties
        return L.circleMarker(latlng, {
          radius: props.is_mega ? 10 : props.anomaly_count > 0 ? 8 : 6,
          color: props.id === selected ? cssVar('--color-text') : normal,
          weight: props.id === selected ? 3 : 2,
          fillColor: props.anomaly_count > 0 ? anomaly : normal,
          fillOpacity: props.anomaly_count > 0 ? 0.85 : 0.5,
        }).bindTooltip(`${props.name} · аномалий: ${props.anomaly_count}`, { direction: 'top' })
      },
      onEachFeature: (feature, layer) => {
        const f = feature as unknown as SensorFeature
        layer.on('click', () => onClick(f.properties.id))
      },
    },
  )
}

export default function MapSection({
  features,
  sensor,
  setSensor,
  focus,
  anomalies,
  openDetail,
  dark,
}: {
  features: SensorFeature[]
  sensor: string | null
  setSensor: (id: string) => void
  focus: string | null
  anomalies: SensorAnomalies | null
  openDetail: (id: string) => void
  dark: boolean
}) {
  const mainEl = useRef<HTMLDivElement>(null)
  const miniEl = useRef<HTMLDivElement>(null)
  const maps = useRef<L.Map[]>([])
  const fitted = useRef(false)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    const make = (el: HTMLElement, zoom: number, interactive: boolean) =>
      L.map(el, interactive ? { attributionControl: false } : { zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, touchZoom: false, keyboard: false, attributionControl: false }).setView(CENTRE, zoom)
    const main = make(mainEl.current!, 9, true)
    const mini = make(miniEl.current!, 7, false)
    for (const map of [main, mini]) {
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).on('tileerror', () => setOffline(true)).addTo(map)
    }
    maps.current = [main, mini]
    return () => {
      for (const map of maps.current) map.remove()
      maps.current = []
      fitted.current = false
    }
  }, [])

  useEffect(() => {
    const ids = sensorLayer(features, sensor, setSensor)
    const mini = sensorLayer(features, sensor, setSensor)
    ids.addTo(maps.current[0])
    mini.addTo(maps.current[1])
    if (!fitted.current && features.length > 0) {
      maps.current[0].fitBounds(ids.getBounds().pad(0.3))
      fitted.current = true
    }
    return () => {
      ids.remove()
      mini.remove()
    }
  }, [features, sensor, setSensor, dark])

  useEffect(() => {
    // Center only on explicit picks; without this the auto-selected first sensor would override fitBounds on arrival.
    const found = focus ? features.find((f) => f.properties.id === focus) : undefined
    if (found) maps.current[0]?.setView([found.geometry.coordinates[1], found.geometry.coordinates[0]], 10)
  }, [focus, features])

  const props: SensorProps | undefined = features.find((f) => f.properties.id === sensor)?.properties

  return (
    <section className="map-row">
      <div className={`card map-wrap${offline ? ' offline' : ''}`}>
        <div ref={mainEl} className="map" />
        <div className="mini-box">
          <div ref={miniEl} className="mini" />
          <span>обзор</span>
        </div>
        {offline && <p className="map-note">Карты OpenStreetMap не загрузились — маркеры видны на схематичном фоне.</p>}
      </div>
      <aside className="card panel">
        {!sensor && <p className="hint">Кликните маркер датчика на карте — здесь появится список его аномалий.</p>}
        {sensor && props && (
          <>
            <h3>
              Датчик {props.name} <span className="muted">· км {props.km}</span>
            </h3>
            <p className="muted small">
              {props.directions.direct} / {props.directions.reverse}
            </p>
            {anomalies && anomalies.anomalies.length > 0 ? (
              <>
                <CountChips counts={anomalies.counts} />
                <AnomalyList data={anomalies} onSelect={openDetail} />
              </>
            ) : (
              <p className="hint">Аномалий по этому датчику нет.</p>
            )}
          </>
        )}
      </aside>
    </section>
  )
}
