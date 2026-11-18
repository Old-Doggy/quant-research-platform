# 项目结构与技术说明

## 目录

```text
quant-research-platform/
├── streamlit_app.py       # 七工作区启动入口
├── portfolio_app/         # 页面、数据与研究计算模块
│   ├── local_app.py       # 页面组装与工作区路由
│   ├── *_workspace*.py    # 看盘、数据、策略、组合等页面
│   ├── factor*.py         # 因子计算、分析与选股
│   ├── research*.py       # 研究任务、缓存、状态与清单
│   ├── offline*.py        # 模拟执行和市场约束
│   ├── portfolio_accounting.py # 组合现金、成交和净值账本
│   ├── providers/         # 行情与财务数据适配器
│   ├── project*.py        # 历史作品与结果展示
│   ├── chart_assets/      # 本地 K 线运行时和许可证
│   ├── research_charts.py # Plotly 图形和交互约定
│   ├── design_tokens.py   # 页面与图表共用的字体及语义色
│   └── sample_data/       # 合成样例及生成脚本
├── public_evidence/       # 授权公开的历史汇总和净值
├── scripts/               # 数据获取等命令行工具
├── tests/                 # 计算、数据与页面回归
├── docs/                  # 使用、数据、技术与计算说明
├── .github/workflows/     # Linux / Windows 持续集成
├── requirements.txt
└── LICENSE
```

`portfolio_app/app.py` 兼容旧启动命令，转到完整平台。包名保留以维持模块导入与归档兼容性。

## 运行路径

文件先经过字段标准化和质量检查，再登记数据版本。因子和策略读取明确选择的数据集，提交研究后记录配置、指纹、执行假设和结果。页面通过任务状态与缓存获取结果，图表只负责显示与交互。

Streamlit 负责页面与会话；pandas / NumPy 执行数据和研究计算；Plotly 绘制统计图；Lightweight Charts 绘制 K 线、指标与成交事件。图表资源随仓库提供，行情图无需额外 CDN。

净值计算使用完整研究数据；图表缩放、区间查看和展示采样不会反向修改已完成研究。策略、因子和组合的计算口径见 [methodology.md](methodology.md)。

## 本地状态

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `PORTFOLIO_MODE` | 启动入口设为 `local` | 完整单人本地工作区 |
| `PORTFOLIO_DATA_ROOT` | 项目 `data/` | 可选的本地历史行情根目录 |
| `PORTFOLIO_STATE_DIR` | 项目 `output/` | 快照、登记库、暂存输入、归档和任务记录 |
| `TUSHARE_TOKEN` | 无 | Tushare下载脚本及适配器权限检查 |

这个 GitHub 仓库公开的是源码，本地运行模式不等于开放互联网服务。应用允许读取使用者的本地数据目录，部署为多人服务时需要重新设计身份、路径权限、存储隔离和资源配额。

## 修改与测试

主要计算保持在纯 Python 模块，页面通过适配层调用。修改信号、执行时序、成本或收益指标时，应同步检查回归测试与计算文档。新增行情适配器放在 `portfolio_app/providers/`，独立工具放在 `scripts/`，不要把下载密钥写入页面、示例或配置模板。


## 新版的数据和研究链路

日线源通过适配器归一后写入原始/标准批次，快照固定主表、日历、范围与对照来源。SQLite仅作可重建索引；不能通过修改索引给缺失数据补身份。当前免费快照仍只有浏览能力。

研究后台使用持久任务日志和不可变结果包。清单固定输入、参数、执行和依赖版本。绘图可对长曲线取样，事件坐标按原始交易日取值，CSV 和归档使用完整记录。组合收益瀑布图使用原账本归因，净值与回撤分别映射到独立纵轴。

公开作品从 `public_evidence/` 加载授权汇总。现场运行的研究结果从本地结果库读取，导入或备份不会改变原结果身份。

运行、更新、迁移及回退见[运行与迁移](operations-v2.md)；完整交付边界以[状态报告](status-v2.md)为准。
