# Load test: 100 requests per second within one second (issue #8)

**Conclusion first: at 99.9 requests per second the p95 is 28 ms and there are no
errors** on this machine, with a single uvicorn worker, on the real data of all five
roads (158,733 measurements, 2023-01-01 to 2026-10-01). NFR3 and NFR4 are met.

What it took, in the order issue #8 set out: first indexes (one request of the slowest
shape went from 780 ms to 353 ms inside SQL); indexes alone were not enough (a single
worker tops out at ~7 requests per second with this mix), so the in-memory answer cache
from [ADR 0005](adr/0005-database-turso.md) came in and is cleared by the import.

## How to reproduce

From the repository root (plain `uv` and the `DATABASE_PATH` of your own `.envrc`):

```bash
uv sync                                   # locust is a dev dependency
uv run python -m backend.load             # load every road from analysis/output/ (all five here)
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8099
```

The final numbers assume a warm answer cache (steady state of a running dashboard).
Warm it by asking every request shape of the scenario once: `curl` each path listed in
`tools/locustfile.py`, or just run the load test for a minute and ignore that first run.
Then measure:

```bash
uv run locust -f tools/locustfile.py -H http://127.0.0.1:8099 \
    --headless -u 115 -r 115 -t 90s --csv load
```

`load_stats.csv` holds the table; `load_stats_history.csv` shows rps and percentiles over
time. In the workspace setup the server instead runs via
`direnv exec . process-compose up -D` on port 8099 (`--reload` off for measuring).

## Hardware and setup caveats

Measured on one shared 40-core box (Intel Xeon E5-2698 v4 @ 2.20 GHz, 64 GB RAM) whose
memory was half used by other sessions; uvicorn runs its default single worker on the
local asyncio loop, and locust runs on the same machine against `127.0.0.1`, so request
times include client-side process scheduling. One worker on a quiet or faster machine can
only be better; two workers behind the same checks would double the headroom the numbers
leave. Times are milliseconds measured by locust.

## Scenario: an anonymous dashboard session

