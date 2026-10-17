# Module `r22`: R-22 "Caspian", approach to Saratov

Owner: @Kishulia

Reads the customer's raw export from `analysis/data/raw/r22/` (not in git) and writes the result to `analysis/output/r22/` following the [data contract](../../docs/contract.md).

```sh
uv run python -m analysis.r22                              # run the module
uv run python -m contract.validate analysis/output/r22     # check the result
```

The method, its thresholds and why they are what they are will be described here as the work goes on (see the issues with the road's label).
