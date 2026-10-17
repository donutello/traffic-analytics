# Data contract

> **Status: draft v0.** This is a starting point, ported from an earlier draft. The contract owners confirm or change it in issue #1, and then it becomes v1.

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

Each module decides which anomalies get `is_mega` and how to compute `score`, and describes it in its README.

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
