# Module `a134`: A-134, approach to Voronezh

Owner: @Lexandrine

Reads the customer's real hourly report from `analysis/data/raw/a134/` (not in git — the repo is public and the customer's data stays private) and writes the result to `analysis/output/a134/` following the [data contract](../../docs/contract.md). The committed output is built from that real report; a fresh clone shows the real road's anomalies.

```sh
uv run python -m analysis.a134                       # run the module (needs the raw report)
uv run python -m contract.validate analysis/output/a134
uv run pytest analysis/a134/test_a134.py
uv run python tools/gen_raw.py                       # demo/CI stand-in only, see below
```

## About the input data

`analysis/data/raw/a134/` holds the customer's `Сводный отчёт по часам интенсивность+скорость 01.09.2023–30.09.2026`: one vertical sheet, one sensor section («км 8+100 а/д А-134, подъезд к г. Воронеж»), hourly totals per vehicle class plus per-direction speed and lane load. The module parses 26 720 real hours onto the 27 021-hour grid of the period.

Two things about the file itself shaped the parser:

- **Clock change inside the export.** Every 2023 hour is labelled 3 h in front of the clock the 2024–2026 part follows (each 2023 month-hour profile correlates +0.99 with the later one shifted by +3 h): the recorders were re-timed at the 2023/2024 rollover. `parse.py` adds those 3 hours to the early labels and drops the three re-reported hours of 27.12.2023 that the corrected recorder wrote itself.
- **Real gaps and dead channels.** Hours are missing in blocks (10 h on 2023-09-20, 2 h on 2023-12-02, a 7 h hole on 2025-02-06, every 11:00–19:00 through 2025-10-27…11-07, most middays through 2025-12-17…2026-01-13); the direct channel read empty for a full day on 2024-07-16/17; the reverse channel read zero through 2024-11-25…27 and starved to ~1 % through 2026-08-01…03; single hours elsewhere show zero speed while cars pass. These are what `quality.py` was written to survive.

The generator `tools/gen_raw.py` still exists (fixed seed) for demo runs and CI where the private report is absent, but the committed output is not its data anymore — rerunning the pipeline over generated files only overwrites the output with synthetic numbers.

## Method

