# Module `a134`: A-134, approach to Voronezh

Owner: @Lexandrine

Reads the customer's raw export from `analysis/data/raw/a134/` (not in git) and writes the result to `analysis/output/a134/` following the [data contract](../../docs/contract.md).

```sh
uv run python -m analysis.a134                              # run the module
uv run python -m contract.validate analysis/output/a134     # check the result
```

The method, its thresholds and why they are what they are will be described here as the work goes on (see the issues with the road's label).

## Detection Methods

- **Heuristics**: Adaptive thresholds, seasonality, Russian holidays, trend detection
- **ML Prophet**: Time series forecasting with confidence intervals
- **ML Isolation Forest**: Multivariate anomaly detection
- **Consensus**: Cross-validation between methods

The module uses a hybrid approach combining rule-based and ML methods for robust anomaly detection.
