from __future__ import annotations

from pathlib import Path


_CONTENT = {
    "zh": {
        "language": "zh",
        "title": "Python 数据分析与研究工作台",
        "subtitle": "金融数据应用案例 · 数据处理 · 可视化 · 研究验证",
        "positioning": "以 Python 数据分析、研究工程和交互式工具开发为主线，量化研究作为真实应用场景。重点展示数据处理、信息时点控制、成本建模、策略比较和证据整理能力。",
        "capabilities": (
            "市场数据导入、字段标准化与质量检查",
            "信号构建、单股与组合回测、交易成本建模",
            "交互式行情图、指标配置、风险与归因分析",
            "把复杂研究整理为可复核、可展示的脱敏产物",
        ),
        "workflow": "从数据读取开始，经过质量检查、特征与信号生成、执行假设、回测和稳健性比较，最后形成带有验证状态和限制说明的研究产物。",
        "boundary": "展示层只保留公开摘要、聚合指标、验证状态、成本情景和研究限制；不展示策略核心代码、精确参数、模型权重、标的级持仓、账户信息、原始大数据或私人路径。",
        "projects_heading": "代表性研究项目",
        "artifacts_heading": "公开产物",
        "artifacts_intro": "以下文件用于说明数据结构、研究证据和可运行示例，不代表完整私有研究环境。",
        "metric_labels": {"models": "研究模型", "validated": "验证产物", "review": "需要复核"},
        "capability_columns": ("能力",),
        "comparison_note": "下方数字来自经过筛选的历史研究摘要，不是实盘收益承诺；不同资产、样本区间和执行假设不可直接组成收益排行榜。",
        "historical_note": "历史研究快照，不是实盘收益；模型2和模型6的未通过状态是研究结果的一部分。",
    },
    "en": {
        "language": "en",
        "title": "Python Data & Research Workbench",
        "subtitle": "Financial data applications · Data processing · Visualization · Research validation",
        "positioning": "This portfolio focuses on Python data analysis, research engineering, and interactive tooling, with quantitative research as the application domain. It demonstrates data processing, information-timing controls, cost modeling, strategy comparison, and evidence organization.",
        "capabilities": (
            "Market-data import, schema normalization, and quality checks",
            "Signal construction, single-asset and portfolio backtesting, and cost modeling",
            "Interactive price charts, indicator configuration, risk, and attribution analysis",
            "Turning complex research into reviewable, presentation-ready redacted artifacts",
        ),
        "workflow": "The workflow moves from data ingestion through quality checks, feature and signal construction, execution assumptions, backtesting, and robustness comparison, ending with research artifacts that state validation status and limitations.",
        "boundary": "The presentation layer keeps only public summaries, aggregate metrics, validation status, cost scenarios, and research limitations. It does not expose private strategy code, exact parameters, model weights, security-level holdings, account information, raw large datasets, or private paths.",
        "projects_heading": "Selected Research Projects",
        "artifacts_heading": "Public Artifacts",
        "artifacts_intro": "These files document data structures, research evidence, and runnable examples; they do not represent the complete private research environment.",
        "metric_labels": {"models": "Research Models", "validated": "Validated Artifacts", "review": "Review Required"},
        "capability_columns": ("Capability",),
        "comparison_note": "The figures below are curated historical research summaries, not live-return promises; assets, periods, and execution assumptions are not directly comparable.",
        "historical_note": "Historical research snapshots, not live returns; the review-required states of Models 2 and 6 are part of the research record.",
    },
}


_PUBLIC_ARTIFACTS = (
    ("研究证据说明 / Research evidence notes", "public_evidence/research_notes.md"),
    ("模型1摘要 / Model 1 summary", "public_evidence/model1_summary.csv"),
    ("模型2摘要 / Model 2 summary", "public_evidence/model2_summary.csv"),
    ("模型3摘要 / Model 3 summary", "public_evidence/model3_summary.csv"),
    ("模型3年度样本外 / Model 3 annual OOS", "public_evidence/model3_annual_oos.csv"),
    ("模型4摘要 / Model 4 summary", "public_evidence/model4_summary.csv"),
    ("模型5摘要 / Model 5 summary", "public_evidence/model5_summary.csv"),
    ("模型6摘要 / Model 6 summary", "public_evidence/model6_summary.csv"),
    ("模型7摘要 / Model 7 summary", "public_evidence/model7_summary.csv"),
    ("单标的示例数据 / Single-symbol demo data", "portfolio_app/sample_data/quant_demo_single_symbol.csv"),
    ("多标的示例数据 / Multi-symbol demo data", "portfolio_app/sample_data/quant_demo_multi_symbol.csv"),
)


def build_portfolio_content(language: str = "zh") -> dict[str, object]:
    if language not in _CONTENT:
        raise ValueError("language must be 'zh' or 'en'")
    return dict(_CONTENT[language])


def list_public_artifacts(project_root: str | Path) -> list[dict[str, object]]:
    root = Path(project_root).resolve()
    allowed_roots = tuple((root / directory).resolve() for directory in ("public_evidence", "portfolio_app/sample_data"))
    artifacts: list[dict[str, object]] = []
    for label, relative_path in _PUBLIC_ARTIFACTS:
        path = (root / relative_path).resolve()
        if not any(path == allowed_root or allowed_root in path.parents for allowed_root in allowed_roots):
            raise ValueError(f"artifact path outside public roots: {relative_path}")
        artifacts.append(
            {
                "label": label,
                "path": relative_path,
                "available": path.is_file(),
                "suffix": path.suffix.lower().lstrip(".") or "file",
                "size": path.stat().st_size if path.is_file() else 0,
            }
        )
    return artifacts
