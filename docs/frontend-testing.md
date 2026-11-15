# Frontend testing and browser matrix (issues #13 and #15)

What was actually checked, on Linux with the box's Google Chrome (current version), against the live dev stack
(FastAPI + Vite through `process-compose`). Honest scope first: the real browser matrix of NFR2 (last three
versions of Chrome and Yandex Browser on Windows) is still a manual step before the demo — see the bottom.

## Automated checks (CI runs all of them)

- `npm run lint` (oxlint), `npm run typecheck` (tsc), `npm run build` (vite) — unchanged gates.
- `npm run test` (vitest 5, three new files, 26 tests):
  - `src/urlState.test.ts` — the shareable view: serialize/parse round trip for every field, defaults dropped,
    hostile links (unknown enums, garbage dates, blanks, repeated keys) fall back to defaults.
  - `src/comparison.test.ts` — the comparison math: percent helper with all-zero and empty-whole cases,
    stacked-bar segment sizes and shares, Russian count agreement («1 пара / 2 пары / 5 пар»), table sorting
    (time/level/sensor, direction, stable ties, source array not mutated), timeline position clamping and axis ticks.
  - `src/render.test.tsx` (jsdom + @testing-library/react) — the loading/error/empty boxes render and expose the
    «Повторить» retry, the comparison bar segments are proportional to the API counts (their accessible label
    too), and the shared toolbar really writes `?road=`, `?source=` into the URL, plus the «все дороги» option
    of the comparison view.
- jsdom is selected per test file (`// @vitest-environment jsdom`), so `vite.config.ts` stayed untouched.
  Test-only devDeps: `vitest`, `jsdom`, `@testing-library/react` — no runtime-dependency change, Windows-safe.
- CI (`frontend` job) runs `npm test` between lint and build.

## Widths (NFR1: 1200–1920px)

Resized the real Chrome window to 1200 and 1920 and checked every tab (Обзор, Карта, Сравнение алгоритмов)
for sideways overflow and visual glitches, with screenshots saved
(`.data/screenshots/` in the workspace copy of the repo, not committed):

- `compare-all-1920.png` — comparison across all roads (bars, «в сумме», timelines, difference tables).
- `compare-a134-panel-1920.png` — one-road comparison with the side panel opened from a table row.
- `compare-panel-404-1920.png` — friendly panel state for an unknown `?anomaly=` id.
- `compare-all-1200.png` — the whole comparison page at the minimum width.

Fixed while checking: `.app` had `min-width: 1140px` without `box-sizing: border-box`, so its 2×32px padding
made the page 1204px wide and caused a sideways scrollbar at exactly 1200px (pre-existing, since issue #11).
After the fix a scripted check (`scrollWidth` vs `clientWidth` plus a per-element right-edge scan) shows no
element overflowing at 1200 or 1920 in any tab; difference tables and the JSON dump scroll inside their own
boxes instead of the page.

## States audit (issue #15)

- Chart / sensor list / map: loading spinner, empty («нет датчиков», «нет измерений»), error + «Повторить» —
  already in place from #11/#12, re-verified live.
- Panel: unknown `?anomaly=` id (404 from the API) now shows «Аномалия не найдена» with a hint how to get back,
  instead of the raw error.
- Backend down: whole-app error page with retry (unchanged) — additionally, failed requests are no longer kept
  in the client fetch cache, so a backend restart mid-session recovers instead of caching the failure forever.
- Comparison: loading spinner, error card, and a friendly empty card for filters with no findings; unknown road
  codes and period windows outside the data (checked with `?road=zzz` and 2022 window) show the empty hint, not
  a crash. Empty lists inside the tables («нет находок» lines) and zero-share bars are handled.
- Wrong URL parameters generally: `urlState.parseState` rejects unknown enums and malformed dates (now unit-tested),
  so shared links degrade to the default view.

## Still open (honest, before demo day)

- NFR2 matrix itself: last three Chrome and Yandex Browser versions **on Windows** — manual pass, planned as one
  session before the demo (the UI uses no exotic APIs; current Chrome on Linux renders it clean at both widths).
- The timeline on a road with 190+ one-sided findings gets crowded ticks; counts stay readable via tooltips and
  the tables. A density-sampled view is a possible later refinement, not scheduled.
- The fictional sample road (`_example`) is included in the «в сумме» card and the per-road cards because the
  server counts it; it is labeled as fictional in the UI.
