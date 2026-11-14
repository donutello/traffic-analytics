import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef, useState } from 'react'
import { cssVar } from './cssVar'
import { EmptyState, ErrorState, Spinner } from './States'
import type { Level, SensorFeature, SensorHeat } from './types'

/* Issue #12, docs/adr/0008: Leaflet used directly through refs, OSM raster tiles (no key),
   and the offline fallback stays schematic: tiles hide, markers and clicks keep working. */

const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_CREDIT = '&copy; OpenStreetMap'
/** Somewhere between the four project roads (Lipetsk … Saratov); the fit below overrides it. */
const FALLBACK_CENTER: L.LatLngExpression = [52.2, 40.7]

const LEVEL_VAR: Record<Level, string> = { low: '--lv-low', medium: '--lv-medium', high: '--lv-high', critical: '--lv-critical' }

/** sqrt scale for the marker size: many anomalies grow the point, but never into balloons. */
function radius(count: number): number {
  return count <= 0 ? 5 : Math.min(22, 6 + Math.sqrt(count) * 3)
}

const latlng = (f: SensorFeature): [number, number] => [f.geometry.coordinates[1], f.geometry.coordinates[0]]

interface Props {
  features: SensorFeature[]
  /** Per sensor, counted client-side over the window with the toolbar filters applied. */
  heat: Record<string, SensorHeat>
  selectedId: string | null
  /** Just a redraw trigger: marker colors re-read the palette tokens of the new theme. */
  dark: boolean
  onSelectSensor: (id: string) => void
}

export default function MapSection({ features, heat, selectedId, dark, onSelectSensor }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const markers = useRef<L.LayerGroup | null>(null)
  const [tilesDown, setTilesDown] = useState(false)

  useEffect(() => {
    if (!el.current) return
    const m = L.map(el.current, { center: FALLBACK_CENTER, zoom: 7 })
    map.current = m
    markers.current = L.layerGroup().addTo(m)
    const tiles = L.tileLayer(TILE_URL, { maxZoom: 19, attribution: TILE_CREDIT })
    // NFR10 of ADR 0008: no network, no tiles — hide them and say so, the markers stay usable.
    tiles.on('tileerror', () => setTilesDown(true))
    tiles.addTo(m)
    return () => {
      m.remove()
      map.current = null
      markers.current = null
    }
  }, [])

  useEffect(() => {
    const group = markers.current
    const m = map.current
    if (!group || !m) return
    group.clearLayers()
    const idle = cssVar('--color-muted')
    const border = cssVar('--color-surface')
    const picked = cssVar('--color-text')
    for (const f of features) {
      const p = f.properties
      const h = heat[p.id]
      const color = h && h.count > 0 && h.level ? cssVar(LEVEL_VAR[h.level]) : idle
      const marker = L.circleMarker(latlng(f), {
        radius: radius(h?.count ?? 0),
        color: selectedId === p.id ? picked : border,
        weight: selectedId === p.id ? 3 : 1.5,
        fillColor: color,
        fillOpacity: 0.8,
        // static accent ring that breathes (index.css), marking sensors with mega anomalies
        className: p.is_mega ? 'sensor-marker sensor-mega' : 'sensor-marker',
      })
      marker.bindTooltip(`${p.name} · ${h?.count ?? 0}`)
      marker.on('click', () => onSelectSensor(p.id))
      marker.addTo(group)
    }
  }, [features, heat, selectedId, dark, onSelectSensor])

  // Road (or window) changed with the filters: show all of that road's sensors at once.
  useEffect(() => {
    const m = map.current
    if (!m || features.length === 0) return
    const points = features.map(latlng)
    if (points.length === 1) m.setView(points[0], 11)
    else m.fitBounds(L.latLngBounds(points).pad(0.25))
  }, [features])

  // A sensor picked in the toolbar or on the map: bring it into view.
  useEffect(() => {
    const m = map.current
    const f = features.find((x) => x.properties.id === selectedId)
    if (m && f) m.panTo(latlng(f))
  }, [selectedId, features])

  return (
    <div ref={el} className={`map-canvas${tilesDown ? ' tiles-down' : ''}`} role="application" aria-label="Карта датчиков">
      {tilesDown && (
        <p className="map-note" role="status">
          нет сети для тайлов
        </p>
      )}
    </div>
  )
}

export function MapStates({ error, loading, empty }: { error: string | null; loading: boolean; empty: boolean }) {
  if (error) return <ErrorState message={error} />
  if (loading) return <Spinner label="Загрузка датчиков…" />
  if (empty) return <EmptyState message="На этой дороге нет датчиков." />
  return null
}
