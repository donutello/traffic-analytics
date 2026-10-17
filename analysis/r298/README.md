# Module `r298`: R-298 Kursk – Borisoglebsk

Owner: @nastGU

Reads the customer's raw export from `analysis/data/raw/r298/` (not in git) and writes the result to `analysis/output/r298/` following the [data contract](../../docs/contract.md).

```sh
uv run python -m analysis.r298                              # run the module
uv run python -m contract.validate analysis/output/r298     # check the result
```

The method, its thresholds and why they are what they are will be described here as the work goes on (see the issues with the road's label).
