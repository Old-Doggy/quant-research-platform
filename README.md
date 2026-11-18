# 量化研究与可视化平台

用图表完成从行情观察、因子分析到策略回测和组合研究的工作流。七个工作区共用一套数据与研究记录，参数、结果和图形可以连起来查看。

Python · Streamlit · Plotly · Lightweight Charts

开发分支：精简范围工程验收已完成，连续交易日观察中。[当前状态](docs/status-v2.md) · [验收记录](docs/acceptance-v2.md)

![行情与研究](docs/images/watch.png)

## 能做什么

| 工作区 | 用途 |
| --- | --- |
| 看盘 | 日、周、月 K 线，技术指标、成交量与研究事件联动 |
| 因子 | 因子分布、横截面 Rank IC、分组收益与稳定性分析 |
| 策略 | 配置信号、比较参数、查看成本与样本外验证 |
| 组合 | 组合权重、现金、调仓、成交记录与收益贡献 |
| 数据 | 导入文件、检查质量、登记版本，再进入研究 |
| 实验 | 查看研究记录、比较运行结果、下载归档 |
| 作品 | 按模型浏览研究方法、验证设计与历史净值 |

## 运行

需要 Python 3.12 或 3.13。首次使用无需行情接口或密钥，内置合成数据可运行完整研究流程。

```bash
git clone https://github.com/Old-Doggy/quant-research-platform.git
cd quant-research-platform
python -m venv .venv
```

Windows 激活环境：`.venv\Scripts\activate`；macOS / Linux：`source .venv/bin/activate`。

```bash
python -m pip install --upgrade "pip>=26.2"
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

打开终端给出的本地地址，默认是 `http://127.0.0.1:8501`。从“数据”导入自己的 CSV、Excel 或 Parquet，也可在“看盘”切换行情来源。

![历史模型净值与回撤](docs/images/models.png)

## 数据

仓库附带合成样例及作者授权公开的历史研究汇总。真实行情可从有权使用的数据服务商获取后导入。数据中心提供免费日线更新和财务三表，仓库另提供 Tushare 下载脚本。免费日线更新限最多 20 只沪深股票，单次一年。已有跨源核对范围见[接口记录](docs/provider-coverage.md)。

[数据获取与字段说明](docs/data.md) · [使用指南](docs/usage.md) · [研究计算口径](docs/methodology.md) · [更新与运行](docs/operations-v2.md) · [备份恢复](docs/recovery-runbook.md)

缺公司行为、交易状态或规则证据的免费快照用于看盘和筛选，相关真实回测保持关闭。没有接口凭据时仍可使用合成示例完成研究、保存和复算。

“作品”中的 11 条净值曲线来自既有历史回测，保留原样本区间与成本情景。模型 2、6 的未通过状态也保留在结果中。这些历史汇总不等于当前行情重跑或实盘收益。

## 开发

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

[项目结构与技术说明](docs/architecture.md) · [测试与版本记录](docs/verification.md) · [第三方资源](docs/third-party.md)

应用默认在本机运行，文件导入和本地目录读取面向单人研究使用。互联网部署需要另外配置访问控制与数据隔离。

## 许可证

代码与作者公开的研究汇总采用 [MIT](LICENSE) 许可证。Lightweight Charts 保留 Apache-2.0 许可证和 TradingView 署名。外部行情数据的使用与再分发遵循各数据提供方的条款。
