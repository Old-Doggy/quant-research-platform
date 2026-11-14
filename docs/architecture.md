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
│   ├── offline*.py        # 模拟执行、市场约束与账本
│   ├── project*.py        # 历史作品与结果展示
│   ├── chart_assets/      # 本地图表资源和许可证
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
| `PORTFOLIO_STATE_DIR` | 项目 `output/` | 登记库、暂存输入、日志和任务记录 |
| `TUSHARE_TOKEN` | 无 | 仅供下载脚本使用 |

这个 GitHub 仓库公开的是源码，本地运行模式不等于开放互联网服务。应用允许读取使用者的本地数据目录，部署为多人服务时需要重新设计身份、路径权限、存储隔离和资源配额。

## 修改与测试

主要计算保持在纯 Python 模块，页面通过适配层调用。修改信号、执行时序、成本或收益指标时，应同步检查回归测试与计算文档。新增行情接口放在 `scripts/`，不要把下载密钥写入页面、示例或配置模板。
