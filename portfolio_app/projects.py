from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchProject:
    key: str
    title: str
    category: str
    summary: str
    methods: tuple[str, ...]
    evidence: str
    portfolio_text: str


@dataclass(frozen=True)
class ResearchDetail:
    key: str
    research_question: str
    work_completed: tuple[str, ...]
    validation: tuple[str, ...]
    limitations: tuple[str, ...]
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceLayer:
    key: str
    label: str
    purpose: str
    source: str


RESEARCH_PROJECTS = (
    ResearchProject(
        key="model7",
        title="模型7：多股票池聚合调仓",
        category="组合构建与执行",
        summary="融合多个股票池，使用分层 Top-K、个股权重上限和行业暴露约束生成下一交易日目标仓位。",
        methods=("股票池融合", "组合约束", "下一开盘执行", "交易成本压力测试"),
        evidence="项目文档记录的验证摘要：年化 30.33%、夏普 1.79、最大回撤 -8.97%。",
        portfolio_text="构建多股票池聚合组合模型，完成候选池融合、个股与行业权重约束、下一开盘执行建模及成本压力测试，并将目标仓位接入统一资金管理链路。",
    ),
    ResearchProject(
        key="model2",
        title="模型2：红利低波质量防御",
        category="因子研究",
        summary="围绕股息、盈利质量、低波动和低换手构建防御型选股模型，并评估趋势增强是否真正改善结果。",
        methods=("股息因子", "低波动", "质量筛选", "稳健性比较"),
        evidence="研究交接文档将模型2定位为红利低波防御模型，并保留基础逻辑作为稳定基线。",
        portfolio_text="研究股息、盈利质量与低波动因子的组合效果，比较趋势和动量增强方案，最终保留经过成本与稳定性比较的防御型基线。",
    ),
    ResearchProject(
        key="model1",
        title="模型1：机器学习选股与持有期研究",
        category="机器学习量化",
        summary="围绕特征、Top-K 选择和持有期参数开展滚动验证，并将参数稳定性纳入候选筛选。",
        methods=("特征工程", "滚动验证", "参数稳定性", "样本外检验"),
        evidence="模型配置记录了固定平台稳健排名和多折样本外验证结果，强调避免恢复未经严格复验的参数。",
        portfolio_text="构建机器学习选股研究链路，完成特征处理、滚动样本外验证、参数稳定性评估和候选模型筛选，并保留可复核的研究产物。",
    ),
    ResearchProject(
        key="model3",
        title="模型3：ETF 趋势配置",
        category="资产配置",
        summary="研究 ETF 趋势、动量与风险状态，用于跨资产配置和防御性切换。",
        methods=("ETF 轮动", "趋势状态", "风险预算", "组合回测"),
        evidence="模型配置将模型3定义为 ETF/VAA 类策略，并纳入统一 state 产物和执行窗口。",
        portfolio_text="搭建 ETF 趋势配置研究框架，使用风险状态和动量信号进行资产切换，并验证组合回撤和执行时点的影响。",
    ),
    ResearchProject(
        key="model5",
        title="模型5：财报事件与 PEAD",
        category="事件驱动",
        summary="围绕财报公告和盈利惊喜研究事件信号，并采用保守的 T+1 时点口径避免公告时间穿越。",
        methods=("事件数据", "盈利惊喜", "T+1 执行", "信息时点控制"),
        evidence="模型配置明确要求基于已完成的前一日输入生成信号，公告时间不足时使用保守 T+1 口径。",
        portfolio_text="构建财报事件驱动策略，处理公告时点、盈利变化与价格确认信号，采用保守 T+1 执行规则控制信息可得性和回测穿越风险。",
    ),
    ResearchProject(
        key="model4",
        title="模型4：可转债择时与执行审计",
        category="可转债策略",
        summary="研究可转债行情、转股溢价和执行窗口，并把策略结果与成交语义、交易约束和审计流程连接起来。",
        methods=("可转债数据", "择时信号", "执行窗口", "成交语义审计"),
        evidence="模型配置将可转债策略与股票早盘模型分离，单独维护输入、执行窗口和状态产物。",
        portfolio_text="构建可转债择时与执行审计链路，分离行情信号、执行窗口和资金状态，并验证策略结果在交易约束下的可执行性。",
    ),
    ResearchProject(
        key="model6",
        title="模型6：低波动与组合筛选研究",
        category="组合筛选",
        summary="围绕低波动、质量和股票池稳定性开展消融实验与候选验证，并把研究结论与上线门槛分开记录。",
        methods=("低波因子", "消融实验", "股票池验证", "上线门禁"),
        evidence="模型6保留研究与验证产物，配置中明确记录其当前不作为生产默认模型的原因。",
        portfolio_text="开展低波动与质量组合筛选研究，完成消融实验、股票池鲁棒性检验和上线门禁审查，区分研究候选与生产候选。",
    ),
    ResearchProject(
        key="research_platform",
        title="Quant Research Workbench",
        category="研究基础设施",
        summary="把本地行情、策略信号、回测指标和交互式图表组织为可演示的个人研究平台。",
        methods=("Parquet 数据", "本地文件导入", "交互式图表", "回测指标"),
        evidence="支持本地日线 parquet、CSV、Excel 和 Parquet 文件导入，并输出净值、回撤、夏普和交易记录。",
        portfolio_text="开发量化研究工作台，统一本地行情浏览、策略信号生成、下一日执行回测、交易成本建模和交互式结果展示。",
    ),
)


