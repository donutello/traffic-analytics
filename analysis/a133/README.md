# Module `a133`: А-133, approach to Lipetsk

Owner: @mmsh55

Reads the customer's hourly exports from `analysis/data/raw/a133/` (not in git — the repo is public and the customer's data stays private) and writes the result to `analysis/output/a133/` following the [data contract](../../docs/contract.md). **The customer's real export has not arrived yet, so this module currently runs on a reproducible demo export** written by `tools/gen_raw.py a133`, and the committed output is built from that demo data (see About the input data).

```sh
uv run python tools/gen_raw.py a133                  # write the demo export first
uv run python -m analysis.a133                       # run the module
uv run python -m contract.validate analysis/output/a133
uv run pytest analysis/a133/test_a133.py
```

## About the input data

An export is the same vertical report the A-134 module reads: rows with a section label («км 12+000 а/д А-133», «км 40+000 а/д А-133») alternate with hourly rows — a date, sometimes a comma-decimal number, service lines («Итого», «Среднее») interleaved — and 28 numeric columns: the hour total, the two direction counts, seven vehicle classes each again split by direction, then per-direction speed and lane load. The parser (`parse.py`, issue #16) turns every readable hour of every file into one contract-named row in Moscow time, keeps the per-direction class splits for the [balance audit](#method) below, and drops duplicated hours (first file wins). Unlike the A-134 parser, this one has no clock-shift question to solve: the demo export is consistent.

Until the real report arrives, the bytes in `analysis/data/raw/a133/` come from `uv run python tools/gen_raw.py a133` (fixed seed 20251115): two sensors, 2023–2025, and into the traffic it embeds on their real researched dates (analysis/a133/events.csv) the accidents, roadworks, weather, holiday and UAV effects, plus sensor incidents that are not events: whole lost days (km 12 2023-08-09, km 40 2024-03-03/04), a six-hour morning hole (km 12 2024-09-28), an incomplete day (km 40 2025-10-09, and the 2025-11-17 outage), a six-day stuck run at 311 авт./ч (2024-08-14/15), zero-speed hours while cars pass (2025-03-21), a twelve-hour dead reporter (km 12 2025-02-04), and two quiet metering-drift months for the balance audit (class drift on km 40, June 2025; direction drift on km 12, November 2024). Rerunning the command and the module reproduces the committed output exactly. The tests need none of this: they run on small constructed series, so CI works without any raw file.

## Method

Three public analyses fed this module — see [the credits section](#what-we-took-from-other-analyzers) — and everything below is settled in issues #18/#19 and re-checked against the numbers the module actually prints. Machine-readable codes are English; only dashboard-visible texts (sensor names, event titles, anomaly descriptions) are Russian, as the contract asks.

The pipeline (`pipeline.py`) runs in this order:

1. **Parse** (`parse.py`) as above; the raw table keeps the class × direction splits the contract drops again at the end.
2. **Technical failures and balance** (`quality.py`, issue #18) run on the raw table: stuck hours, dead speed hours, a direction of the tube dead, hours the reporter logged as pure emptiness, and the balance audit below. The hours they name are recorded as *untrusted*.
3. **Gap fill** (`quality.py`): the hour grid is completed per sensor; untrusted hours are dropped first. Holes up to 3 hours are interpolated between the neighbours, longer holes take the median of the same hour on the same kind of day (same calendar month first, then any month, then any day type). Filled hours get `imputation_method` and state `imputed` in `series.csv` (demo run: 24 interpolated, 75 profile-filled hours).
4. **Traffic detectors** (`detect.py`, issue #19) run on the filled table but **never on imputed hours** — a technical hole may not be counted twice, once as sensor work and once as traffic. The day-shape detector additionally needs days with no imputed hour at all.
5. **Monthly detectors** compare a calendar month with the same month of the other years; after a completeness complaint the month's traffic checks are skipped, and a month (or a peer) under 95 % real hours takes no part in any year-over-year comparison.
6. **Cross-channel confirmation**: volume and speed findings of one sensor whose intervals overlap confirm each other — each side of a pair gets +0.5 score once (cap 6.5, level recomputed through the one contract table) and a sentence in the description saying so (28 findings used the bonus in the demo run).
7. **Merge**: episodes of the same sensor, type and metric that end within 12 hours of each other are told as one story (weighted actual/expected, the loudest score, one rebuilt description) — a two-month repair season is a handful of findings, not 150 fragments.
8. **Finalize**: ids `a133-<type>-YYYYMMDD-NN`, `is_mega` for traffic anomalies with |deviation| ≥ 60 %.
9. **Event linking** attaches `event_id` to anomalies that overlap a reviewed event's day or the day before/after it (news dates round; an overnight accident clears the next morning) and whose type suits the event category; the per-category kind tables live in `pipeline.py` (`EVENT_KINDS`), one anomaly links to at most one event (first event in the review file that fits wins).
10. **Corporate findings** (`corporate.py`, issue #20) are transcribed separately and written into the same `anomalies.json`.

### The balance audit (`quality.py`) — this module's own addition

Every hour of the export must add up three ways: the total equals the two directions, and the total equals the seven vehicle classes. Hours where either identity is off by more than max(10 авт./ч, 2 %) untrust the hour (rounding slack for a 30-column manual export). Untrusted hour groups alone are noisy, so a *month* is reported (`balance_drift`, medium) only when ≥ 30 disagreeing hours spread over ≥ 7 days show ≥ 80 % of them on the same side with a median disagreement ≥ 5 cars — a **metering drift nobody notices**, counted only over the hours that actually disagree. The demo export's two injected drift months are exactly what this rule catches (and single-month +6-авт./h wobbles that stay under the monthly bar pass quietly, by design). A-134 has no equivalent rule; ODM 218.2.020-2012 count reporting assumes classes and directions add up to the totals, and that assumption is the practical reason the identities are worth checking at all.

## Norms

Every hour compares against the median of the **same hour of the same kind of day (weekday / weekend / official holiday, `holidays.py`) in the same calendar month, pooled over all years of the export**. Pooling across years is deliberate: a stormy December must stay a minority inside its own norm instead of dragging that norm down. A consequence worth naming: a holiday that looks the same in every year is absorbed by its own pooled holiday norm, so nothing here can flag a normal festive day. The holiday calendar covers 2023–2026 (Government Decrees № 1505, № 1314, № 1335 and № 1466, linked in `holidays.py`) — which also means 30–31 December 2024 are *holiday* days here: the official transfer made New Year's Eve a non-working day, and an accident on such a day is read against holiday shapes.

The dispersion measure is a **floored robust scale**: `sigma = max(1.4826·MAD, 10 % of the norm, floor)`, with floors of 20 авт./ч (hourly volume), 100 авт./сутки (daily volume), 3 км/ч (speed) and 2 % (load), and `z = (x − median) / sigma`. Without the floors a night hour repeating the same count has a MAD of nothing and any small wobble becomes a 20-sigma storm; a norm of 30 авт./ч gets a sigma of at least 20, keeping the z thresholds honest. Groups with fewer than four reference days are skipped — this also quietly protects the holiday norms from thin months like the December 2024 transfer block.

## Thresholds (settled in #18/#19)

| Detector | Finds | Rule | Why |
| --- | --- | --- | --- |
| `integrity` (day) | `missing_hours` | a day with fewer than 24 hours | a complete export day is 24 hours; lost days and outages land here |
| `sensor` | `flatline` | identical volume > 10 авт./ч for 5 hours in a row | real flow never repeats an exact count 5 hours running |
| `sensor` | `zero_speed` | speed ≤ 1 км/ч while cars pass, ≥ 2 hours in a row | single-hour dropouts are repaired by imputation, not reported |
| `sensor` | `zero_telemetry` | all seven channels (both volumes, both speed, both load, total) exactly 0 for ≥ 12 consecutive hours; the hours are untrusted and imputed | a road can go quiet in a storm, but it does not log a perfectly round zero on every counter in both directions for half a day — that is the reporter sending emptiness, and it must never be read as an empty road |
| `direction` | `direction_imbalance` | a side reads ≤ 5 % of the hour while the other reads > 150 авт./ч, runs ≥ 2 hours | the hour then counts one loop instead of two; 150 and not A-134's 200 because this is a smaller road |
| `balance` | `untrusted hours` / `balance_drift` | see [the balance audit](#the-balance-audit-qualitypy--this-modules-own-addition) | silent metering drift moves the totals, classes and directions apart slowly |
| `amplitude` | `volume_drop`, `volume_spike` | hours vs the same-hour norm: \|z\| ≥ 3 against the floored scale **and** \|actual − norm\| ≥ max(35 % of the norm, 50 авт./ч) together, ≥ 4 hours in a row → one anomaly with the exact interval; runs are told separately on `volume`, `volume_direct` and `volume_reverse` | a deviant hour must be statistically far **and** large in cars, so night wobbles stay quiet; per-direction runs see accidents the total hides |
| `amplitude` | daily drops/spikes | day sum vs the month/kind median: z ≤ −3 / ≥ +3 **and** \|actual − norm\| ≥ max(25 % of the norm, 100 авт./сутки) | a flat percent with no scale behind it is not evidence; the absolute bar kills big-% deviations of a few cars |
| `amplitude` | `speed_drop` | per direction: the norm is built only from hours where that direction counted cars, and an hour flags when its speed is ≥ 15 км/ч under the norm **and** z ≤ −3 **and** this hour's direction volume > 0; ≥ 4 such hours in a row → one anomaly | a slowed road is measured in км/ч, not in % of a norm that is nearly meaningless at night; an hour whose loop counted nothing logs no real speed |
| `speed_load` | `congestion` | daytime (7–21 h) speed < 50 км/ч while lane load > 20 % **in the same hour's record**, ≥ 2 hours | free flow here is 80–90 км/ч; below 50 with confirmed occupancy the queue is real in the ODM-218.2.020-2012 sense; the pairing is per-record, so a slow hour can never be confirmed by another hour's load |
| `profile` | `profile_shift` | full days without imputed hours over 800 авт./day whose hourly shape correlates with the norm below r = 0.70 | norms are flat for quiet days and thin days correlate badly by noise alone; the floor is lower than A-134's 1000 because this approach is calmer |
| `integrity` (month) | `missing_hours` | month completeness under 75 % of hours real | monthly comparisons below that are not trustworthy; the month's other checks are skipped then |
| `yoy` | `volume_drop`, `volume_spike` | monthly average daily volume off ±25 % from the same calendar month's other years, peers from the other years only, and only months ≥ 95 % real hours take part | ±25 % is where road-ops practice treats a month as changed; the validity gate keeps a blacked-out month from comparing itself and from bending other months' norms |
| `mix` | `vehicle_mix_shift` | share of large trucks + road trains moves ±8 п.п., same 95 % gate and peer-only rule | class shares are steadier than volume, so a quiet road can hide a structural change in them |
| `yoy` (speed) | `speed_drop` | the month's **flow-weighted** mean speed (each hour weighted by its direction's cars) ≥ 15 км/ч under its peers' norm | a plain mean lets an empty night hour outvote a full evening one |
| `load` | `level_of_service_shift` | monthly median lane occupancy drifts ±20 % from its calendar norm, same gate | an ODM-218.2.020-style load level shift means the congestion regime changed without the volume changing |
| `regime` | `volume_drop`/`volume_spike` | ≥ 7 consecutive complete days, every day under 0.75 or over 1.25 of its FROZEN norm — the median of the same-kind complete days strictly before the window, within 168 days and ≥ 6 of them; one report per window | a window whose own days feed the norm absorbs itself, so a sustained new level is never told; the frozen historical norm is what sees it |
| `share` | `volume_drop`/`volume_spike` on a direction | the direct share of the flow tips ≥ 25 п.п. away from its day-kind norm for ≥ 4 hours of the same sign, hour volume ≥ 60 авт./ч | one-sided closures (реверс, a loop under repair) move the split long before the total moves |

On the demo export several rules fire 0 times, honestly. `direction` never trips (the synthetic sensors stay healthy in that particular way) and monthly completeness never falls under its bar. `congestion`: the modeled accident slowdowns mostly stay just above 50 км/ч, and the eight daytime hours that went under on the load side were isolated — a queue needs two consecutive ones. The whole year-over-year block (month volume, mix, flow-weighted speed, load level), the frozen-norm `regime` and the direction-tilt `share` are silent because the generator's three years differ only by injected events: no real year-over-year shift, no structural class change, no sustained new level; the injected direction drift (+8 авт./ч, a couple of п.п.) sits far under the share bar on purpose — the balance audit is the rule built to see it, and it does. On real data (winter waves, the real repair season) these silent rows are exactly where the module first wakes up; the speed-drop and amplitude rules already carry every injected story, so none of the silence is a broken pipe.

## Severity

`level` is never chosen by hand: the single `detect.level_from_score()` applies the contract v1 table (≥ 5 critical, ≥ 3.5 high, ≥ 2 medium, else low) — also after the +0.5 of a cross-channel confirmation, which never passes 6.5 and is given to a finding at most once. Scores: statistical detectors report `min(|z|, 9.9)` on the floored scale; rule detectors carry fixed weights on the same scale — integrity 3.0, flatline 4.0, zero_speed 2.5, zero_telemetry 3.5, direction 2.8, balance_drift 3.2 (louder than one lost hour-group, quieter than a broken channel telling its own story), congestion 4.5, profile 2.5, monthly integrity 3.0, yoy MADT 3.5 + 0.1 per point beyond 25 (cap 6.5), mix 2.0 + 0.1 per point beyond 8 (cap 3.5), yoy speed 2.5, load shift 2.0, share tip 2.5, regime 3.5 + 0.1 per % beyond 25 (cap 6.5). `is_mega` flags traffic anomalies with |deviation| ≥ 60 % (FR3) — never technical ones (7 in the demo run).

## What we took from other analyzers

[dilczech/traffic_anomaly_analyzer](https://github.com/dilczech/traffic_anomaly_analyzer) (numpy/pandas only, same style of 29-column report) gave the floored robust sigma, the practical-magnitude AND-tests beside the z, the per-direction speed norms built only from hours where the direction counted cars, the frozen-norm regime detector (re-scored onto our contract scale), the ≥ 12-hour zero-packet distrust, the volume×speed overlap promotion (turned from priority labels into +0.5 score) and the flow-weighted monthly speed with the ≥ 95 % validity gate. [Lexandrine/flow-analysis](https://github.com/Lexandrine/flow-analysis) is the ancestor of the same architecture the A-134 module grew from, so the norm-referenced amplitude/profile/monthly core came through it.

Ours — ported nowhere — are the **balance audit** (hourly identities + the monthly drift story over disagreeing hours only), the **direction-tilt** share check, and the **episode merge** pass. We still neither copy the analyzers' `min(speed)/max(load)` congestion pairing (ours is per-record) nor their `fillna(0)` parsing (missing is missing here, not zero).

## Events (issue #17)

`events.csv` is the manual-review table: 19 outside events for 2023–2025 found by browsing Lipetsk news and the official production calendar — 4 official holiday periods, 6 real crashes on this road, the December 2024 wet-snow warning, four repair-season milestones (including the М-4 km 414–429 works whose Lipetsk exits affect these approaches), the 2025-11-17 city blackout, and three city-life days (City Day 2023, the two red-level UAV nights). Every row carries a `source_url` opened during the research. Two tempting stories were dropped for lack of a datable page; both "red level" events sit in category `other` because a siren is neither accident nor roadworks, the Karla Marksa теплотрасса closure is `roadworks` because that is what it physically was.

Linking is deliberately narrow: an anomaly links only if its interval overlaps the event **day ± 1 day** and its type suits the category — accident: the drop/slow types and `profile_shift`; roadworks and other: those plus spikes; weather: drop types and `profile_shift`; holiday: volume drops, spikes and `profile_shift`; outage: only the technical findings. Because an accident here stops traffic without emptying the road, `speed_drop` is an accident-suitable kind (unlike the A-134 file). "Found" means exactly: at least one linked finding.

**Read this table as what it is: a demo round-trip.** The generator embedded these same events' effects into the synthetic traffic by design, so 18/19 measures that the detectors, the linking rules and the category tables carry every reviewed story end to end — it is not evidence about the real road, which the module has not seen yet. One honest miss survived even that:

| Event | Category | Found | Why / why not |
| --- | --- | --- | --- |
| 2023-01-01 New Year holidays | holiday | **found** | 2 linked findings (profile-shape days the pooled holiday norm does not quite describe) |
| 2023-05-09 Victory Day holidays | holiday | **found** | 6 linked: morning quiet + evening return peaks |
| 2025-01-01 New Year holidays | holiday | **found** | 2 linked |
| 2025-05-09 Victory Day | holiday | **found** | 5 linked |
| 2023-12-22 mass crash near Borinskoye | accident | **found** | 6 linked: evening/night congestion and speed drops on km 40 |
| 2024-09-26 three dead on the Don alternative | accident | **found** | 3 linked: the morning clearance slows the corridor sensor |
| 2024-12-30 three cars, four dead, km 20 | accident | **found** | 2 linked: 30 December is an official transfer-holiday, so the night reads against holiday shapes and the crash shows as a profile shift — an honest demo limitation of norm-referencing when an accident lands on a holiday |
| 2025-04-18 car burns on Gryazi road | accident | **found** | 6 linked: half-day standstill |
| 2025-11-24 fatal crash Lipetsk–Gryazi | accident | **found** | 7 linked: evening flow on one lane |
| 2025-12-29 two dead Lipetsk–Khlevnoye | accident | **found** | 7 linked |
| 2024-12-19 wet snow and ice, region-wide | weather | **found** | 4 linked: two-day speed drops on both sensors |
| 2024-04-19 repair season opens | roadworks | **found** | 4 linked: long speed-drop episodes from April on |
| 2024-07-24 Karla Marksa closed (city) | roadworks | **found** | 8 linked: the city traffic the closure pushed onto the approaches |
| 2025-09-15 М-4 km 414–429 repair starts | roadworks | **found** | 4 linked (autumn works season at the interchange exits) |
| 2025-11-14 Lipetsk–Dobroe–Chaplygin repair finishes | roadworks | **found** | 4 linked (same nearby works story) |
| 2025-11-17 blackout in the city centre | outage | **found** | 1 linked: exactly the technical findings of the six dead hours |
| 2023-07-14 City Day | other | **found** | 5 linked: evening peaks toward the city |
| 2024-04-19 red level, UAV threat at ~23:00 | other | missed | the slow episode it made that night overlaps the same day's repair-season finding, and the repair row comes first in the file — first-fit linking gave the night to the seasonal story (the anomaly exists and is loud; the attribution went elsewhere) |
| 2025-07-17 red level, sirens at ~01:00 | other | **found** | 4 linked: the overnight drop |

## Corporate findings (issue #20)

`corporate_findings.csv` is a hand-retyped extract of the customer's corporate monitoring for this road: 24 rows on the two sensors (18 traffic, 6 technical), spanning the same period as the export. 14 of them overlap a finding of ours within ±1 day — the storms, crashes and repair waves both systems see — and 10 do not: a red flatline alarm on 2025-08-08 when both sensors logged clean, an orange dead-reporter claim on 2024-06-15 that counted a quiet day as silence, a yellow congestion alarm on 2025-10-21 with no load above its bar anywhere near it. Transcription only, as the contract asks: `detector = corporate`, `score = null`, ids `a133-corp-NNNN`, kept out of finalization; the interface's yellow/orange/red map onto the v1 table through fixed representative scores (1.5 / 2.8 / 4.2) for the `level` field only, which is why the stream reads 13 low / 6 medium / 5 high.

## Sensors

| id | section | near | coords (OSM-approximate) |
| --- | --- | --- | --- |
| `a133-km12-0` | км 12+000 а/д А-133 | Елецкая Лозовка, Хлевенский округ | 52.29525, 39.16719 |
| `a133-km40-0` | км 40+000 а/д А-133 | Боринское | 52.47469, 39.40193 |

Section names come from the export's own labels; `parse.sensor_id` turns «км 12+000» into `a133-km12-0` (the contract id regex). Coordinates were read off the OSM road chain at the given kilometre — **approximate, unverified against the customer's camera passport**, and both sensors count `direct` = на Липецк. If a future export adds sections, `parse.py KNOWN_SENSORS` prints exactly what to add.

## Status

Issues #16–#21 are implemented on the `analysis/a133-module` branch: parser and contract output (#16), event research (#17), failure handling, gap fill and the balance audit (#18), settled thresholds and severity (#19), corporate transcription (#20), committed output, 27 tests and this README (#21). Open by nature: the real customer export (everything current is the seeded demo), re-running the event research against whatever the real data shows, verifying the coordinates, and re-settling thresholds if the customer disputes a call.