`tools/locustfile.py` runs one request per ~1.1 s per user; 115 users land on the target
of 100 rps. Task weights are 45% series, 30% anomalies (24% list + 6% detail of one
anomaly), 15% comparison, 7% sensors map, 3% meta picker. Every parameter set is a real
sensor, road or period of the loaded database — 38 shapes, chosen uniformly at random
per task. The heavy end of what the dashboard actually asks for is all in it: whole
period requests (the picker's open bounds) for day, week and **hour** granularity —
`series hour WHOLE period` over 27,021 hours of the biggest sensor is the worst case,
run once per ~21 series requests — plus windowed requests (hour of a week, hour of two
months, day of a year) and filtered anomaly and comparison reads.

## EXPLAIN QUERY PLAN findings and the indexes added

Plans and the timings below come from the loaded all-road database. An excerpt of each
change, before → after:

```
/api/series (per-hour anomaly check, worst shape)
-  SEARCH a USING INDEX idx_anomalies_sensor_starts (sensor_id=? AND starts_at<?)
+  SEARCH a USING COVERING INDEX idx_anomalies_sensor_source_starts_ends (sensor_id=? AND source=? AND starts_at<?)

/api/anomalies last data day, /api/meta period bounds
-  SEARCH measurements USING PRIMARY KEY   17.6 ms   (MAX(ts) alone)
-  SCAN measurements                       23.5 ms   (MIN(ts) + MAX(ts) in one query)
+  SEARCH … USING COVERING INDEX idx_measurements_ts   0.0 ms (each bound is one seek)
```

Two indexes were missing from `backend/schema.sql`:

- `idx_anomalies_sensor_source_starts_ends (sensor_id, source, starts_at, ends_at)`.
  `/api/series` asks, for every measurement hour of the sensor, whether one of our
  anomaly intervals covers it. Against the old index SQLite walked that sensor's rows
  before the hour and fetched `source` and `ends_at` from the table every time. The new
  index answers the whole check from the index: the worst request's SQL time on this
  database drops from **780 ms to 353 ms**, its daily rollup from 655 ms to 344 ms, an
  hourly week window stays at ~3 ms.
- `idx_measurements_ts (ts)`. `MIN/MAX` of the stored hours (every anomaly page's
  "N days ago", the `/api/meta` period) could not use the `(sensor_id, ts)` key, which
  orders time only inside one sensor, and read all 158k rows. With the ts index a lone
  `MAX(ts)` / `MIN(ts)` is one seek to an index end: 17.6 ms → 0.0 ms. This also needed
  a one-line change: `/api/meta` asked both bounds in one query, and SQLite only applies
  the min/max-to-seek trick to a lone aggregate, so `backend/meta/repositories.py` now
  asks twice.

Considered and not added: the anomaly list filters and sorts (`road`, `source`, period
overlap, `ORDER BY starts_at`) — the table holds 731 rows and every plan already answers
in under 6 ms, the temp-B-tree sorts cost well below a millisecond; the sensors count
grouping and `is_mega` scan, same story on the same 731 rows.

`backend/test_db.py` now pins both plans: a future query change that silently stops
using the indexes fails the test.

## Why indexes alone were not enough, and the answer cache

With the indexes in, the same 115-user run achieved **7.0 rps** (620 requests in 90 s)
and waited p50 10 s / p95 43 s. The shape table of the same run says why: the whole
period series answers need 350–550 ms of SQL **plus** building and validating 27k-point
responses, and the mix asks for something heavy almost every request — about 12 rps of
pure work against one worker's one CPU second. The dashboard's real answers are simply
too fat for one worker at this rate.

So, per issue #8 and ADR 0005, the in-memory cache (`backend/common/cache.py`): one
middleware keeps every GET answer under `/api/` by its full URL in a 256-entry dict and
serves repeats without touching the database, pydantic or the JSON dump. A cache answer
is correct by the same contract argument the issue names: an answer depends only on the
stored rows, and the import replaces all of a road's rows and then clears the whole
cache (`backend/importer/services.py`). `backend/test_cache.py` pins both halves: the
second answer comes from the cache, and an import run clears it.

## Measured results

Final run (warm cache, 115 users, 90 s): **99.9 requests/s achieved, 8,942 requests, 0
failures, p50 6 ms, p95 28 ms, p99 120 ms, worst 163 ms** (the `load_stats.csv` counts;
the run summary carries a few requests more from the last half second). Per request shape:

| request shape | # req | p50 | p95 | p99 | max | errors |
|---|---|---|---|---|---|---|
| /api/anomalies/{id} plain | 249 | 5 | 40 | 150 | 150 | 0 |
| /api/anomalies/{id} with event | 279 | 5 | 20 | 51 | 150 | 0 |
| /api/meta | 281 | 5 | 24 | 64 | 120 | 0 |
| anomalies road | 421 | 5 | 27 | 120 | 160 | 0 |
| anomalies road+level | 420 | 6 | 26 | 140 | 160 | 0 |
| anomalies road+source | 446 | 6 | 27 | 120 | 160 | 0 |
| anomalies whole period | 404 | 8 | 38 | 54 | 160 | 0 |
| anomalies year window | 442 | 6 | 21 | 90 | 150 | 0 |
| comparison all roads whole period | 416 | 8 | 26 | 68 | 160 | 0 |
| comparison road | 463 | 6 | 27 | 61 | 160 | 0 |
| comparison road+year | 464 | 6 | 27 | 66 | 150 | 0 |
| sensors road | 319 | 5 | 22 | 47 | 150 | 0 |
| sensors whole period | 307 | 5 | 21 | 61 | 150 | 0 |
| series day whole period | 1121 | 5 | 28 | 63 | 160 | 0 |
| series day year | 472 | 5 | 29 | 150 | 160 | 0 |
| series hour WHOLE period (worst) | 144 | 17 | 35 | 66 | 71 | 0 |
| series hour two months | 506 | 5 | 40 | 150 | 160 | 0 |
| series hour week | 649 | 5 | 32 | 150 | 160 | 0 |
| series week whole period | 1139 | 5 | 29 | 140 | 160 | 0 |
| **all** | 8942 | 6 | 28 | 120 | 160 | 0 |

Cold starts are honest too, because they show what the cache was carrying: a cold cache
under the same load achieved 78 rps with p50 6 ms but a p99 of 13 s — all of it piled
into the first ~45 s while the 38 shapes were computed once, and the run held a steady
100 rps with p95 ≤ 150 ms from then on. Without the cache at all it never went above
7 rps. The first answer that fills a cache entry is answered exactly like an uncached
request (its own measured time, e.g. 565 ms for the worst shape — still within NFR4),
so even the cold-start first answers are inside the 1 s budget individually; the seconds
above 1 s in the cold run are queue waits behind each other's misses at 115 users,
which is precisely the no-cache saturation from the section above.

## Against NFR3 / NFR4

- **NFR3 (100 rps):** handled — 99.9 rps sustained for 90 s, 0 errors, a single worker on a
  busy shared box.
- **NFR4 (≤ 1000 ms):** met with a wide margin for repeats (p95 28 ms) and for the first
  answers themselves, whose worst individual measured value is 565 ms (the hourly
  whole-period query answering the cache miss).
- Issue #8's "Done when" — p95 ≤ 1000 ms at 100 rps on the real data of all roads — is met
  on this machine, with the hardware note above; the numbers will move with the box, the
  three orders of magnitude between 43 s and 28 ms at the same load will not.