RESEARCH_DETAILS = {
    "model1": ResearchDetail(
        key="model1",
        research_question="机器学习横截面信号在固定交易约束、不同持有期和成本压力下是否仍然具有稳定的选股价值？",
        work_completed=(
            "建立日频股票特征处理、模型训练、横截面排序、Top-K 选股和持有期回测链路。",
            "比较滚动 WFO、固定平台稳健排名和未来区间 holdout，避免把单次最优参数直接当成生产参数。",
            "加入负对照、信号扰动、代码置换和成本/滑点压力测试。",
        ),
        validation=(
            "正式成本压力测试基线：年化 19.90%、夏普 1.00、最大回撤 -21.49%，样本期 2016-08-25 至 2026-03-04。",
            "综合成本 2 倍情景：年化 12.54%、夏普 0.62；尾部额外恶化 30bp 时收益接近现金且夏普转负。",
        ),
        limitations=(
            "结果对执行成本和尾部成交恶化较敏感，不能只展示基线收益。",
            "正式研究参数与实盘可选参数需要通过固定平台和严格连续复验保持一致。",
        ),
        source_files=(
            "模型1/模型1_数据处理.py",
            "模型1/模型1_模型训练.py",
            "模型1/模型1_回测.py",
            "data/output/model1_formal_cost_stress_20260507/",
        ),
    ),
    "model2": ResearchDetail(
        key="model2",
        research_question="股息、低波动和低换手因子能否构成稳定防御基线，市场状态和风险预算又会怎样改变组合暴露？",
        work_completed=(
            "实现红利低波 baseline，并比较质量、估值、回撤和温和趋势增强，而不是预设增强一定有效。",
            "把股票池、全市场 breadth、风险预算、行业权重上限和复权/原始价格口径拆开处理。",
            "修正回测与实盘之间的 universe、预测分数 T+1 映射和执行口径错配问题。",
        ),
        validation=(
            "研究交接记录中的经典防御基线约为年化 7.1%、夏普 0.40、最大回撤 -19.6%。",
            "当前页面展示的股票池验证摘要为研究证据，不代表已通过生产门槛。",
        ),
        limitations=(
            "股票池验证未通过最终门槛，不能包装成生产成功模型。",
            "模型2的核心贡献更适合展示为口径对齐、风险暴露控制和负结果判断。",
        ),
        source_files=(
            "模型2/模型2_线性模型训练.py",
            "模型2/模型2_回测.py",
            "模型2/handoff_model2.md",
            "data/output/model2_pool_validation_smoke_decode/",
        ),
    ),
    "model3": ResearchDetail(
        key="model3",
        research_question="ETF 趋势、动量和风险状态能否形成跨资产配置规则，并在滚动样本外和参数邻域中保持稳定？",
        work_completed=(
            "构建 ETF/VAA 资产切换、风险状态、目标仓位和再平衡参数搜索链路。",
            "对正式参数网格执行滚动样本外验证，并输出年度 OOS、参数稳定性、负对照和 block bootstrap 产物。",
            "把 ETF 运行时的尾盘信号、执行窗口和配置来源交易日纳入审计。",
        ),
        validation=(
            "正式 WFO：年化 11.86%、夏普 0.88、最大回撤 -14.02%，样本期 2016-01-04 至 2026-04-30。",
            "正式网格包含 105 组参数，年度 OOS 结果允许直接检查不同市场阶段的表现。",
        ),
        limitations=(
            "研究生成配置与运行时配置存在来源交易日差异，页面必须保留这一审计限制。",
            "2022 年度 OOS 为负，不能只用全样本指标描述策略。",
        ),
        source_files=(
            "模型3/模型3_线性模型训练+回测.py",
            "模型3/模型3.py",
            "data/output/model3_vaa_formal_audit_full/",
            "configs/models/model3.json",
        ),
    ),
    "model4": ResearchDetail(
        key="model4",
        research_question="可转债择时信号在涨跌停、流动性、赎回风险和真实执行窗口下是否仍然可执行？",
        work_completed=(
            "将可转债行情、转股溢价/赎回风险和择时信号与独立执行审计链路连接。",
            "比较 legacy 同日收盘代理与 T-1 下一开盘执行，纳入手数、参与率、最小成交额、佣金和滑点约束。",
            "记录被交易约束拦截的买卖、交易次数和成本倍数，而不是只保存净值曲线。",
        ),
        validation=(
            "T-1 下一开盘、2 倍成本情景：年化 13.53%、夏普 0.79、最大回撤 -28.34%。",
            "正式审计覆盖 2024-01-02 至 2026-05-07，并输出交易、持仓和每日曲线。",
        ),
        limitations=(
            "历史缺少 14:50 tick/orderbook 时，下一尾盘执行使用次日收盘代理。",
            "赎回风险过滤依赖可得的公告日期和 as-of 字段，仍需继续核验数据时点。",
        ),
        source_files=(
            "模型4/模型4_数据处理.py",
            "模型4/模型4_回测.py",
            "experiments/model4_cb_formal_execution_audit.py",
            "data/output/model4_cb_execution_audit/",
        ),
    ),
    "model5": ResearchDetail(
        key="model5",
        research_question="财报公告后的盈利惊喜和价格确认能否转化为可交易的 PEAD 信号，同时避免公告时点穿越？",
        work_completed=(
            "围绕净利润同比、跳空、成交量爆发、最大持有期和追踪止损建立事件策略参数网格。",
            "将公告日期/时间、前一日信息可得性和 T+1 执行作为策略设计的一部分。",
            "完成正式 WFO、成本压力、负对照、bootstrap 和目标文件输出。",
        ),
        validation=(
            "正式 PEAD WFO 基线：年化 20.70%、夏普 1.33、最大回撤 -13.49%。",
            "2 倍成本情景仍为正，但独立执行时点审计仍需与研究 WFO 结果分开解读。",
        ),
        limitations=(
            "公告时间字段的完整性直接决定是否存在信息时点偏差。",
            "运行审计曾记录执行时点收益为负的风险信号，因此不能把 WFO 结果直接等同于已准备好实盘。",
        ),
        source_files=(
            "模型5/模型5_模型+回测.py",
            "模型5/模型5.py",
            "experiments/model5_pead_formal_audit.py",
            "data/output/model5_pead_formal_audit/20260507_215750/",
        ),
    ),
    "model6": ResearchDetail(
        key="model6",
        research_question="低波动与质量选股在不同股票池、调仓频率和 T+1 交易约束下，表现是否稳定？",
        work_completed=(
            "实现 Alpha-MoE/低波动组合筛选、股票池扫描、参数消融和锁定候选验证。",
            "采用真实 T+1 下一开盘、100 股一手、涨跌停/停牌、佣金、印花税和滑点口径。",
            "把研究候选与生产候选分开，并对固定折、成本倍数和近期区间单独审查。",
        ),
        validation=(
            "锁定候选成本 1 倍：年化 21.82%、夏普 1.10、最大回撤 -18.76%。",
            "固定折正收益为 5/5，但最终 research gate 仍为 false；2 倍成本年化降至 15.21%。",
        ),
        limitations=(
            "候选未通过最终研究门禁，当前不应改变生产配置。",
            "高换手和股票池稳定性是主要后续风险，而非单看基线收益。",
        ),
        source_files=(
            "模型6/数据处理.py",
            "模型6/调参+模型训练.py",
            "模型6/回测.py",
            "data/output/model6_locked_validation_raw/",
        ),
    ),
    "model7": ResearchDetail(
        key="model7",
        research_question="多个股票池如何在个股权重、行业暴露、调仓频率和下一开盘执行约束下合成为可管理的组合？",
        work_completed=(
            "融合四个模型2股票池，执行每腿 Top-K、单股权重上限、行业权重上限、重复股票合并和现金残余处理。",
            "收盘后生成目标仓位，下一交易日早盘执行，并对 skipped legs、有效腿覆盖率和目标质量做预检。",
            "模型脚本只发布目标仓位 state，真实资金分配、影子订单、风控和最终提交由资金管理系统负责。",
        ),
        validation=(
            "锁定小资金候选的选择验证摘要：年化 30.33%、夏普 1.79、最大回撤 -8.97%，2 倍成本年化 26.84%。",
            "当前 latest 本地回测报告另有 28.89% 年化、1.72 夏普、-9.25% 回撤的日曲线摘要，页面应把两者标记为不同产物，不能混写。",
        ),
        limitations=(
            "目标文件必须拥有精确 exec_date，旧日期 targets 不得用于当天执行。",
            "模型7的历史选择验证、latest 本地回测和运行时状态是不同层次的证据。",
        ),
        source_files=(
            "模型7/模型7_配置.py",
            "模型7/模型7_回测.py",
            "模型7/模型7.py",
            "模型7/模型7_交易日前与早盘Runbook.md",
            "模型7/output/latest/",
        ),
    ),
    "research_platform": ResearchDetail(
        key="research_platform",
        research_question="如何把本地行情、策略试验、回测指标和研究证据组织成一个面试时可以直接演示的工作台？",
        work_completed=(
            "统一 CSV、Excel、Parquet 和本地日线 parquet 的字段、日期、股票代码和价格口径。",
            "提供趋势、均值回归和质量动量示例策略，支持单股与等权组合的下一交易日执行回测。",
            "把历史研究证据、模型状态、成本压力和限制说明放进同一个可浏览界面。",
        ),
        validation=(
            "支持本地数据导入、信号图、净值曲线、回撤指标、交易成本和逐股票比较。",
            "应用不直接下单，研究平台与原有实盘链路保持隔离。",
        ),
        limitations=(
            "交互式回测用于探索和演示，不能替代各模型正式审计产物。",
            "当前组合回测是透明的等权合成，尚未等同于模型7的多股票池约束引擎。",
        ),
        source_files=(
            "portfolio_app/app.py",
            "portfolio_app/data.py",
            "portfolio_app/strategies.py",
            "portfolio_app/backtest.py",
            "portfolio_app/evidence.py",
        ),
    ),
}


