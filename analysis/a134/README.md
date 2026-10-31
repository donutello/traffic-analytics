# Module `a134`: A-134, approach to Voronezh

Owner: @Lexandrine

Reads the customer's raw export from `analysis/data/raw/a134/` (not in git) and writes the result to `analysis/output/a134/` following the [data contract](../../docs/contract.md).

```sh
uv run python -m analysis.a134                              # run the module
uv run python -m contract.validate analysis/output/a134     # check the result
```

## Method

The code is a reworked port of the three detectors from the earlier standalone analyzer ([Lexandrine/traffic_anomaly_analyzer](https://github.com/Lexandrine/traffic_anomaly_analyzer)). Charts and the Excel report of that analyzer are not ported: the dashboard shows the same data from the contract files. Machine-readable codes are English; only `description`, `name` and `road_name` text is Russian, as the contract asks.

**Parse** (`parse.py`). Each `.xlsx` report in the raw folder is a vertical report: section rows («км 8+…») and hourly rows of 29 columns. Every recognizable hour becomes one row with the contract's column names; values are Moscow time (`+03:00`), cut to whole hours. Duplicated hours (overlapping reports) keep the first file. The per-direction splits by vehicle class are dropped: the contract keeps per-class totals and per-direction speed and load.

**Daily detectors** (`detect.py`), per sensor and calendar day:

| Detector | Finds | Rule | Why this threshold |
| --- | --- | --- | --- |
| `integrity` | `missing_hours` | fewer than 24 hours in a day | a complete export day is 24 hours |
| `sensor` | `flatline` | the same volume > 10 авт./ч for 5 hours in a row | real flow never repeats an exact count 5 hours running (the earlier README said 3+; the analyzer's code always used 5 and gave fewer false alarms, see #25) |
| `direction` | `direction_imbalance` | on days over 500 авт./day the share of one direction leaves 15–85 % | the approach carries both directions roughly evenly; an extreme split usually means the tube of one direction died, so it counts as `technical` |
| `speed_load` | `congestion` | a daytime (7:00–21:00) speed < 50 км/ч while the lane load is > 20 % | on this approach free flow is 70–90 км/ч; below 50 the queue is real, and `expected` is the 80 км/ч free-flow baseline (the README/code disagreement is settled in #25) |
| `profile` | `profile_shift` | full day over 1000 авт. whose hourly profile correlates with the norm of the same month and day type below r = 0.70 | norms are medians per hour, weekday/weekend apart; busy days only, because a thin day correlates badly by noise |
| `amplitude` | `volume_drop`, `volume_spike` | daily volume vs the median of the same month and day type: z < −3 and −25 % (or −50 % alone) for a drop; mirror for a spike | z is the modified z-score `0.6745·(x − median)/MAD`; the ±50 % rule catches what a calm month hides |

**Monthly detectors** (`detect.py`), year-over-year, only when the same calendar month has at least two years of data: data completeness below 75 % (`missing_hours`), monthly average daily volume deviating ±25 % from that calendar month's median (`volume_drop`/`volume_spike`, critical from ±40 %), the heavy-truck share (large trucks + road trains) moving ±8 п.п. (`vehicle_mix_shift`), average monthly speed dropping 15 км/ч below the norm (`speed_drop`).

**Series states** (`series.csv`): `anomaly` marks every hour covered by a `traffic` anomaly; filling in gaps (`imputed`) comes with #24, so lost hours are simply absent for now.

**`is_mega`** marks a traffic anomaly whose |deviation| reaches 60 % — it shows the road's biggest events on the map without waiting for the manual review (#23).

**`score`** follows the ported analyzer: the amplitude detector reports |z|, the others report fixed severity weights (integrity 3.0, flatline 4.0, direction 2.8, congestion 4.5, profile 2.5, monthly detectors null). Rebuilding scores on one scale for all detectors is part of #25.

## Sensors

The exports report one section so far: «км 8+100 а/д А-134» (id `a134-km8-100`, on «Московский проспект» near хутор Ветряк, coordinates in `KNOWN_SENSORS`, taken from OSM landmarks of the М-4 «Дон» — Воронеж rebuilding). A sensor found in the exports without an entry there is written out without coordinates and the module prints what to add — finding coordinates from km marks is the open part of #22.

## Status

Ported and rewritten to the contract in #22 (parser, hourly series, ported detectors as a first step of #25). Threshold settling, vehicle-mix and holiday handling and the cross-check against the manual review continue in #23–#25; gap filling in #24; the committed result and the CI check of this road in #27.
