# Module `a133`: A-133, approach to Lipetsk

Owner: @mmsh55

Reads the customer's raw export from `analysis/data/raw/a133/` (not in git) and writes the result to `analysis/output/a133/` following the [data contract](../../docs/contract.md).

```sh
uv run python -m analysis.a133                              # run the module
uv run python -m contract.validate analysis/output/a133     # check the result
```

The method, its thresholds and why they are what they are will be described here as the work goes on (see the issues with the road's label).
