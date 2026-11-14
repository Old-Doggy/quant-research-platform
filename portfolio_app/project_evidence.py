"""Public evidence navigation, without reconstructing unpublished time series."""
from __future__ import annotations

import math
from pathlib import Path
import re

from portfolio_app.project_dossiers import _EN_EVIDENCE, _ENGLISH, _STATUS
from portfolio_app.redacted_results import load_redacted_annual_oos


_EN_CASES = {
    "base": "Cost baseline", "cost_x2": "Twice baseline cost",
    "validation_summary": "Universe validation", "all_oos": "Walk-forward aggregate",
    "t_minus_1_next_open_cost_x2": "Prior-day signal, next-session audit at twice baseline cost",
    "base_wfo": "Walk-forward baseline", "stress_cost_x2": "Twice baseline cost",
    "cost_x1": "Locked candidate at baseline cost", "selection_validation": "Selection validation",
    "latest_local_backtest": "Latest local backtest", "runtime_state": "Historical runtime state",
}
_ZH_CASES = {"base": "基线成本", "cost_x2": "2 倍成本", "base_wfo": "样本外基线成本",
    "stress_cost_x2": "2 倍成本", "cost_x1": "锁定候选：基线成本"}


def _metrics(values):
    return {key: float(value) for key, value in values.items()
            if key in {"annual_return", "sharpe", "max_drawdown"}
            and value is not None and math.isfinite(float(value))}


def _period(text, *, runtime=False):
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if runtime:
        return (f"Snapshot published {dates[0]}; historical execution record ends {dates[1]}"
                if len(dates) >= 2 else "Historical state; dates not disclosed")
    return " to ".join(dates[:2]) if len(dates) >= 2 else "Backtest date range not disclosed in the source summary"


def build_project_evidence(root: str | Path, card: dict, *, language="zh") -> dict:
    if language not in {"zh", "en"}:
        raise ValueError("language must be 'zh' or 'en'")
    zh = language == "zh"
    model = card["model_id"]
    layers = []
    for source in card["evidence_layers"]:
        key = source["key"]
        runtime = key == "runtime_state" or source["status"] == "runtime_only"
        status = "runtime_only" if runtime else ("review_required" if model in {"model2", "model6"} else source["status"])
        label = _ZH_CASES.get(key, source["label"]) if zh else _EN_CASES.get(key, "Reviewed summary")
        cost = source["cost_assumption"]
        limits = source["limitations"]
        if not zh:
            cost = _EN_EVIDENCE[model][1]
            if key in {"cost_x2", "stress_cost_x2"}:
                cost = "Twice baseline commission and slippage" if model == "model1" else "Twice aggregate baseline cost; exact rates not disclosed"
            limits = " ".join(_ENGLISH[model]["limitations"])
            if model == "model6" and key == "cost_x2":
                limits += " Only three of five fixed folds are positive at twice baseline cost."
            if model == "model7":
                if runtime:
                    cost = "Not applicable"
                    limits = "Historical runtime metadata only; no performance evidence or claim of current executability. Security-level records remain private."
                elif key == "latest_local_backtest":
                    cost = "Cost multiplier and exact rates not separately disclosed"
                    limits = "Period checked against the corresponding daily record. Report cost is not matched to the walk-forward source row; this is not an independent formal audit."
                else:
                    cost += "; annual return at twice cost: 26.84%"
                    limits = "Selection validation differs from the latest local backtest. Publication date is not a backtest range; historical evidence is not live performance."
        layers.append({"key": key, "label": label, "status": status,
            "status_label": ("仅历史运行状态" if zh else "Historical runtime only") if runtime else _STATUS[language].get(status, "未披露" if zh else "Not reported"),
            "period": source["period"] if zh else _period(source["period"], runtime=runtime),
            "cost_assumption": cost, "limitations": limits,
            "source": "已筛选的公开研究摘要" if zh else "Curated public research summary",
            "metrics": {} if runtime else _metrics(source["metrics"])})
    keys = [row["key"] for row in layers]
    comparable = (model, tuple(keys)) in {
        ("model1", ("base", "cost_x2")), ("model5", ("base_wfo", "stress_cost_x2")),
        ("model6", ("cost_x1", "cost_x2")),
    } and len({row["period"] for row in card["evidence_layers"]}) == 1
    comparable = comparable and all(
        len(re.findall(r"\d{4}-\d{2}-\d{2}", source["period"])) == 2
        and len(row["metrics"]) == 3
        for source, row in zip(card["evidence_layers"], layers))
    annual = []
    if model == "model3" and layers:
        for row in load_redacted_annual_oos(root):
            if str(row["year"]) == "ALL_OOS" or row["model"] != "model3":
                continue
            incomplete = "不完整年度" in str(row["limitations"])
            annual.append({"year": str(row["year"]), "start": row["period_start"], "end": row["period_end"],
                "days": int(row["days"]), "metrics": _metrics(row), "incomplete": incomplete,
                "status": row["status"], "source": layers[0]["source"],
                "cost_assumption": row["cost_assumption"] if zh else "Formal audit; separate cost multiplier not disclosed",
                "limitations": row["limitations"] if zh else (
                    "Incomplete year through " + row["period_end"] if incomplete else
                    "Negative out-of-sample year; research and runtime configuration source dates differ" if str(row["year"]) == "2022" else
                    "Read with the complete audit and parameter stability evidence")})
    return {"layers": layers, "annual": annual, "cost_comparable": comparable,
        "curve": {"status": "not_in_reviewed_bundle", "points": []}}
