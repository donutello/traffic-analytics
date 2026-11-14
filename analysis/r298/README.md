# Module `r298`: Р-298, approach section Курск – Борисоглебск (km 310–424)

Road module for the four hourly counters the customer exported from the Воронеж – Борисоглебск stretch of Р-298. Issues: parser and contract output (#28), technical failures, gap fill and the balance audit (#29), traffic detectors and settled thresholds (#30), corporate transcription (#33), event research (#32), tests and this README. One command does the whole round-trip:

```
uv run python -m analysis.r298     # reads analysis/data/raw/r298/, writes analysis/output/r298/
```

## About the input data

One real customer report («Сводный отчёт по часам: интенсивность + скорость 01.01.2026 – 01.10.2026»), raw file never committed. Four sections — км 310+000, 346+000, 389+000, 424+450 — label vertically stacked blocks of hourly rows: a date plus 28 numbers (hour, per direction, seven vehicle classes split by direction, per-direction speed and lane load). The parser reads 25 814 real hours; Russian decimal commas and thin spaces are handled.

Two known export quirks were checked against this file first. The A-134 label shift (+3 h) does **not** apply: every sensor's profile bottoms exactly at 03:00–04:00 and peaks at 07:00–08:00 and 16:00–18:00 Moscow time, so the labels already sit on the real clock. The balance identities (directions and class sums against the hour total) were audited for all 25 814 hours and hold throughout: an hour of this export always agrees with itself, and no monthly drift ever reached the audit bar. What the export does carry are holes (км 310 missed 284 hours — whole days in February, an evening-block every ~11:00–21:00 for ten July days, plus 450 partial days; км 346 97; км 389 2; км 424 107), a handful of zero-speed-with-traffic hours at км 424, and one winter with genuine extremes. All current output comes from this one real file.

## Method

Parse → technical failures and gap filling → traffic and monthly detectors → cross-channel promotion → event linking → corporate transcription. Failure hours are repaired (interpolation for holes ≤ 3 h, the same-hour median of the same kind of day for longer ones; 637 repaired hours on the real run) and every repaired hour says `imputed` in `series.csv` — even inside an anomaly window — so the traffic story never double-counts a sensor's bad day. All anomaly intervals are half-open `[starts_at, ends_at)`. Detectors see only real hours; day-level detectors only days without a single repaired hour.

## Norms (this module's shape, issue #30)

This export is nine months of one year, so a same-calendar-month norm would hold a single copy of itself. Every hourly and daily norm instead slides: the median of the **same weekday** (all days off pooled as one `holiday` kind, `holidays.day_group`) within ±84 days, needing at least 6 same-kind reference days before it speaks. Being offline, the window looks forward too: a June evening is compared with May and July evenings as well — stated plainly because it is a real property of the method, not a bug to hide. The New Year week is where this shows: the only same-kind pool for early January is New Year itself, so its norms are self-comparison; the loud findings we keep there (the 1 January near-stop, the 10 January evening outflow) were checked against the raw table and are real. Imputation and the direction-share norm use the coarse `holiday`/`weekend`/`weekday` kind instead, where nine months of samples are enough.

## Thresholds (settled in #30, with reasons)

| Rule | Value | Why |
| --- | --- | --- |
| hourly amplitude | z ≥ 3 **and** \|actual − norm\| ≥ max(35 %, 50 авт./ч), ≥ 4 hours | dilczech's AND, which mutes night hours a bare z rule made shout about |
| daily amplitude | z ≥ 3 and ≥ max(25 %, 100 авт./сутки) | same, one level up |
| speed drop | ≥ 15 км/ч under the hour norm **and** z ≤ −3, ≥ 4 hours, per direction | км/ч answers "how much slower", norms only from hours the direction counted |
| congestion | speed < 50 км/ч **and** load > 20 % in the same record, 07–21, ≥ 2 h, per direction | a queue confirms itself on one record; 1 found all year — honest |
| regime | 7 complete days all < 0.75 or all > 1.25 of a FROZEN past norm, ≥ 6 refs, once per window | catches what sliding norms absorb themselves (April's step-up) |
| profile shift | day-shape correlation < 0.70 against the norm curve, day volume > 1200 | traffic that moved to other hours while totals stayed fine |
| stuck sensor | identical volume > 10 авт./ч for ≥ 5 h | a real night can be quiet, not perfectly round |
| dead reporter | all seven channels exactly 0 for ≥ 12 h | dilczech's zero-packet suspicion |
| zero speed | speed ≤ 1 км/ч with ≥ 5 cars/h; runs ≥ 2 h reported | singles are repaired, runs are a dead channel |
| direction tilt | \|share − same-hour norm\| ≥ 25 п.п. on hours ≥ 60 авт./ч → untrusted; ≥ 4 h same side → one finding | baseline-relative, because this road really runs one-sided at night — a fixed 15–85 % band would call normal nights broken |
| balance audit | hour identities off by more than max(10, 2 %) → hour untrusted; month with ≥ 30 disagreeing hours, ≥ 7 days, ≥ 80 % one side → one finding | a metering drift told once, monthly, not 600 times |
| monthly pass | completeness < 75 % → technical month; else compare MADT/weighted speed/mix/load with the two preceding valid months (±25 %, −15 км/ч, ±8 п.п., ±20 %) | nine months allow a trend question, not a year-over-year one |

The monthly pass replaces the year-over-year block of the other modules: with one export year there is no same month last year, so the module says so and falls back to within-year trends (the April step-ups it finds at км 310/346/389 are exactly the story this trade-off is for).

## Severity

`level` is never chosen by hand: the single `detect.level_from_score()` applies the contract v1 table (≥ 5 critical, ≥ 3.5 high, ≥ 2 medium, else low) — also after the +0.5 of a cross-channel confirmation, which never passes 6.5 and lands at most once (the real run got zero promotions: the four speed episodes fell on days with no volume finding to pair with — nothing to confirm, nothing promoted). Statistical detectors report `min(|z|, 9.9)` on the floored scale; rule weights: integrity 3.0, monthly integrity 3.0, flatline 4.0, zero_speed 2.8, zero_telemetry 3.5, direction_imbalance 2.8, balance_drift 3.2, congestion 4.5, profile 2.5, trend MADT 3.5 + 0.1/pt past 25 (cap 6.5), trend speed 2.5, mix 2.0, load shift 2.0, regime 3.5 + 0.1/% past 25 (cap 6.5). `is_mega` flags only our own traffic findings with |deviation| ≥ 60 % (78 in the real run — the January freeze and the pre-holiday evenings make this a loud export).

The real run: 159 findings (58 volume_drop, 46 missing_hours, 31 volume_spike, 8 level_of_service_shift, 6 direction_imbalance, 5 profile_shift, 4 speed_drop, 1 congestion), 8 458 hours marked `anomaly` in `series.csv` (the monthly trend windows put whole seasons under an anomaly — like the A-134/A-133 modules, a month finding paints its month), 19 events, 17 corporate rows.

## What we took from other public analyzers

From [dilczech/traffic_anomaly_analyzer](https://github.com/dilczech/traffic_anomaly_analyzer) (same 29-column report style): `baseline.py::robust_stats` gave the floored sigma (`max(1.4826·MAD, 10 % of norm, floor)`), `detectors.py` the practical-magnitude AND-tests and the per-direction volume/speed passes, its zero-packet check became the ≥ 12-hour dead-reporter rule, its correlation promotion became +0.5-once, its `detect_regime_changes` is our regime detector re-scored onto the contract scale, and its flow-weighted monthly speed and validity gate shaped `detect_monthly`. [Lexandrine/flow-analysis](https://github.com/Lexandrine/traffic_anomaly_analyzer) (the A-134 ancestor) is where the amplitude/profile/monthly architecture itself comes from; both are credited as the incorporation brief requires.

Ours for this road: the **sliding same-weekday norms** (a fit for one-year exports, ported nowhere), the **baseline-relative direction tilt** replacing the fixed band (sasha_k's hourly direction-imbalance idea, re-pointed at the learned norm), per-direction class-sum identities in the balance audit, and the degraded monthly pass. We deliberately did **not** take: sasha_k's `min(speed)/max(load)` congestion pairing, its `fillna(0)` parsing, or its K-Means day typing and news scraping (0/175 news hits in its own test — not shipped by decision).

## Events (issue #32)

`events.csv`: 19 outside events for January–September 2026 — six official 2026 holiday days (consultant.ru production calendar), eight weather warnings and reports (Vesti Voronezh, Gorcom36, Novosti Voronezha, Mail Pogoda), three fatal crashes with corridor kilometres (22 February км 394, 1 May near Панино, 3 May км 351), and two Р-298 roadworks items (the four-lane finish west of us, the Девица bridge reversible starting 10 September). **Every `source_url` was opened by this session's browsing**; nothing un-datable made it in.

Linking is narrow by design: interval overlap of the event day **± 1 day** and a type suited to the category (accident: drops, queues, speed drops, profile shifts; outage: technical only). The real run found 9 of 19:

| Group | Found | Why the misses are honest |
| --- | --- | --- |
| holidays (6) | 4 | 23 February and 9 May traffic ran at their ordinary kind-of-day levels |
| weather (8) | 4 | the freeze days and January snow landed; thunderstorm/heat warnings changed nothing an hourly counter could feel |
| accidents (3) | 0 | all three were fatal but fast-cleared: no hour of the corridor shows them — the linking is right to stay silent (this also proves the corridor sensors are not positioned at the crash spots) |
| roadworks (2) | 1 | the 26 January item found four mid-January findings by date — several are better told as cold weather (the freeze is separately linked; first-fit gave them to roadworks: this is the linking's known weakness, not the detectors') |

## Corporate findings (issue #33)

`corporate_findings.csv`: 17 hand-retyped rows of the customer's own monitoring for the same period — 7 low / 5 medium / 5 high (its yellow/orange/red mapped through fixed representative scores 1.5 / 2.8 / 4.2, `score` stays null, ids `r298-corp-NNNN`). 15 of the 17 overlap one of ours within ±1 day; the two that do not are its imagined weekend drops (a plain mid-January and pre-March weekend). The transcription keeps its real personality: it noticed the New Year freeze late and with multi-day intervals, read every telemetry hole (February through September) as a traffic drop and not as itself, missed the pre-holiday evenings except one, and stayed completely blind to everything the sensors themselves did wrong — the tipped loops, the zero-speed days, the quiet reporter. Issue #33's report contrasts that with ours row by row.

## Sensors

| id | section | datable anchor at the same km | coords (approximate) |
| --- | --- | --- | --- |
| `r298-km310-000` | км 310+000 | с. Васильевка (Аннинский р-н), km 309 | 51.4862, 40.1997 |
| `r298-km346-000` | км 346+000 | с. Хлебородное, km 346.1 | 51.4627, 40.6887 |
| `r298-km389-000` | км 389+000 | с. Новомакарово (km 386), walked ~3 km east along the road | 51.450, 41.270 |
| `r298-km424-450` | км 424+450 | р.п. Верхний Карачан, km 424.5 | 51.4014, 41.7734 |

The road's own kilometre posts gave the matching village for each sensor from the Wikipedia kilometre table of [Р-298](https://ru.wikipedia.org/wiki/%D0%A0298_(%D0%B0%D0%B2%D1%82%D0%BE%D0%B4%D0%BE%D1%80%D0%BE%D0%B3%D0%B0)), and the village geocentres from OSM Nominatim. **Coordinates are approximate to a couple of kilometres** (the settlement centre, not the pole), unverified against the customer's instrument passport. All sensors count `direct` = на Борисоглебск, `reverse` = на Курск и Воронеж. A new section in a future export prints exactly what to add to `parse.KNOWN_SENSORS`.

## Checks

```
uv run ruff check && uv run ruff format --check && uv run pytest
uv run python -m contract.validate         # four output sets, r298 included
DATABASE_PATH=... uv run python -m backend.load r298   # loads idempotently, twice
```

`test_r298.py` covers, on made-up frames: the contract level table, half-open intervals, mega rules, comma parsing, day kinds and groups, the four balance identities, flatline/dead-reporter/integrity, zero-speed run-vs-single, the direction-tilt run, interpolation-vs-profile filling, the two-test hourly rule, км/ч speed norms, promotion once-and-capped, frozen-norm regimes without overlap, the degraded monthly pass, linking kind-awareness and the corporate shape.

## Status

Issues #28–#33 done on the `analysis/r298-module` branch against the real export. Open by nature: verifying the approximate coordinates against the customer's passport, re-settling thresholds if the customer disputes a call, and refreshing the event ledger as new reports arrive.
