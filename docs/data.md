# 数据获取与字段说明

## 内置样例

`portfolio_app/sample_data/` 中的 CSV 由固定随机种子生成，包含日线、成交量以及演示用 ROE/PB。它们不是实际证券数据。无需联网即可运行；生成脚本为 `portfolio_app/sample_data/generate_demo_data.py`。

## 获取真实行情

可从已经有权使用的数据服务下载行情，再通过“数据”导入。常用来源包括 [Tushare Pro](https://tushare.pro/document/2)、[AKShare](https://akshare.akfamily.xyz/) 和交易所提供的资料。接口权限、覆盖范围与收费由提供方决定，本项目不代购权限。

仓库提供 `scripts/fetch_tushare.py`，按单只股票下载**未复权日线**。需要 Tushare token 及对应接口权限；不会下载财务报表、生成复权价格或自动写入平台的研究登记库。

```bash
python -m pip install -r requirements.txt
```

PowerShell 设置当前终端的 token：

```powershell
$env:TUSHARE_TOKEN = "你的 token"
python scripts/fetch_tushare.py --symbol 600000.SH --start 20240101 --end 20261030 --output data/600000.SH.csv
```

macOS / Linux：

```bash
export TUSHARE_TOKEN="你的 token"
python scripts/fetch_tushare.py --symbol 600000.SH --start 20240101 --end 20261030 --output data/600000.SH.csv
```

示例日期是固定区间，按实际需要修改。脚本拒绝覆盖现有文件，空返回或可能超过接口行数上限时停止。下载后选择“文件导入”；未复权价格遇到除权分红会出现跳变，做收益研究前需选择一致的数据口径。

token 只通过环境变量读取，不写入仓库。`data/`、`output/` 和本地密钥文件已列入 `.gitignore`。

## 文件字段

每行是一只标的一个交易日，按标的和日期唯一。多标的可放在同一个文件。

| 字段 | 要求 | 含义 |
| --- | --- | --- |
| `trade_date` | 必需 | `YYYY-MM-DD` 或 `YYYYMMDD` |
| `symbol` / `ts_code` | 多标的必需 | 标的代码，推荐保留市场后缀 |
| `open`, `high`, `low`, `close` | 必需 | 同一价格口径的开高低收 |
| `vol` | 可选 | 成交量，原始单位保留；不能直接假定为股数 |
| `amount` | 可选 | 成交额，使用数据源原单位 |
| `pre_close` | 可选 | 数据源提供的前收盘价 |
| `turnover_rate` | 可选 | 换手率，百分数值，如 1.5 表示 1.5% |
| `roe` | 质量动量所需 | ROE 百分数值，如 8 表示 8% |
| `pb` | 质量动量所需 | 市净率倍数，必须有效且大于 0 |

```csv
trade_date,symbol,open,high,low,close,vol
2024-01-02,EXAMPLE,10.0,10.4,9.9,10.2,10000
2024-01-03,EXAMPLE,10.2,10.5,10.1,10.3,12000
```

CSV 使用 UTF-8。文件导入支持 CSV、XLSX/XLS 和 Parquet。研究输入上限为 150,000 行、96 MiB 内存估计，实际上传还受 Streamlit 配置限制；大数据应先选取研究区间和标的。

## 接入本地行情目录

在“看盘”使用本地行情时，目录约定为：

```text
data/
├── stock_basic.csv                   # 可选：ts_code,name
├── daily_raw_merged/600000.SH.parquet # 未复权
├── daily_qfq_merged/600000.SH.parquet # 前复权
└── daily_hfq_merged/600000.SH.parquet # 后复权
```

每个 Parquet 同样使用上表字段。`PORTFOLIO_DATA_ROOT` 可以指向目录根部；只填实际拥有的数据口径，不能将 raw 文件改名当作 qfq。仓库不附带这些文件，也不会启动时自动下载市场行情。

## 时点与复权

财务数据应按公告实际可用时间与交易日对齐，不能按报告期末回填，也不能把今天查询的 ROE 当作当时已知数据。字段可用时点、历史成分和复权因子缺失时，不能据此证明回测满足历史信息条件。

前复权和后复权应由原始价格与明确来源的复权因子计算。更新前复权基准要统一重算历史，不能把不同基准直接拼接；低价复权数据保留小数精度。ETF 未复权价格不等于分红再投资总收益。更多计算口径见 [methodology.md](methodology.md)。
