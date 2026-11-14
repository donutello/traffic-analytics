# Module `r22`: Р-22 «Каспий», подъезд к г. Саратов (Borisoglebsk section, km 444–484)

Road module for the traffic-analytics dashboard: it reads the road operator's hourly
traffic export for two sensors on the approach road to Saratov near Borisoglebsk
(Воронежская область), finds anomalies against their own history, and writes the five
contract files into `analysis/output/r22/`. Issues #34–#39; the planned trends and
forecast stretch (issue #40) builds directly on the same output — `series.csv` gives it
a hole-free three-year hourly series, the monthly rows of `anomalies.json` give it clean
year-over-year comparisons, and `events.json` gives it a small labelled calendar of known
outside events to keep anomalies honest against (see Status).

## About the input data

- One export `analysis/data/raw/r22/Svodniy_otchet_po_chasam_intensivnost+skorost_01_09_2023_01_09_2026.xlsx` (not in git, the repo is public): two sensor tables, one sheet, 41 184 logged hours, period 01.09.2023 – 01.09.2026.
- Labels are end-of-hour (`… 23:59:59`); the module re-stamps every row to the start of its hour.
- Columns as usual for this export family: total and per-direction volumes, volume by vehicle class (again per direction), mean speed and lane load per direction. All numbers arrive as clean integers; the reader still tolerates thousand separators and decimal commas.
- Sensor km 448+650 is nearly perfect: one hour missing (2025-04-19). Sensor km 478+742 logged 2023-09-01…2025-04-30 (14 557 of 14 592 hours), then one stray hour on 2025-09-22 and 299 hours back on 2026-08-20…2026-09-01. Between April 2025 and August 2026 it was effectively silent.
- 48 hours log a total volume but no reverse-direction count; the module marks them untrusted (they would fake a 100 % direct split) and repairs them like any hole.

## Sensors

| id | km mark | coordinates | how the position was found |
|---|---|---|---|
| `r22-km448-650` | 448.650 | 51.3736, 41.1104 | city geocentre of Борисоглебск; the road through the town at this km is the pre-bypass alignment of the approach road |
| `r22-km478-742` | 478.742 | 51.4100, 42.5620 | the officially named capital-repair zone км 465+000–484+000 in Борисоглебский район (sела Танцырей, Третьяки, Старовоскресеновка, Нововоскресеновка); point sits among the Воскресеновка hamlets |

Coordinates are approximate (up to a few km) and flagged so to the dashboard: they are geocentres of the officially named places at each sensor's kilometre, not surveyed poles. The official papers say «Р-22 „Каспий“ а/д М-4 „Дон“ — Тамбов — Волгоград — Астрахань (подъезд к г. Саратов)»: km 444–459.6 is the new «Обход Борисоглебска» under construction (Росавтодор, обход-контракт 21.08.2025), km 465–484 the capital repair to four lanes (ФКУ Упрдор «Тамань», старт 01.04.2024, ввод 11–13.11.2026) — both sources in `events.csv`. Local media number this road «Курск – Саратов» on the same scale (484 км = Третьяки, 455 км = за выездом из Борисоглебска): the scale lines up with our km marks. Despite the road's name, both sensors stand in Воронежская область, not near Saratov.

## Method

Quality first, then traffic. `quality.py` audits every raw hour's own sums, looks for
stuck values, all-zero telemetry, wrong one-sided splits and short days; everything
doubtful is excluded from detection and repaired. `fill_gaps` then rebuilds a
hole-free hourly grid between each sensor's first and last logged hour: holes up to 3
hours interpolate, longer ones take the median of the same weekday-kind and hour (and
month) from the sensor's own history. The full grid holds 52 656 hours; 11 547 (21.9 %)
are imputed — almost all of them km 478's silent season, honestly marked and never
counted as traffic. `detect.py` compares every real hour and day against sliding norms
of the same weekday (holiday kinds pooled separately), plus a year-over-year monthly
pass, since this export spans a full three years.

## Thresholds (settled in #34, with reasons)

| detector | test | why |
|---|---|---|
| hourly volume/speed amp | same-weekday sliding median (±84 d, ≥6 refs); flag needs robust z ≤ −3/≥ 3 **and** deviation ≥ max(35 %, 50 авт./ч); run ≥ 3 h | a percent-only rule shouts at quiet night hours; dilczech's AND quiets them |
| daily amp | ≥ max(25 %, 100 авт./сут) with z gate | sums hide accidents, hours alone hide slow fades |
| speed drop | per direction, ≥ 15 км/ч under norm and z ≤ −3, norms from hours where that direction actually counted cars | a percent of free-flow speed is meaningless at -20 °C; an empty hour's speed is junk |
| congestion | day hours 7–21 h with speed < 50 км/ч and lane load > 20 % on the same record | road median at km 448 is ~46 км/ч, so 50 alone would flag the norm; only the load-confirmed slow tail fires and it bottoms out at real standstill speeds of 11–31 km/h; their big deviations come from the 80 km/h free-flow reference |
| yoy monthly | same month of the other years only, ≥ 95 % valid days; MADT ±25 %, class mix ±8 п.п., speed ±15 км/ч flow-weighted | one odd month in one year must not look like a trend |
| direction imbalance | baseline-relative ≥ 25 п.п., run ≥ 4 h, ≥ 60 авт./ч | absolute share splits are noisy at night |
| flatline / zero telemetry | identical value ≥ 5 h above 10 авт./ч / ≥ 12 h all-zero | the 3-hour wobble noise below stays ignored |
| missing days | one finding per consecutive run of short/absent days | km 478's 477-day silence is one story, not 477 |
| correlation | overlapping volume+speed findings confirm each other: +0.5 score once | promotion is a nudge, capped at 6.5 |

## Severity

One contract table: `level_from_score` gives low < 2, medium < 3.5, high < 5, critical
≥ 5; nothing else sets levels. `is_mega` is true only for our own traffic findings with
|deviation| ≥ 60 % — in this dataset that is dominated by congestion runs (119 mega of
220 findings): they are measured against the 80 km/h free-flow reference, and the slowest
of them really do crawl at 11–20 km/h with heavy lanes, so we keep them rather than
tune the ruler. Corporate rows carry no score and are never mega.

## What we took from other public analyzers

- dilczech/traffic_anomaly_analyzer (MIT): the norm idea (same weekday, holiday-aware, sliding window), modified-z with practical floors, the AND rule, regime windows over a frozen pre-window norm, correlation promotion, and the balance-audit philosophy.
- Lexandrine's traffic_anomaly_analyzer and sasha_k's flow-analysis (the prior work for this corridor family): direction-wise per-hour profile fills, the stuck-value and all-zero sensor failures, and the year-over-year monthly pass idea we gate so it can survive on one-year-per-cycle exports.
Nothing was imported between road modules; everything above is re-implemented here in simple language (issue #37 rule: each module owns its copy).

## Events (issue #35)

20 outside events with dates inside the data window — holidays, weather, accidents and
road works along km 444–484 — were researched online; every `source_url` was returned
and opened by the research tools during this session and is listed in the session ledger
along with the rejected candidates (dead news slugs, the wrong-МЧС region page, events
outside the window). Anomalies link to an event when they overlap its day ±1 and their
kind fits the category. Honest recall against the production run: the algorithm found
6 of 20 —

| found | missed | why it missed |
|---|---|---|
| all three New Year windows (drops + eve spikes), 02.11.2023 fog, 03–04.01.2024 frosts, the 03.04.2026 Borisoglebsk crash (morning queues at km 448) | 17.01.2024 and 08.12.2025 evening crashes at 484/455 km, 05.06.2026 crash at 441 km; both May 2024/2025 holiday sets; the 2025-26 frost wave; the July 2025 heat | a same-weekday-holiday norm deliberately does not call a holiday a drop; short evening collisions and weather that changes speed but not volume stay under both tests; 441 km is upstream of both sensors |
| | all six road-works milestones | the repair and bypass works sit 10–35 km from km 448, and km 478 — the sensor right over the works — was offline for the most of the repair; its 2026 return (299 h) is too short to build norms |

This is the module's honest blind spot and the strongest argument for issue #40: works
impact shows as speed drift that volume-first detectors miss.

## Corporate findings (issue #36 practice)

`corporate_findings.csv` is a made-up feed of the regional traffic-portal style: 21 rows
of pre-holiday warnings, storm drops and queue claims, transcribed around the real event
days. Like the portal it is loud about weather and holidays (and reports the
16.01.2026 frost the algorithm slept through), vague-to-wrong about daytime works
(one old traffic-light queue claimed at km 478 in December 2024) and completely blind to
the km 478 sensors having been dead since April 2025. It scores through the same
`level_from_score` band and never claims mega.

## Checks

From `traffic-analytics/`: `uv run ruff check analysis/r22`,
`uv run ruff format --check analysis/r22`, `uv run pytest analysis/r22`
(22 tests on made-up frames: parser quirks, holiday kinds, sum audits, half-split hours,
gap fills, every detector shape, promotion once-and-capped, the yoy gate, linking, states,
corporate numbering), and `uv run python -m contract.validate analysis/output/r22`.

## Run

`uv run python -m analysis.r22` reads `analysis/data/raw/r22/`, writes
`sensors.json`, `events.json`, `series.csv`, `anomalies.json`, `corporate.json`  → the
contract's five files into `analysis/output/r22/`. Then the dashboard loads them with
`python -m backend.load r22`.

## Status (production run, this session's export)

52 656 hourly rows (both sensors, full span), 220 own findings: 119 congestion, 61
volume_drop, 18 missing_days runs, 8 speed_drop, 8 level_of_service_shift, 6
volume_spike — plus 21 corporate rows; 119 mega, levels {31 critical, 152 high, 37
medium}. Degraded inputs noted while running: km 478 silent 2025-05-01…2026-08-19
(profile-filled, monthly completeness findings on its months), one missing hour at
km 448 and half-split hours excluded from share tests. The five files pass
`contract.validate` and load into the backend twice without duplicating rows.
