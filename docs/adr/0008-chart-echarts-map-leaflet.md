# 0008. Chart: ECharts. Map: Leaflet

- Status: accepted
- Date: 2026-10-31
- Author: @donutello

## Context

The dashboard needs an interactive time series chart (FR1, FR2): a long hourly series per sensor, zoom from weeks to single days, points coloured by three data states, marked anomaly intervals. And a map of sensors (FR3): a few hundred markers at most, clickable, with a side panel linked to them. The chart and the map share one state palette. The tile layer is OpenStreetMap (no API key), and the demo machine may be offline (NFR10).

## Decision

- Chart: [ECharts](https://echarts.apache.org/), loaded whole (`import * as echarts`). Line + scatter for the state points + `markArea` for anomaly intervals; `dataZoom` gives wheel and slider zoom without extra code.
- Map: [Leaflet](https://leafletjs.com/) with the standard OSM raster tiles, used directly (its API is small enough inside two `useEffect`s), with an OpenLayers-style minimap in the corner of the map section.
- Both read the state colors from the CSS variables in `index.css` at render time, so one palette drives the chart, the markers and the lists (FR2), in both themes.

## Alternatives

- **Chart.js:** smaller, but time-axis zooming needs a plugin, and marked intervals need another one; ECharts has both built in, as the issue suggested.
- **vis-timeline / Apache Superset-style widgets:** heavier than we need.
- **MapLibre GL:** vector tiles and 60 fps panning we don't need for a few hundred markers; Leaflet is less code and works fine with plain OSM raster tiles.
- **react-leaflet:** a React wrapper whose version must match React's majors; Leaflet managed in refs is a dozen lines and one dependency fewer.

## Consequences

- Two more runtime dependencies (~450 KB gz for echarts, ~50 KB for leaflet): acceptable for a dashboard whose chart library was the plan from the start (NFR1 budgets 3 s on fast internet).
- ECharts types are awkward in custom tooltip formatters: we cast the callback parameter.
- Offline fallback (NFR10) is ours to provide: tiles are hidden if they fail to load and markers stay on a schematic background.
