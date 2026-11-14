from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from portfolio_app.projects import RESEARCH_PROJECTS, get_project_detail
from portfolio_app.redacted_results import load_redacted_model7_results, load_redacted_results
from portfolio_app.research_artifacts import build_research_artifact_views


SHOWCASE_ARTIFACTS = {
    "model1": (("公开摘要", "public_evidence/model1_summary.csv"),),
    "model2": (("公开摘要", "public_evidence/model2_summary.csv"),),
    "model3": (("公开摘要", "public_evidence/model3_summary.csv"), ("年度样本外", "public_evidence/model3_annual_oos.csv")),
    "model4": (("公开摘要", "public_evidence/model4_summary.csv"),),
    "model5": (("公开摘要", "public_evidence/model5_summary.csv"),),
    "model6": (("公开摘要", "public_evidence/model6_summary.csv"),),
    "model7": (("公开摘要", "public_evidence/model7_summary.csv"),),
}

_PUBLIC_TEXT_REPLACEMENTS = {
    "目标仓位": "组合配置意图",
    "目标文件": "运行状态记录",
    "资金管理链路": "组合管理流程",
    "targets": "运行状态记录",
}


def _public_text(value: object) -> str:
    text = str(value)
    for source, replacement in _PUBLIC_TEXT_REPLACEMENTS.items():
        text = text.replace(source, replacement)
    return text


def _metric(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _artifacts(root: Path, model_id: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for label, relative_path in SHOWCASE_ARTIFACTS[model_id]:
        path = root / relative_path
        result.append(
            {
                "label": label,
                "path": relative_path,
                "available": path.is_file(),
                "suffix": path.suffix.lower().lstrip("."),
            }
        )
    return result


def _result_layers(root: Path, model_id: str, public_only: bool) -> list[dict[str, object]]:
    rows = load_redacted_model7_results(root) if model_id == "model7" else load_redacted_results(root)
    model_rows = [row for row in rows if row.get("model") == model_id]
    if not model_rows:
        return []
    layers: list[dict[str, object]] = []
    for row in model_rows:
        metrics = {
            "annual_return": _metric(row.get("annual_return")),
            "sharpe": _metric(row.get("sharpe")),
            "max_drawdown": _metric(row.get("max_drawdown")),
        }
        metrics = {key: value for key, value in metrics.items() if value is not None}
        layers.append(
            {
                "key": str(row.get("evidence_case", "summary")),
                "label": _public_text(row.get("status_label", "研究摘要")),
                "status": str(row.get("status", "unavailable")),
                "status_label": _public_text(row.get("status_label", "证据不可用")),
                "period": _public_text(row.get("period", "未提供")),
                "metrics": metrics,
                "cost_assumption": _public_text(row.get("cost_assumption", "未提供")),
                "limitations": _public_text(row.get("limitations", "")),
                "source_label": "curated research summary" if public_only else "private research workspace",
            }
        )
    return layers


def build_strategy_showcases(project_root: str | Path, public_only: bool = True) -> list[dict[str, Any]]:
    """Build the shared seven-project, disclosure-safe showcase contract."""
    root = Path(project_root)
    result_views = {view["model_id"]: view for view in build_research_artifact_views(root, public_only=public_only)}
    cards: list[dict[str, Any]] = []
    projects = sorted(
        (project for project in RESEARCH_PROJECTS if project.key.startswith("model")),
        key=lambda project: int(project.key.removeprefix("model")),
    )
    for project in projects:
        detail = get_project_detail(project.key)
        layers = _result_layers(root, project.key, public_only)
        artifacts = _artifacts(root, project.key) if public_only and layers else []
        status = "unavailable" if not layers else ("review_required" if project.key in {"model2", "model6"} else layers[0]["status"])
        status_label = "公开证据不可用" if not layers else ("研究门禁需复核" if status == "review_required" else layers[0]["status_label"])
        cards.append(
            {
                "model_id": project.key,
                "title": project.title,
                "category": project.category,
                "summary": _public_text(project.summary),
                "research_question": _public_text(detail.research_question),
                "work_completed": [_public_text(item) for item in detail.work_completed],
                "methods": [_public_text(item) for item in project.methods],
                "validation": [_public_text(item) for item in detail.validation],
                "limitations": [_public_text(item) for item in detail.limitations],
                "status": status,
                "status_label": status_label,
                "evidence_layers": layers,
                "metrics": layers[0]["metrics"] if layers else {},
                "artifacts": artifacts,
                "disclosure_mode": "public_redacted" if public_only else "private_redacted",
                "series_status": "not_in_reviewed_bundle",
                "result_view": result_views.get(project.key, {}),
            }
        )
    return cards
