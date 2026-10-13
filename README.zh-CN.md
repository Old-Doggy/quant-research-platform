# Python 数据分析与研究工作台

**一个可运行的 Python 作品集项目，用于展示金融数据分析、研究流程和交互式可视化能力。**

**语言：** 简体中文 · [English](README.md)

## 项目概览

- **项目定位：** 数据分析与研究工程作品
- **运行环境：** Python 3.12 为基准版本
- **交互界面：** Streamlit 数据看板
- **内置数据：** 可重复生成的合成数据
- **支持格式：** CSV、Excel 和 Parquet
- **公开策略：** 趋势跟踪、均值回归、质量动量
- **验证方式：** 本地测试，以及 Ubuntu 和 Windows 上的 GitHub Actions
- **公开边界：** 不包含私人策略、真实研究收益、原始行情、凭证或交易运行文件

本项目围绕金融日线数据演示完整的分析流程：

- 导入文件并统一字段；
- 检查日期、价格、缺失值、重复记录和标的代码；
- 生成可解释的策略信号；
- 运行考虑交易成本的简化回测；
- 比较单标的和多标的等权组合；
- 通过交互式图表查看分析结果。

这是一个作品集项目，不代表真实交易业绩，也不是生产级交易系统。

## 快速运行

仓库内置数据完全合成，不需要券商账户、行情接口或密钥。

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run streamlit_app.py
```

### macOS 或 Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run streamlit_app.py
```

打开 Streamlit 在终端输出的本地地址，通常是 `http://localhost:8501`。

如果默认端口被占用，可以使用：

```bash
python -m streamlit run streamlit_app.py --server.port 8517
```

## 应用页面

| 页面 | 主要内容 |
| --- | --- |
| Quant Dashboard | 查看价格、指标、信号、策略参数、交易成本、净值曲线和回撤 |
| 数据分析 | 查看数据摘要、逐标的收益与风险统计、数据质量报告 |
| 策略比较 | 在同一份输入数据上比较三种演示策略 |
| 项目说明 | 查看项目范围、分析口径和限制 |

## 公开策略示例

1. **趋势跟踪**
2. **均值回归**
3. **质量动量**：使用可选的 ROE 和 PB 字段

质量动量策略会保守处理缺失的基本面字段。如果输入数据没有必要字段，可能不会产生信号。

## 导入自己的数据

应用支持：

- CSV 文件；
- Excel 文件（`.xlsx` 和 `.xls`）；
- Parquet 文件。

必需字段：

```text
trade_date, open, high, low, close
```

应用会自动识别并标准化常见的中英文日期、开盘、最高、最低和收盘字段别名。多标的数据可以包含 `ts_code` 或 `symbol`；`volume`、`roe` 和 `pb` 为可选字段。

上传文件只在当前应用会话中分析，应用本身不会主动把上传内容保存到磁盘或加入仓库。涉及敏感数据时，请使用本地实例。

## 示例数据

`portfolio_app/sample_data/` 提供可重复生成的合成数据：

- `quant_demo_single_symbol.csv`：300 条数据，用于图表、信号和单标的回测；
- `quant_demo_multi_symbol.csv`：4 个合成标的，用于日期对齐和等权组合比较；
- `generate_demo_data.py`：使用 Python 标准库重新生成两份数据。

这些文件不是下载的证券行情，也不具有投资含义。

## 验证方式

安装开发依赖后运行：

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pip check
.\.venv\Scripts\python -m pytest
```

macOS 和 Linux 使用 `.venv/bin/python` 替换上面的解释器路径。GitHub Actions 会在 Ubuntu 和 Windows 上检查 Python 3.12 与 3.13。

## 分析口径

- 信号向后移动一行后参与收盘到收盘收益计算。
- 交易成本按持仓变化计入。
- 组合页面采用简化的动态等权收益合成方式。
- 示例不模拟下一交易日开盘成交、完整现金账本、容量、涨跌停或停牌约束。
- 年化使用 252 个交易日。
- 页面展示的类夏普指标为年化复合收益除以年化波动，假设无风险收益为 0；它不是标准的算术均值夏普比率。
- 应用不会下单，也不保证盈利。

## 公开边界与许可证

本仓库有意排除私人策略、重要研究参数、真实历史研究收益、模型权重、原始行情、账户信息、券商或 QMT 文件以及运行产物。仓库内策略和数据仅用于通用方法演示。

当前尚未选择开源许可证。在添加许可证之前，不应默认内容可以自由复用或再分发。发布和托管边界见 [`DEPLOYMENT.md`](DEPLOYMENT.md)。
