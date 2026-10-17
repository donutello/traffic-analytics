# 0002. Frontend: React, TypeScript and Vite

- Status: accepted
- Date: 2026-10-17
- Author: @donutello

## Context

The dashboard is one page with an interactive chart, a map, a side panel and a comparison section (FR1–FR4). It runs in recent Chrome and Yandex Browser on screens from 1200 to 1920px wide (NFR1, NFR2). The UI is in Russian.

## Decision

- The frontend is a single-page app in [React](https://react.dev/) with TypeScript, built with [Vite](https://vite.dev/). It lives in `frontend/` and was created from the official `react-ts` template.
- It talks to the backend only through the JSON API under `/api/...`. In development, Vite forwards `/api` to FastAPI (see `vite.config.ts`), so the browser sees one address.
- Styles are plain CSS. The colors for the three data states (normal, anomaly, filled-in gap) are CSS variables in `src/index.css`, shared by every chart and the map (FR2).
- Data is loaded with plain `fetch`. No router and no state library: there is only one page.
- The chart and map libraries are chosen in their own issues (suggestions: ECharts for charts, MapLibre GL or Leaflet with OpenStreetMap for the map) and get an ADR then.
- In production FastAPI serves the built files from `frontend/dist`, so there is one server, one address and one HTTPS certificate.

## Alternatives

- **Server-rendered pages (Jinja templates).** Simpler at first, but zooming charts and a linked map and panel need a lot of JavaScript anyway.
- **Next.js.** Server rendering and routing we don't need, plus a second server to deploy.
- **Tailwind CSS and a component library.** Faster to make things look nice, but more to set up and learn for a page with a few sections. We can add them later if plain CSS becomes painful.

## Consequences

- The frontend can be built and checked on its own: `npm run lint` and `npm run build`.
- Without the backend running, the page only shows that the server is unavailable. Until the API is ready, the frontend can use the example data from `analysis/output/_example/`.
- Every new library is a decision: we add one only when an issue needs it.
