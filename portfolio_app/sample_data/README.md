# Synthetic Demo Data

The files in this directory are deterministic synthetic datasets for demonstrating the public application. They are not real securities, are not downloaded from a market-data vendor, and do not represent investment performance.

## Files

- `quant_demo_single_symbol.csv`: 300 rows for price charts, signals, and single-symbol backtests;
- `quant_demo_multi_symbol.csv`: four synthetic symbols with partially overlapping dates for alignment and equal-weight comparison; and
- `generate_demo_data.py`: a reproducible standard-library generator for both datasets.

Run from the repository root when the files need to be refreshed:

```powershell
python portfolio_app/sample_data/generate_demo_data.py
```

The generated series intentionally include trend, drawdown, volatility, and small date gaps. They exercise the application workflow without attempting to model a real market.

---

# 合成示例数据（中文）

本目录中的文件是用于演示公开应用的可重复合成数据。它们不是真实证券，不是从行情供应商下载的历史数据，也不代表任何投资业绩。

## 文件说明

- `quant_demo_single_symbol.csv`：300 条单标的数据，用于价格图表、信号和单标的回测；
- `quant_demo_multi_symbol.csv`：4 个日期部分重叠的合成标的，用于数据对齐和等权组合比较；
- `generate_demo_data.py`：使用 Python 标准库重新生成两份数据的脚本。

如需刷新示例文件，请在仓库根目录运行：

```powershell
python portfolio_app/sample_data/generate_demo_data.py
```

生成的数据有意包含趋势、回撤、波动和少量日期间隔，用于覆盖应用流程，不用于模拟真实市场。
