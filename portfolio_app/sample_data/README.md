# Synthetic Demo Data

The CSV files in this directory are deterministic synthetic datasets created for demonstrating the portfolio application on GitHub.

They are not real securities, are not downloaded from a market-data vendor, and do not represent investment performance.

## Files

- `quant_demo_daily.csv`: the original compact one-symbol smoke-test file;
- `quant_demo_single_symbol.csv`: 300 synthetic trading-day rows for price charts, signals, and single-symbol backtests;
- `quant_demo_multi_symbol.csv`: four synthetic symbols with partially overlapping dates for equal-weight portfolio alignment and per-symbol comparison;
- `generate_demo_data.py`: deterministic standard-library generator for the two larger files.

Run from the repository root if the generated files need to be refreshed:

```powershell
python portfolio_app/sample_data/generate_demo_data.py
```

The generated series intentionally include trend, drawdown, volatility, and small date gaps. They are designed to exercise the application workflow, not to model a real market.
