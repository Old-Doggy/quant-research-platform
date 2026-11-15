"""Capability-aware catalog for runnable, draft, private and display-only assets."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .strategies import STRATEGIES
from .research_integrity import audit_research_input, IntegrityViolation
import pandas as pd
import numpy as np


def strategy_input_fields(strategy_key):
    """Raw dependencies, excluding indicators calculated by the strategy itself."""
    strategy = next((item for item in STRATEGIES if item.key == strategy_key), None)
    if strategy is None:
        raise ValueError('unknown strategy: ' + str(strategy_key))
    derived = {'ma20', 'ma60', 'rolling_std20', 'zscore20', 'ret60'}
    return tuple(field for field in strategy.required_features if field not in derived)


def audit_strategy_input(frame, strategy_key):
    fields = strategy_input_fields(strategy_key)
    missing = [field for field in fields if field not in frame
               or not np.isfinite(pd.to_numeric(frame[field], errors='coerce')).any()]
    if missing:
        raise IntegrityViolation('策略缺少有效字段：' + '、'.join(missing))
    return audit_research_input(frame, feature_fields=fields)


def strategy_input_status(frame, strategy_key):
    try:
        audit_strategy_input(frame, strategy_key)
    except IntegrityViolation as exc:
        return dict(can_run=False, message=str(exc),
                    action='请到数据中心补充所需字段及其可用时点，或选择价量策略。')
    return dict(can_run=True, message='', action='')


_EVIDENCE_STATUSES = {"validated", "validated_with_limitations", "review_required", "unavailable"}


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _record(strategy_id: str, display_name: str, status: str, capabilities: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "display_name": display_name,
        "status": status,
        "capabilities": capabilities,
        **extra,
    }


def build_strategy_catalog(
    *,
    factor_drafts: Sequence[Mapping[str, Any]] | None = None,
    private_evidence: Sequence[Mapping[str, Any]] | None = None,
    unavailable: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return a safe catalog; private records contribute only public metadata."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    def add(item: dict[str, Any]) -> None:
        if item["strategy_id"] in seen:
            raise ValueError(f"duplicate strategy_id: {item['strategy_id']}")
        seen.add(item["strategy_id"])
        result.append(item)

    for strategy in STRATEGIES:
        add(_record(strategy.key, strategy.name, "runnable", ["configure", "run", "view_evidence"], source="public_template", description=strategy.description))
    for draft in factor_drafts or ():
        source = draft.get("source") if isinstance(draft, Mapping) else None
        source = source if isinstance(source, Mapping) else {}
        draft_id = _text(source.get("factor_run_id"), "factor draft factor_run_id")
        add(_record(f"factor_draft:{draft_id}", "因子策略草案", "draft_requires_confirmation", ["review", "configure"], source="factor_research", backtest_status="not_run"))
    for evidence in private_evidence or ():
        model_id = _text(evidence.get("model_id"), "private evidence model_id")
        status = evidence.get("status")
        if status not in _EVIDENCE_STATUSES:
            raise ValueError("private evidence status is invalid")
        if status == "review_required":
            capabilities = ["view_evidence", "review"]
        elif status in {"validated", "validated_with_limitations"}:
            capabilities = ["view_evidence"]
        else:
            capabilities = ["view_summary"]
        safe_status = "review_required" if status == "review_required" else "read_only" if status != "unavailable" else "display_only"
        add(_record(model_id, _text(evidence.get("display_name"), "private evidence display_name"), safe_status, capabilities, source="private_evidence", disclosure_mode="private_local"))
    for item in unavailable or ():
        strategy_id = _text(item.get("strategy_id"), "unavailable strategy_id")
        add(_record(strategy_id, _text(item.get("display_name"), "unavailable display_name"), "display_only", ["view_summary"], source="unavailable"))
    return result