EVIDENCE_LAYERS = {
    "model1": (
        EvidenceLayer("formal_audit", "正式成本压力测试", "用于确认基线、成本敏感性和尾部恶化。", "data/output/model1_formal_cost_stress_20260507/"),
    ),
    "model2": (
        EvidenceLayer("research_summary", "研究验证摘要", "用于展示防御型因子研究的当前验证状态。", "data/output/model2_pool_validation_smoke_decode/"),
    ),
    "model3": (
        EvidenceLayer("formal_audit", "正式 WFO 审计", "用于查看年度样本外、参数稳定性和负对照。", "data/output/model3_vaa_formal_audit_full/"),
    ),
    "model4": (
        EvidenceLayer("execution_audit", "执行窗口审计", "用于确认下一开盘执行、交易约束和成本情景。", "data/output/model4_cb_execution_audit/"),
    ),
    "model5": (
        EvidenceLayer("formal_audit", "PEAD 正式 WFO 审计", "用于确认事件时点、样本外和成本压力。", "data/output/model5_pead_formal_audit/20260507_215750/"),
    ),
    "model6": (
        EvidenceLayer("locked_validation", "锁定候选验证", "用于查看固定折、成本敏感性和 research gate。", "data/output/model6_locked_validation_raw/"),
    ),
    "model7": (
        EvidenceLayer("selection_validation", "选择验证摘要", "用于说明候选组合如何被选出及其成本压力。", "模型7/output/latest/manifest.json"),
        EvidenceLayer("latest_local_backtest", "latest 本地回测", "用于查看当前发布目录中的日曲线摘要。", "模型7/output/latest/MODEL7_LOCAL_BACKTEST_REPORT.md"),
        EvidenceLayer("runtime_state", "运行状态层", "用于说明目标仓位和执行日期，不与历史回测混写。", "模型7/output/latest/model7_targets.csv"),
    ),
    "research_platform": (
        EvidenceLayer("interactive_demo", "交互式演示", "用于现场展示数据导入、信号、回测和质量检查。", "portfolio_app/"),
    ),
}


def get_project(key: str) -> ResearchProject:
    for project in RESEARCH_PROJECTS:
        if project.key == key:
            return project
    raise KeyError(f"Unknown research project: {key}")


def get_project_detail(key: str) -> ResearchDetail:
    try:
        return RESEARCH_DETAILS[key]
    except KeyError as exc:
        raise KeyError(f"Unknown research detail: {key}") from exc


def get_evidence_layers(key: str) -> tuple[EvidenceLayer, ...]:
    try:
        return EVIDENCE_LAYERS[key]
    except KeyError as exc:
        raise KeyError(f"Unknown evidence layer: {key}") from exc
