"""Bilingual, disclosure-safe dossiers for the seven research projects."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from portfolio_app.showcase import build_strategy_showcases
from portfolio_app.project_artifact_registry import list_project_artifacts


SECTION_IDS = ("data", "methods", "validation", "results", "limitations", "artifacts")


_ENGLISH = {
    "model1": {
        "question": "Can a cross-sectional machine-learning signal remain useful across holding periods, costs, and rolling out-of-sample tests?",
        "data": "Daily cross-sectional market data with engineered features, labels, and explicit point-in-time and execution assumptions.",
        "work": ["Built feature preparation, model training, cross-sectional ranking, top-k selection, and holding-period tests.", "Compared rolling validation, stability ranking, and holdout periods instead of selecting one best parameter.", "Added negative controls, signal perturbation, and transaction-cost stress cases."],
        "validation": "Formal cost stress evidence is available; sensitivity to execution cost and tail deterioration remains part of the conclusion.",
        "limitations": ["Performance is sensitive to execution costs and adverse tail conditions.", "Formal research parameters must remain separated from any future production configuration."],
    },
    "model2": {
        "question": "Can dividend, quality, and low-volatility factors form a stable defensive baseline across changing market conditions?",
        "data": "Daily equity data with dividend, quality, volatility, universe, and portfolio-exposure inputs.",
        "work": ["Built a dividend-low-volatility baseline and compared quality, valuation, drawdown, and trend enhancements.", "Separated universe construction, breadth, risk budget, industry limits, and price-adjustment conventions.", "Corrected universe, signal timing, and execution mismatches between research and implementation."],
        "validation": "A reviewed defensive baseline exists, but the current research gate remains review required.",
        "limitations": ["The candidate has not passed the final research gate.", "The main contribution is disciplined alignment and risk control, including the negative conclusion."],
    },
    "model3": {
        "question": "Can ETF trend, momentum, and risk-state signals support a stable cross-asset allocation rule?",
        "data": "Daily ETF or asset-class data with rolling windows, regime inputs, execution dates, and out-of-sample periods.",
        "work": ["Built asset switching, risk-state, target-allocation, and rebalance research paths.", "Ran rolling out-of-sample validation, parameter-neighborhood checks, negative controls, and bootstrap artifacts.", "Audited signal timing, execution windows, and the source date of generated configurations."],
        "validation": "Formal walk-forward evidence and annual out-of-sample records are available, including incomplete-year labeling.",
        "limitations": ["Configuration source dates and runtime dates require explicit audit interpretation.", "At least one annual out-of-sample period is negative and remains visible."],
    },
    "model4": {
        "question": "Can convertible-bond timing remain executable after liquidity, trading-rule, redemption, and execution-window constraints?",
        "data": "Daily convertible-bond market data with timing signals, liquidity fields, redemption risk, and execution assumptions.",
        "work": ["Connected convertible-bond prices, conversion-premium or redemption risk, and timing signals to an execution audit.", "Compared same-day proxy behavior with conservative next-session execution under cost and participation constraints.", "Recorded blocked trades, turnover, costs, and execution states instead of keeping only a return curve."],
        "validation": "A reviewed next-session execution audit and cost scenario are available.",
        "limitations": ["When intraday execution data is unavailable, the execution window uses a conservative proxy.", "Redemption-risk conclusions depend on the availability and timing of announcement fields."],
    },
    "model5": {
        "question": "Can earnings surprises and price confirmation form a tradable PEAD signal without crossing the information-availability boundary?",
        "data": "Daily equity and event data with announcement timing, earnings changes, price confirmation, and holding windows.",
        "work": ["Built event-signal, holding-window, and trailing-exit research paths.", "Made announcement timing, prior-day availability, and next-session execution explicit design inputs.", "Completed walk-forward, cost stress, negative-control, and bootstrap evidence outputs."],
        "validation": "Formal PEAD walk-forward evidence and cost scenarios are available.",
        "limitations": ["Incomplete announcement timestamps can create information-timing risk.", "Execution-time evidence must be interpreted separately from the walk-forward summary."],
    },
    "model6": {
        "question": "Can low-volatility and quality screening produce a reusable candidate across universes, rebalance frequencies, and T+1 constraints?",
        "data": "Daily equity data with low-volatility, quality, universe, rebalance, and execution-rule inputs.",
        "work": ["Built candidate screening, ablation, universe robustness, and locked-candidate validation paths.", "Included T+1, lot-size, limit, suspension, commission, and slippage assumptions.", "Separated research candidates from production candidates and recorded the gate result."],
        "validation": "Locked-candidate evidence exists, but the final research gate remains review required.",
        "limitations": ["The candidate has not passed the final research gate.", "Turnover and universe stability remain material risks beyond the headline metrics."],
    },
    "model7": {
        "question": "How can multiple stock pools be combined under position, industry, rebalance, and next-session execution constraints?",
        "data": "Multiple stock-pool outputs with portfolio constraints, execution dates, cost assumptions, and separate runtime-state records.",
        "work": ["Combined multiple pools with top-k selection, position and industry limits, duplicate handling, and residual cash.", "Generated configuration after the close and separated next-session execution from selection logic.", "Kept selection validation, latest local backtest, and runtime state as separate evidence layers."],
        "validation": "Three public evidence layers are available; runtime state is explicitly excluded from historical performance metrics.",
        "limitations": ["Selection validation, latest local backtest, and runtime state are different evidence products.", "Execution dates and source dates must match before a runtime record can be used."],
    },
}


_TITLES = {
    "zh": ("数据与时点", "方法与工程工作", "验证设计", "结果摘要", "失败、限制与状态", "公开产物"),
    "en": ("Data and timing", "Methods and engineering work", "Validation design", "Result summary", "Failures, limits, and status", "Public artifacts"),
}
_EN_TITLES = (
    "Machine-Learning Selection", "Dividend, Low-Volatility, and Quality Defense",
    "ETF Trend Allocation", "Convertible-Bond Timing and Execution Audit",
    "Earnings Events and PEAD", "Low-Volatility Portfolio Screening",
    "Multi-Pool Aggregation and Rebalancing",
)
_EN_CATEGORIES = ("Machine learning", "Factor research", "Asset allocation", "Convertible bonds",
    "Event-driven research", "Portfolio screening", "Portfolio construction")
_ZH_DATA = (
    "日频横截面行情、特征、标签与执行时点数据。",
    "日频股票、股息、质量、波动、股票池与组合暴露数据。",
    "日频 ETF/资产类别、滚动窗口、状态和样本外期间数据。",
    "日频可转债行情、流动性、赎回风险与执行约束数据。",
    "日频股票与财报事件、公告时点、盈利变化和持有期数据。",
    "日频股票、低波质量因子、股票池、调仓和交易规则数据。",
    "多个股票池结果、组合约束、执行日期和运行状态记录。",
)
_STATUS = {
    "zh": {"validated": "公开证据可用", "validated_with_limitations": "公开证据可用，存在限制", "review_required": "研究验收未通过", "unavailable": "公开证据不可用"},
    "en": {"validated": "Reviewed evidence available", "validated_with_limitations": "Evidence available with limitations", "review_required": "Review required", "unavailable": "Evidence unavailable"},
}

_EN_EVIDENCE = {
    "model1": ("Formal cost stress baseline", "Baseline aggregate cost"),
    "model2": ("Universe validation; research gate not passed", "Exact cost scenario not disclosed in the source summary"),
    "model3": ("Formal ETF walk-forward aggregate", "Separate transaction-cost column not disclosed in the source summary"),
    "model4": ("Prior-day signal, next-session execution audit", "Twice the aggregate baseline cost"),
    "model5": ("Formal PEAD walk-forward aggregate", "Formal audit baseline cost"),
    "model6": ("Locked candidate; final research gate not passed", "Baseline fees, tax, and slippage; exact settings not disclosed"),
    "model7": ("Selection validation summary", "Baseline includes transaction costs; exact rate not disclosed"),
}


def _result_items(card: dict[str, Any], language: str) -> list[str]:
    if not card["evidence_layers"]:
        return ["暂无经过审查的公开结果。" if language == "zh" else "No reviewed result is available in this copy."]
    labels = ("年化收益", "夏普", "最大回撤") if language == "zh" else ("Annual return", "Sharpe", "Maximum drawdown")
    values = []
    for key, label in zip(("annual_return", "sharpe", "max_drawdown"), labels):
        number = card["metrics"].get(key)
        if number is not None and math.isfinite(float(number)):
            value = f"{number:.2f}" if key == "sharpe" else f"{number:.2%}"
            values.append(f"{label}: {value}")
    layer = card["evidence_layers"][0]
    if language == "zh":
        context = [f"证据来源：{layer['label']}", f"期间：{layer['period']}", f"成本口径：{layer['cost_assumption']}",
            "以下为已审查摘要的历史快照，非实时表现；不同项目不可直接比较。"]
    else:
        label, cost = _EN_EVIDENCE[card["model_id"]]
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", layer["period"])
        period = " to ".join(dates[:2]) if len(dates) >= 2 else "Backtest date range not disclosed in the source summary"
        context = [f"Evidence source: {label}", f"Period: {period}", f"Cost assumption: {cost}",
            "Historical snapshot from the reviewed summary, not live performance. Results across projects are not directly comparable."]
    if card["model_id"] == "model7":
        context.append("此处仅为选型验证摘要；不代表最新本地回测或运行状态绩效。" if language == "zh" else "This headline covers selection validation only, not the latest local backtest or runtime-state performance.")
    return context + (values or ["没有可公开的绩效指标。" if language == "zh" else "No public performance metric is available."])


def build_project_dossiers(project_root: str | Path, *, language: str = "zh") -> list[dict[str, Any]]:
    """Read only the reviewed public bundle; never import a private strategy."""
    if language not in _TITLES:
        raise ValueError("language must be 'zh' or 'en'")
    records = []
    for index, card in enumerate(build_strategy_showcases(project_root, public_only=True)):
        english = _ENGLISH[card["model_id"]]
        zh = language == "zh"
        status = card["status"] if card["status"] in _STATUS[language] else "unavailable"
        title = card["title"] if zh else f"Model {index + 1}: {_EN_TITLES[index]}"
        question = card["research_question"] if zh else english["question"]
        work = card["work_completed"] if zh else english["work"]
        validation = card["validation"] if zh else [english["validation"]]
        limitations = card["limitations"] if zh else english["limitations"]
        data_summary = _ZH_DATA[index] if zh else english["data"]
        artifacts = [item for item in list_project_artifacts(project_root, card["model_id"], language=language)
                     if item["available"]] if card["evidence_layers"] else []
        missing = "暂无可下载的公开产物。" if zh else "No downloadable public artifact is available."
        if status == "unavailable":
            validation = ["本副本缺少公开验证证据，以下工作说明不代表验证已通过。" if zh else "Reviewed validation evidence is absent from this copy; the work description does not imply a passed validation."]
        items = (
            [data_summary], list(work), validation, _result_items(card, language),
            [*limitations, _STATUS[language][status]],
            [f"{item['label']} ({item['suffix'].upper()})" for item in artifacts] or [missing],
        )
        records.append({
            "model_id": card["model_id"], "title": title,
            "category": card["category"] if zh else _EN_CATEGORIES[index],
            "question": question, "data_summary": data_summary, "work_completed": list(work),
            "evidence_status": status, "status_label": _STATUS[language][status],
            "metrics": dict(card["metrics"]), "artifact_paths": [item["path"] for item in artifacts],
            "artifacts": artifacts, "limitations": list(limitations),
            "work_scope_note": "按已记录工作说明范围，不虚构工时、代码量或数据规模；不同项目的结果不可直接排名。" if zh else "Scope follows recorded work; hours, code volume, and dataset scale are not invented. Results across projects are not ranked.",
            "sections": [{"id": key, "title": label, "items": list(content)}
                for key, label, content in zip(SECTION_IDS, _TITLES[language], items)],
        })
    return records
