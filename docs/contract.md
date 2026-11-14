# Data contract

> **Status: v1 (confirmed 2026-11-14).** The contract owners (@technostd and the four analysts) confirmed the draft in issue #1. The file format stands as it was; the meaning of `score`, `level` and `is_mega` is now a rule (see [Severity](#severity-score-level-and-is_mega)), and the document now says how every API endpoint is built from these files.

The contract describes the files a road module writes to `analysis/output/<road>/`. The backend imports these files into the database, and the dashboard only reads the database. The modules, the backend and the frontend depend only on this format, not on each other. Why it works this way: [ADR 0004](adr/0004-data-flow-through-files.md) and [ADR 0006](adr/0006-data-contract-as-pydantic-models.md).

The source of truth is the Pydantic models in [`contract/models.py`](../contract/models.py). This document explains them. A full example set: [`analysis/output/_example/`](../analysis/output/_example/) (made-up data with all three states of the series, a mega-anomaly and the corporate system's findings).

## Who owns it

- @technostd owns the shared models in `contract/` and the import into the database.
- Each analyst owns the export of their road: @mmsh55 (`a133`), @Lexandrine (`a134`), @nastGU (`r298`), @Kishulia (`r22`).
- A change to the contract is a pull request that @technostd and every analyst whose road it affects approve.

## Checking

```sh
uv run python -m contract.validate analysis/output/a134   # one road
uv run python -m contract.validate                        # every road in analysis/output/
```

The check looks at each file and at the links between files: the sensors in `series.csv` and in the anomalies exist in `sensors.json`, every `event_id` exists in `events.json`, ids don't repeat, and each sensor has at most one line per hour.

## Files

| File | Required | What's in it |
| --- | --- | --- |
| `sensors.json` | yes | the road and its sensors |
| `series.csv` | yes | the hourly series of every sensor |
| `anomalies.json` | yes | anomalies found by the module (may be `[]`) |
| `events.json` | no | outside events that explain anomalies |
| `corporate_anomalies.json` | no | anomalies found by the customer's corporate system |

No other files are allowed in a road directory: otherwise a typo in a file name would go unnoticed.

## What the API builds from these files

The backend imports the files into the database (issue #4) and keeps everything in them, so each endpoint of issues #5–#7 is one query. These notes are the check that the contract is enough; the prototype responses in [`frontend/public/mock/`](../frontend/public/mock/) (generated from the `_example` set) show the same shapes.

- `GET /api/series?sensor=&from=&to=&granularity=hour|day|week` (#5): `hour` gets one point per `series.csv` line of that sensor (`ts`, `volume`, `state`). `day` and `week` sum the hours of each group; the state of a group is `anomaly` if a `traffic` anomaly of the same sensor in `anomalies.json` covers any of its hours (`sensor_id` + interval), else `imputed` if any line of the group is `imputed`, else `normal`.
- `GET /api/sensors?road=&from=&to=` (#6): one GeoJSON Feature per sensor of `sensors.json` (`id`, `name`, `road`, `km`, coordinates, `directions`). `anomaly_count` is the number of ours and corporate anomalies of that sensor whose interval touches the period; `is_mega` is whether any of the sensor's anomalies has `is_mega` set.
- `GET /api/anomalies?road=&sensor=&from=&to=&type=&source=&level=` (#6): the items of `anomalies.json` with `source: "ours"` plus the items of `corporate_anomalies.json` with `source: "corporate"` — `source` is which file the anomaly stands in, not a field of the file. The period filter is interval overlap; `sensor_name` for the list comes from `sensors.json`.
- `GET /api/anomalies/{id}` (#6): the anomaly's own fields (time, `deviation_pct`, `actual`, `expected`), the sensor's `name`, and when `event_id` is set the event from `events.json` with its `description` and `source_url`, so the side panel can show the cause and its link.
- `GET /api/comparison?road=&from=&to=` (#7): ours and corporate items on the same `sensor_id` whose intervals overlap match ("both found"); the rest are "only ours" and "only corporate"; counts and shares are counted from these three lists in the two files.
- The meta the frontend header shows: one entry per road directory (`road`, `road_name`, sensor count from `sensors.json`) and the whole period (smallest and biggest `ts` in all `series.csv` files).

## General rules

- UTF-8. JSON with indentation (so diffs in pull requests are readable). CSV with commas and a dot as the decimal separator.
- Time is ISO 8601 with an offset, always at the start of an hour: `2025-03-08T10:00:00+03:00`. Time without an offset is rejected. The customer's data is in Moscow time, so the offset is usually `+03:00`.
- An anomaly's interval is half-open: `starts_at` is included, `ends_at` is not. An anomaly for the whole day of March 8: `2025-03-08T00:00:00+03:00` to `2025-03-09T00:00:00+03:00`. An anomaly of one hour: `10:00` to `11:00`.
- Every id starts with the road code and a dash: `a134-km12`, `a134-0001`, `a134-crash-20240308`. This keeps ids unique across the whole database. The road code is the directory name.
- Fields are never left out: if there is no value, write `null` (an empty cell in CSV).
- Codes (`type`, `detector`, `metric`) are English `snake_case`. Texts that users see in the dashboard (`road_name`, `name`, `directions`, `title`, `description`) are in Russian.

## `sensors.json`

An object with the road and its sensors.

| Field | Type | Description |
| --- | --- | --- |
| `road` | string | road code, equal to the directory name: `a133`, `a134`, `r298`, `r22` |
| `road_name` | string | name for the UI: «А-134, подъезд к г. Воронеж» |
| `sensors[].id` | string | `<road>-<anything>`, for example `a134-km12` |
| `sensors[].name` | string | label for the UI, for example «км 12+300» |
| `sensors[].km` | number | kilometre where the sensor stands |
| `sensors[].lat`, `lon` | number | coordinates in degrees (WGS 84) |
| `sensors[].directions` | object | labels of the two directions: `{"direct": "на Воронеж", "reverse": "из Воронежа"}` |

## `series.csv`

One line is one hour of one sensor. The columns go in exactly this order:

| Column | Type | Description |
| --- | --- | --- |
| `sensor_id` | string | id from `sensors.json` |
| `ts` | time | start of the hour |
| `volume`, `volume_direct`, `volume_reverse` | integer ≥ 0 | vehicles per hour: total and per direction |
| `cars`, `small_trucks`, `medium_trucks`, `large_trucks`, `road_trains`, `buses`, `motorcycles` | integer ≥ 0 or empty | vehicle mix by class, both directions together |
| `speed_direct`, `speed_reverse` | number ≥ 0 or empty | mean speed, km/h (empty if there were no vehicles) |
| `load_direct`, `load_reverse` | number 0–100 or empty | lane occupancy, % |
| `state` | `normal`, `anomaly`, `imputed` | state of the hour (FR2) |
| `imputation_method` | `interpolation`, `profile` or empty | how the hour was filled in |

Rules for `state`:

- `normal`: a real value with no deviation.
- `anomaly`: a real value inside the interval of at least one `traffic` anomaly from `anomalies.json`.
- `imputed`: there was no value, or it can't be trusted (lost connection, stuck sensor), and the module filled it in. `imputation_method` is set if and only if `state` is `imputed`. A filled-in hour is always `imputed`, even inside an anomaly.

Ways to fill in a gap: `interpolation` is a straight line between the neighbouring hours (short gaps), `profile` is the median value of the same hour on the same kind of day. A new way is added to the contract by a pull request.

Missing hours that were not filled in are simply absent from the file. Writing lines in order (`sensor_id`, then `ts`) is easier to read, but the check doesn't require it. The same hour of one sensor must not appear twice.

## `anomalies.json`

A list of anomalies. One anomaly is one sensor and one continuous interval.

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | `<road>-<anything>`, unique in the file |
| `sensor_id` | string | id from `sensors.json` |
| `starts_at`, `ends_at` | time | interval `[starts_at, ends_at)`, both at the start of an hour |
| `category` | `traffic`, `technical` | `traffic`: something happened on the road; `technical`: the sensor or its connection failed |
| `type` | code | what was found: `volume_drop`, `volume_spike`, `flatline`, `congestion`, `missing_hours`, ... |
| `detector` | code | which detector found it: `amplitude`, `profile`, `sensor`, ... |
| `level` | `low`, `medium`, `high`, `critical` | how serious it is |
| `metric` | code | the `series.csv` column the values refer to: `volume`, `speed_direct`, ... |
| `actual`, `expected` | number or `null` | actual and normal value over the interval, in the units of `metric` |
| `deviation_pct` | number or `null` | `(actual − expected) / expected × 100` |
| `score` | number ≥ 0 or `null` | strength of the deviation on the detector's own scale, higher is stronger |
| `is_mega` | boolean | a mega-anomaly, highlighted on the map and charts (FR3) |
| `event_id` | string or `null` | id from `events.json`, if the cause is known |
| `description` | string or `null` | explanation for the side panel: «Поток упал до 720 авт. вместо 4800» |

### Severity: `score`, `level` and `is_mega`

These three fields must mean the same thing on all four roads, so one road's "high" and "mega" look like every other road's. They are rules, not suggestions; each module still lists its own weights and rules in its README.

`score` — the strength of the deviation on one shared scale, from 0 up, one decimal place. In practice a score stays under 10.

- A detector that measures deviation against a statistical norm writes the modified |z| (like the `amplitude` detector in a134).
- A detector with a fixed rule (a stuck sensor, missing hours, congestion) writes a fixed weight per rule, picked to land where the table below puts that kind of finding (the weights a134 already uses — 3.0 `integrity`, 4.0 `flatline`, 2.8 `direction`, 4.5 `congestion`, 2.5 `profile` — sit on this scale; a134 brings the `level` of these weights in line with the table in #25).
- Corporate anomalies have no score: `score` is `null` in every `corporate_anomalies.json` item. So it is for a detector that has no number of its own (a134's monthly detectors until #25).

`level` follows from `score` through this table, so the roads bucket alike:

| `score` | `level` |
| --- | --- |
| below 2 | `low` |
| 2 – 3.4 | `medium` |
| 3.5 – 4.9 | `high` |
| 5 and above | `critical` |

When `score` is `null`, the producer picks the band its anomaly looks like (for corporate ones: map the corporate system's own severity classes onto the table).

`is_mega` — the road's biggest events, highlighted on the map and charts (FR3), the same bar everywhere:

- a traffic anomaly with `|deviation_pct| ≥ 60` gets `is_mega: true` (the threshold a134 already has);
- every such anomaly must be marked — no road may skip it to keep its map quiet;
- everything else is `false`: `technical` anomalies, anomalies with `deviation_pct: null`, and all corporate anomalies (the map highlights our findings; the comparison section shows the corporate ones anyway).

So in `anomalies.json` an anomaly is mega exactly when it is `traffic` and |deviation| reaches 60 %; the `_example` set follows this, and `contract/test_validate.py` checks the example against these rules.

## `events.json`

A list of outside events found by manual review.

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | `<road>-<anything>`, unique in the file |
| `date` | date | `2025-03-08` |
| `category` | `accident`, `roadworks`, `weather`, `holiday`, `outage`, `other` | crash, roadworks, weather, holiday, loss of connection or power, other |
| `title` | string | title for the UI |
| `description` | string or `null` | details |
| `source_url` | string | link to the source (`http://` or `https://`), required |

## `corporate_anomalies.json`

The corporate system's findings for the same period, in the same format as `anomalies.json`, so the dashboard can compare them with ours (FR4). Fields the corporate system doesn't have (usually `score` and `description`) are `null`, and `detector` is `corporate`. Two anomalies match if they are on the same sensor and their intervals overlap.

## Changing the contract

A change is its own pull request that updates `contract/models.py`, this document, the `_example` set and, if needed, the import, all together. Adding a new value to a list of allowed values (a way to fill gaps, an event category) is easy. Renaming or removing a field means changing the import and every module at the same time.