The starting point was the three detectors ported from the earlier standalone analyzer ([Lexandrine/traffic_anomaly_analyzer](https://github.com/Lexandrine/traffic_anomaly_analyzer)); charts and the Excel report are not ported — the dashboard reads the contract files. Machine-readable codes are English; only dashboard-visible texts (sensor names, event titles, anomaly descriptions) are Russian, as the contract asks.

The pipeline (`pipeline.py`) runs in this order:

1. **Parse** (`parse.py`): every recognizable hour of every `.xlsx` becomes one row with contract column names, Moscow time, whole hours (including the +3 h fix above). Duplicated hours keep the first file. Per-direction splits by vehicle class are dropped; the contract keeps class totals and per-direction speed and load.
2. **Technical failures** (`quality.py`, issue #24) run on the raw table: flatline (stuck sensor), zero speed while cars pass, days with fewer than 24 hours, and a direction of the tube dead (one side starved while the other is busy). The hours they name are recorded as *untrusted*.
3. **Gap fill** (`quality.py`): the hour grid is completed per sensor from the first to the last hour; untrusted hours are dropped first. Holes up to 3 hours are interpolated between the neighbours, longer holes take the median of the same hour on the same kind of day (same calendar month first, then any month, then any day type). Filled hours get `imputation_method` and state `imputed` in `series.csv`.
4. **Traffic detectors** (`detect.py`) run on the filled table but **never on imputed hours** — a technical hole may not be counted twice, once as sensor work and once as traffic. The day-shape detector additionally needs days with no imputed hour at all. A day- or month-wide completeness window may still overlap a genuine anomaly in the hours that survived around it (as December 2025 does): the detectors only fired on real hours, so no hour is ever told twice.
5. **Monthly detectors** compare a calendar month with the same month of the other years; after a completeness complaint the month's traffic checks are skipped (a month missing its middays is compared no further), and a month (or a peer) under 95 % real hours takes no part in any year-over-year comparison.
6. **Cross-channel confirmation**: volume and speed findings of one sensor whose intervals overlap confirm each other - each side of a pair gets +0.5 score once (cap 6.5, level recomputed through the one contract table) and a sentence in the description saying so.
7. **Finalize**: ids `a134-<type>-YYYYMMDD-NN`, `is_mega` for traffic anomalies with |deviation| ≥ 60 %.
8. **Event linking** attaches `event_id` to anomalies that overlap a reviewed event's day or the day before/after it (news dates round; an overnight accident clears the next morning) and whose type suits the event category (below).
9. **Corporate findings** (`corporate.py`) are transcribed separately and written into the same `anomalies.json`.

## Norms

Every hour compares against the median of the **same hour of the same kind of day (weekday / weekend / official holiday, `holidays.py`) in the same calendar month, pooled over all years of the export**. Pooling across years is deliberate: a stormy December must stay a minority inside its own norm instead of dragging that norm down — with per-year-month norms the December 2023 storm days made themselves normal (found while settling #25). A consequence worth naming: a holiday that looks the same in every year (1 May 2024, 1 May 2025) is absorbed by its own pooled holiday norm, so the module cannot flag it as an anomaly. The holiday calendar covers 2023–2026 (Government Decrees № 1505, № 1314, № 1335 and № 1466, linked in `holidays.py`).

The dispersion measure is a **floored robust scale**: `sigma = max(1.4826·MAD, 10 % of the norm, floor)`, with floors of 20 авт./ч (hourly volume), 100 авт./сутки (daily volume), 3 км/ч (speed) and 2 % (load), and `z = (x − median) / sigma`. The z thresholds of #25 keep their meaning: 1.4826·MAD is the same scale the old modified z-score (`0.6745·(x − median)/MAD`) used. What the floors change is the collapse: a night hour that repeats the same count hour after hour has a MAD of nothing, and the old fallback turned it into a hair-width sigma that made any small absolute wobble a 20-sigma storm. A norm of 30 авт./ч now has a sigma of at least 20, and a jump of 50 cars there is z = 2.5, not z = 34. Groups with fewer than four days are skipped.

## Thresholds (settled in #24/#25, re-settled on the real export)

| Detector | Finds | Rule | Why |
| --- | --- | --- | --- |
| `integrity` (day) | `missing_hours` | a day with fewer than 24 hours | a complete export day is 24 hours; the real report's gap blocks land here |
| `sensor` | `flatline` | identical volume > 10 авт./ч for 5 hours in a row | real flow never repeats an exact count 5 hours running |
| `sensor` | `zero_speed` | speed ≤ 1 км/ч while 5+ cars pass, ≥ 2 hours in a row | the real export's speed channel drops single hours all over — those are repaired quietly by imputation; only a run of 2+ is a broken channel worth reporting |
| `sensor` | `zero_telemetry` | all seven channels (both volumes, both directions' speed and load, total) exactly 0 for ≥ 12 consecutive hours; the hours are untrusted and imputed | dilczech's zero-packet suspicion: a road can go quiet in a storm, but it does not log a perfectly round zero on every counter and both directions for half a day — that is the reporter sending emptiness; a dead reporter must never be read as an empty road. The real report has no such hour yet (verified), so this rule currently fires 0 times |
| `direction` | `direction_imbalance` | a side reads ≤ 5 % of the hour (or empty) while the other reads > 200 авт./ч, for runs of ≥ 2 hours | the hour then counts one loop instead of two; the real export deads one direction for whole days, so this is per-run, not per-day — hours another failure already explains get no second story |
| `amplitude` | `volume_drop`, `volume_spike` | hours vs the same-hour norm: |z| ≥ 3 against the floored scale **and** |actual − norm| ≥ max(35 % of the norm, 50 авт./ч) together, ≥ 4 hours in a row → one anomaly with the exact interval; runs are told separately on `volume`, `volume_direct` and `volume_reverse` | dilczech's practical-magnitude AND, replacing the flat ±25 % rule a floored z alone doesn't need: a deviant hour must be statistically far **and** large in cars, so night wobbles stay quiet; per-direction runs see accidents the total hides — the December 2025 M-4 pileup arrives as −51 % on the Voronezh-bound loop while the total stayed under every settled bar |
| `amplitude` | `speed_drop` | per direction: the norm is built only from hours where that direction counted cars, and an hour flags when its speed is ≥ 15 км/ч under the norm **and** z ≤ −3 **and** this hour's direction volume > 0; ≥ 4 such hours in a row → one anomaly | dilczech measures a slowed road in км/ч, not % of a norm that is nearly meaningless at night; an hour whose loop counted nothing logs no real speed; run ≥ 4 over ≥ 2 chosen on the real export: 2- and 3-hour runs made 60 of 80 speed findings there and not one of them named a researched event the longer runs don't already name, while 4 hours matches the settled volume run rule |
| `amplitude` | daily drops/spikes | day sum vs the month/kind median on the floored scale: z ≤ −3 **and** |actual − norm| ≥ max(25 % of the norm, 100 авт./сутки) (mirror for a spike) | the old ±50 %-alone trigger is gone: it was a flat percent with no scale behind it; the floors are now what keeps a calm month's tight MAD honest, and the absolute bar kills big-% deviations of a few cars |
| `regime` | `volume_drop`, `volume_spike` | ≥ 7 consecutive **complete** days, every day under 0.75 or every day over 1.25 of its FROZEN norm — the median of the same-kind complete days strictly before the window, within 168 days and ≥ 6 of them; one report per window (overlapping windows are skipped); score 3.5 + 0.1 per % of mean deviation beyond 25, cap 6.5 | a window whose own days feed the norm absorbs itself, so a sustained new level is never told — the frozen historical norm of dilczech's regime check is what sees it; on the real export this fires 0 times, honestly: the closest 7-day window (30 Jan 2024) stays at ratios 0.80–0.88, inside the band |
| `speed_load` | `congestion` | daytime (7–21 h) speed < 50 км/ч while lane load > 20 % **in the same hour's record**, ≥ 2 hours | free flow here is 70–90 км/ч; below 50 with confirmed occupancy the queue is real; single slow hours are measurement noise; the pairing is per-record (verified for this port), so a slow hour can never be confirmed by another hour's load |
| `profile` | `profile_shift` | full days without imputed hours over 1000 авт./day whose hourly shape correlates with the norm below r = 0.70 | norms are flat for quiet days and thin days correlate badly by noise alone |
| `integrity` (month) | `missing_hours` | month completeness under 75 % of hours real | monthly comparisons below that are not trustworthy; the month's other checks are skipped then |
| `yoy` | `volume_drop`, `volume_spike` | monthly average daily volume off ±25 % from the same calendar month's other years, **peers from the other years only**, and only months ≥ 95 % real hours — its own or a peer's — take part | ±25 % MADT is where road-ops studies treat a month as changed, not noise; the validity gate (dilczech's) keeps a blacked-out month from comparing itself and from bending other months' norms |
| `mix` | `vehicle_mix_shift` | share of large trucks + road trains moves ±8 п.п., same 95 % gate and peer-only rule | class shares are steadier than volume; 8 п.п. did not fire on seasonal truck waves in testing |
| `yoy` (speed) | `speed_drop` | the month's **flow-weighted** mean speed (each hour weighted by its direction's cars) ≥ 15 км/ч under its peers' norm | free-flow on this approach only shifts with capacity or weather regimes; a plain mean lets an empty night hour outvote a full evening one (dilczech weights by flow too) |
| `load` | `level_of_service_shift` | monthly median lane occupancy drifts ±20 % from its calendar norm, same gate | an ODM-218.2.020-style load level shift means the congestion regime changed without the volume changing; December 2025 — the export's darkest month — was finding #1 here under the old ungated rule, which is exactly the comparison the gate is for |

## Severity

`level` is never chosen by hand: the single `detect.level_from_score()` applies the contract v1 table (≥ 5 critical, ≥ 3.5 high, ≥ 2 medium, else low) — including after the +0.5 of a cross-channel confirmation, which never passes 6.5 and is given to a finding at most once (the marker sentence in its description shows a used bonus; findings already at or above the cap are left alone). Scores: statistical detectors report `min(|z|, 9.9)` on the floored scale; rule detectors carry fixed weights on the same scale — integrity 3.0, flatline 4.0, zero_speed 2.5, zero_telemetry 3.5, direction 2.8, congestion 4.5, profile 2.5, monthly integrity 3.0, yoy MADT 3.5 + 0.1 per point beyond 25 (cap 6.5), mix 2.0 + 0.1 per point beyond 8 (cap 3.5), yoy speed 2.5, load shift 2.0, regime 3.5 + 0.1 per % beyond 25 (cap 6.5). `is_mega` flags traffic anomalies with |deviation| ≥ 60 % (FR3) — never technical ones.

## What we took from dilczech/traffic_anomaly_analyzer and sasha_k

Two public analyses of the very same customer export fed this round of detectors, and one honest word about where each idea comes from is in order.

[dilczech/traffic_anomaly_analyzer](https://github.com/dilczech/traffic_anomaly_analyzer) (numpy/pandas only, same 29-column report, no sklearn/statsmodels anywhere — which is why the ports cost no new dependencies) gave, one line each:

- sigma = max(1.4826·MAD, 10 % of norm, floors 20/100/3/2) — its `baseline.py::robust_stats` and per-metric floors, verbatim;
- the practical-magnitude AND-tests (hourly |Δ| ≥ max(35 %, 50 авт./ч), daily max(25 %, 100)) beside the z — its `detectors.py` volume checks;
- per-direction everything: speed norms built only from hours where that direction counted cars, flagged hours needing moving cars, direction-aware speed gaps in км/ч — its `detectors.py` speed checks (we added the per-direction **volume** runs on our own detector, its direction volume tests exist too);
- the regime-change detector: 7-day windows, the 0.75/1.25 all-or-nothing bar, the 168-day frozen lookback with ≥ 6 same-group days, one report per window — its `detect_regime_changes`; we score it on our contract scale (3.5 + 0.1/% past 25, cap 6.5) instead of its severity words, and group days by our weekday/weekend/holiday `day_kind` rather than its weekday-number groups;
- the volume×speed overlap promotion (+ its once-only, cap, and leave-the-loud-ones-alone behaviour) — its `priorities.py::promote_correlated_events`, turned from its review-priority labels into +0.5 score and a contract-table relevel;
- the ≥ 12-hour all-zero zero-packet as distrust-worthy telemetry — its `quality.py` and `zero_packet_hours`;
- the flow-weighted monthly speed and the ≥ 95 % validity gate on year-over-year comparisons with peers only (the compared year excluded from its own norm) — its `monthly_summary` and `detect_monthly_anomalies`.

[sasha_k's flow-analysis](https://github.com/Lexandrine/flow-analysis) (the author's handle; the repo lives under @Lexandrine's account as [Lexandrine/flow-analysis](https://github.com/Lexandrine/flow-analysis)) is the ancestor of this module's original three detectors (the July-2025 port described in issue #22), so its core ideas were already here. From its net-new list we deliberately ported **nothing** this time: its day-level car-share check overlaps our `mix` detector's question, and its hourly direction-imbalance runs would need a direction norm architecture of their own — kept off to avoid scope creep (a134 never carried a settled 15–85 % day-level band, so there was nothing to keep that variant alongside), and we still neither copy its `min(speed)/max(load)` congestion pairing (our congestion is per-record, which is the correct pairing it lacks) nor its `fillna(0)` parsing (missing is missing here, not zero).

## Events (issue #23)

`events.csv` is the manual-review table: 20 outside events for 2023–2025 found by browsing Voronezh news (accidents, roadworks, weather days, the traffic-light outage) and the official production calendar. Every row carries a `source_url` — a page actually opened during the research and mentioning the event (two tempting accidents were dropped because the aggregator page could only be dated to 2026). Titles and descriptions are Russian (dashboard text). 2026 has no researched events yet; the export now covers it, so that is an open follow-up.

Linking is per category and deliberately narrow: an anomaly links only if its interval overlaps the event **day ± 1 day** and its type suits the category — accident: `volume_drop`/`congestion`; roadworks and other: those plus spikes and `profile_shift`; weather: the drop types and `profile_shift`; holiday: volume and profile types; outage: only the technical findings. One anomaly links to one event. "Found" means exactly that: at least one linked finding.

On the real export, 4 of 20 events left a trace the module's documented rules can see (3 before the smarter-detector ports, which is honest growth, not retuning — see the note under the table):

| Event | Category | Found | Why / why not |
| --- | --- | --- | --- |
| 2023-01-01 New Year holidays | holiday | missed | the export starts 01.09.2023 — outside coverage |
| 2023-05-09 Victory Day holidays | holiday | missed | outside coverage |
| 2023-06-03 storm, Kamenny Most collapse | weather | missed | outside coverage |
| 2023-09-28 Ostuzhevskoye ring light outage | outage | missed | a city intersection queue 8 km downstream; km 8+100 ran +11 % that Saturday (the sensor's own gap week was 09-20) |
| 2023-10-13 two-level interchange opened | roadworks | missed | redistributes city flows; the approach day moved +5 % |
| 2023-10-26 bus into two lorries on M-4 | accident | missed | the crash 100 km upstream took ~17 % off arrivals that day — under the settled daily bar (−25 % plus z ≤ −3) |
| 2023-12-12 snowdrifts, 84 buses stayed in | weather | **found** | 9 anomalies link: volume drops of 44…56 % through 12–13 December, total and per direction, plus a km/h speed drop on the 13th |
| 2023-12-15 blizzard on M-4 «Don» | weather | **found** | 14 anomalies link: congestion −77 %, volume drops −36…−64 % over three days, and the first speed drops now measured in км/ч on both directions |
| 2024-02-08 cyclone Olga wet snow | weather | missed | the approach's day sums stayed inside the norms |
| 2024-02-12 worst ice in Voronezh | weather | missed | traffic stayed moving; what the ice actually broke was the speed channel (our findings there are sensor-zero runs) |
| 2024-04-19 Ostuzheva street closed to May | roadworks | missed | a city street closure; the approach day moved +2 % |
| 2024-05-01 first May weekend trips | holiday | missed | 1 May looked the same in 2024 and 2025, so the pooled holiday norm absorbed it — a norm-referenced detector cannot flag a normal holiday |
| 2024-06-02 nine-car pileup, Moskovsky Ave | accident | missed | inside the city; the approach day moved −5 % |
| 2025-01-01 New Year holidays | holiday | **found** | 4 anomalies link: a night spike (+76 % total, +87 % out of town) and an afternoon drop (−55 %) |
| 2025-02-25 serious BMW crash, Moskovsky Ave | accident | missed | inside the city; the day was ordinary |
| 2025-05-01 first May weekend 2025 | holiday | missed | same holiday-normal absorption |
| 2025-05-20 sewer collapse, street partly closed | other | missed | one city street; the approach was unchanged |
| 2025-08-03 downpour floods Voronezh streets | weather | missed | an evening downpour inside the city; the day moved −5 % |
| 2025-10-08 Voronezh bypass repair resumed (M-4 km 492–517) | roadworks | missed | slowdowns on the highway itself; the approach day was ordinary |
| 2025-12-15 bus pileup at km 571 of M-4 | accident | **found** | new since the ports: the Voronezh-bound loop reads −51 % on the evening of the 15th and −49 % on the morning of the 16th — the day totals stayed inside the settled bar, only the per-direction runs see it |

Missed is the honest outcome for events that happened in the city or far upstream: this sensor counts the approach to Voronezh, not Voronezh itself — the events it cannot show are exactly the ones its position cannot show. The December 2023 storm pair and New Year 2025 were already seen before these ports and stayed seen; the added December 2025 accident arrives honestly through the per-direction runs it needed, as a marginal pair (−51 % and −49 %, the totals never crossed any bar). Nothing was retuned to chase a number: the one tuned choice, the speed run length, was picked between 2 and 4 hours on the noise profile of the real export (60 of 80 two- and three-hour findings vs none of the found events needing them), and the event count came out 4 of 20 under both settings.

## Corporate findings (issue #26)

`corporate_findings.csv` is a hand-retyped extract of the customer's corporate monitoring for this road: 25 rows, all on the one real sensor, spanning the same period as the export, transcribed the way the real interface behaves — laggy, wider intervals than ours, about fifteen findings that match a real anomaly in our own output (the storms and winter waves both systems see) and ten that land on days our module calls normal: false alarms, including a red congestion alarm on the rainy evening of 2025-08-03 and a drop claim on the 2024 May holiday our norms absorb. The CSV can be extended as more of the interface gets screened.

`corporate.py` only converts them to contract items: `detector = corporate`, `score = null`, `is_mega = false`, `description = null`. The interface's own severity class maps onto the v1 table through fixed representative scores (yellow 1.5 → low, orange 2.8 → medium, red 4.2 → high), still via the one `level_from_score`. They are numbered `a134-corp-NNNN` and kept out of finalization, so the corporate stream can never be silently retuned into our scale.

## Sensors

The real export carries one section: «км 8+100 а/д А-134, подъезд к г. Воронеж» (id `a134-km8-100`, «Московский проспект» near хутор Ветряк) — coordinates in `KNOWN_SENSORS` from OSM landmarks of the М-4 «Дон» — Воронеж rebuilding. A second generated-only section (km 4+700) left the module when the real export arrived; if a future export adds sensors, add their coordinates to `KNOWN_SENSORS` — the module prints exactly what to add.

## Status

Issues #22–#27 are completed on this branch: parser and contract output (#22), event research (#23), failure handling and gap fill (#24), settled thresholds and severity (#25), corporate transcription (#26), committed output and CI (#27). The real export is wired in and the committed output is its result. A smarter-detectors round landed on top of it on the `analysis/a134-smarter-detects` branch — the ports from the two public analyzers (their own credit above), plus the correctness fixes (flow-weighted month speed, validity-gated year-over-year, per-record congestion confirmed, zero-telemetry rule): the committed output is that round's result, 4 of 20 researched events found, and two new rules (regime, zero telemetry) honestly firing 0 times on the real report so far. Open by nature: verifying the OSM-approximate coordinates with the customer, the 2026 round of event research, and re-tuning the thresholds if the customer disputes a call.
