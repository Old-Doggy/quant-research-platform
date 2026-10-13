# Python Data Workbench

**A runnable Python portfolio project for financial data analysis, research workflows, and interactive visualization.**

**Language:** [简体中文](README.zh-CN.md) · English

## Project Snapshot

- **Positioning:** data analysis and research engineering portfolio
- **Runtime:** Python 3.12 baseline
- **Interface:** Streamlit dashboard
- **Included data:** deterministic synthetic datasets
- **Input formats:** CSV, Excel, and Parquet
- **Public strategies:** trend following, mean reversion, and quality momentum
- **Validation:** local tests and GitHub Actions on Ubuntu and Windows
- **Safety boundary:** no private strategies, real research returns, raw market data, credentials, or trading runtime files

This project demonstrates an end-to-end workflow for daily market-style data:

- import and normalize files;
- check dates, prices, missing values, duplicates, and symbols;
- generate interpretable strategy signals;
- run a simple transaction-cost-aware backtest;
- compare single-symbol and equal-weight multi-symbol portfolios; and
- explore the results through interactive charts.

It is a portfolio project, not a claim of trading performance or a production trading system.

## Quick Start

The bundled datasets are synthetic. No broker account, market-data API, or secret is required.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run streamlit_app.py
```

### macOS or Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run streamlit_app.py
```

Open the local address printed by Streamlit, normally `http://localhost:8501`.

To use another port:

```bash
python -m streamlit run streamlit_app.py --server.port 8517
```

## Application Pages

| Page | What to inspect |
| --- | --- |
| Quant Dashboard | Prices, indicators, signals, strategy parameters, costs, equity curves, and drawdowns |
| 数据分析 | Data summaries, per-symbol return and risk statistics, and quality reports |
| 策略比较 | Three demonstration strategies on the same input data |
| 项目说明 | Scope, methodology notes, and limitations |

## Public Strategy Demos

1. **Trend following**
2. **Mean reversion**
3. **Quality momentum** using optional ROE and PB fields

The quality-momentum example handles missing fundamental fields conservatively. When the required fields are unavailable, it may produce no signal.

## Import Your Own Data

The application accepts:

- CSV files;
- Excel files (`.xlsx` and `.xls`); and
- Parquet files.

Required fields:

```text
trade_date, open, high, low, close
```

Common Chinese and English field aliases are normalized automatically. Multi-symbol files may include `ts_code` or `symbol`; `volume`, `roe`, and `pb` are optional.

Uploaded files are analyzed in the current application session. The application does not intentionally save uploads to disk or add them to the repository. Use a local instance for sensitive data.

## Demo Data

`portfolio_app/sample_data/` contains deterministic synthetic data:

- `quant_demo_single_symbol.csv`: 300 rows for charts, signals, and single-symbol backtests;
- `quant_demo_multi_symbol.csv`: four synthetic symbols for alignment and equal-weight comparison; and
- `generate_demo_data.py`: a standard-library generator for refreshing both datasets.

These files are not downloaded market data and have no investment meaning.

## Verification

Install the development dependencies, then run:

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pip check
.\.venv\Scripts\python -m pytest
```

On macOS or Linux, use `.venv/bin/python` instead. GitHub Actions checks Python 3.12 and 3.13 on Ubuntu and Windows.

## Methodology Notes

- Signals are shifted by one row before close-to-close return calculation.
- Trading costs are applied to changes in position.
- The portfolio view uses a simplified dynamic equal-weight return combination.
- The example does not model next-open execution, a full cash ledger, capacity, limit-up/limit-down rules, or suspension constraints.
- Annualization uses 252 trading days.
- The displayed Sharpe-style metric uses annualized compounded return divided by annualized volatility with a zero risk-free rate; it is not the arithmetic-mean Sharpe ratio.
- The application does not place orders and does not guarantee profits.

## Public Scope and License

The repository intentionally excludes private strategies, important research parameters, real historical research returns, model weights, raw market data, account information, broker or QMT files, and runtime artifacts. The included strategies and datasets are generic demonstrations only.

No open-source license has been selected yet. Until a license is added, reuse and redistribution should not be assumed. See [`DEPLOYMENT.md`](DEPLOYMENT.md) for publishing and hosting boundaries.
