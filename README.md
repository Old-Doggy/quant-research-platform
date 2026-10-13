# Python 数据分析与研究工作台

以金融日线数据为案例的Python作品：文件导入、字段标准化、数据质量检查、通用示例策略、成本回测、组合分析和交互图表。展示数据分析、研究验证和工具开发能力，不宣称真实交易业绩。

**本仓库不包含私人策略、重要研究参数、真实历史研究收益、模型权重、原始行情、账户或交易运行产物。** 三种策略仅为通用方法演示。示例数据完全合成，不需要券商、行情接口或密钥。

## 快速开始

Python 3.12为基准运行版本。克隆或解压后进入本仓库根目录，安装需要能够访问Python包源。

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run streamlit_app.py
```

macOS / Linux：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run streamlit_app.py
```

无需激活环境。打开终端显示的本地地址，默认是 `http://localhost:8501`。首次启动直接显示带合成数据的分析界面。端口占用时增加 `--server.port 8517`。

## 页面

| 页面 | 内容 |
| --- | --- |
| Quant Dashboard | K线与信号、策略与成本参数、单标的/等权组合、净值与回撤 |
| 数据分析 | 数据摘要、逐标的收益与风险、标准化后的质量报告 |
| 策略比较 | 同一输入下比较三种通用演示策略 |
| 项目说明 | 模块范围、分析口径与限制 |

三种策略为趋势跟踪、均值回归、质量动量。质量动量需要ROE/PB；缺失时保守处理，可能没有信号。公开页面不展示私人模型编号、收益摘要或下载链接。

## 导入与示例

支持CSV、Excel（`.xlsx`/`.xls`）与Parquet。必需字段为 `trade_date, open, high, low, close`；支持日期、开盘、最高、最低、收盘等常见别名。多标的数据包含 `ts_code` 或 `symbol`，成交量、ROE、PB可选。

`portfolio_app/sample_data/`包含单标的300条日线和4个合成标的。生成器可重复生成样例；样例收益没有投资含义。默认不访问外部数据源。

导入文件在当前会话中分析，应用不主动将上传文件保存到磁盘或加入仓库。不要把私人数据加入Git。公开服务器上传不等同于本机处理，敏感数据只在自己的本地实例分析。

## 验证

在同一环境安装测试依赖，再运行全部公开测试，无需私人数据：

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

macOS/Linux使用 `.venv/bin/python`。测试覆盖示例数据、CSV/Excel/Parquet导入、三种策略、组合、四个页面及公开边界。`.github/workflows/tests.yml`配置了Python 3.12/3.13在Windows/Linux的检查；远程CI是否通过以推送后的结果为准。

## 口径与限制

信号滞后一行参与收盘到收盘收益计算，不模拟下一开盘成交；成本按持仓变化计入。组合是简化动态等权收益合成，未实现完整现金账户、权重再平衡成本、容量、涨跌停或停牌约束。

年化按252个交易日；页面夏普为年化复合收益除以年化波动（无风险取0），不是标准算术均值夏普。质量检查针对标准化后的数据，已删除的重复行和无效日期不计入异常数。

应用不下单，不保证盈利。当前无线上Demo，项目许可证待所有者确认，未预设开源授权。部署范围见 `DEPLOYMENT.md`。`PUBLIC_MANIFEST.json`记录初始导出文件校验值，后续编辑需要重新审查和生成。
