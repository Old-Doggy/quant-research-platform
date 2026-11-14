"""Convert a completed factor research run into an explicit strategy draft."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FactorStrategyDraftError(ValueError):
    """Raised when a factor run cannot safely become a strategy draft."""


_DIRECTIONS = {"long", "short", "long_short"}
_REBALANCE_FREQUENCIES = {"daily", "weekly", "monthly"}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FactorStrategyDraftError(f"{label} is required")
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FactorStrategyDraftError(f"source is missing {label}")
    return value.strip()


def build_factor_strategy_draft(
    factor_run: Mapping[str, Any],
    *,
    top_k: int = 10,
    direction: str = "long",
    rebalance_frequency: str = "weekly",
) -> dict[str, Any]:
    """Build a reviewable factor-ranking draft without implying execution.

    The returned object deliberately contains no orders, fills, NAV or backtest
    metrics. Execution assumptions must be selected again by a later stage.
    """
    run = _mapping(factor_run, "factor run")
    if run.get("status") != "succeeded":
        raise FactorStrategyDraftError("only a successful factor run can become a strategy draft")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise FactorStrategyDraftError("top_k must be a positive integer")
    if direction not in _DIRECTIONS:
        raise FactorStrategyDraftError("direction is invalid")
    if rebalance_frequency not in _REBALANCE_FREQUENCIES:
        raise FactorStrategyDraftError("rebalance frequency is invalid")

    config = _mapping(run.get("config"), "source config")
    contract = _mapping(run.get("result_contract"), "source result_contract")
    source = {
        "factor_run_id": _required_text(run.get("run_id"), "factor_run_id"),
        "factor_result_id": _required_text(contract.get("result_id"), "factor_result_id"),
        "factor_id": _required_text(config.get("factor_id"), "factor_id"),
        "dataset_id": _required_text(config.get("dataset_id"), "dataset_id"),
        "data_version": _required_text(config.get("data_version"), "data_version"),
        "label_id": _required_text(config.get("label_id"), "label_id"),
    }
    return {
        "schema_version": "factor-strategy-draft.v1",
        "status": "draft",
        "strategy_type": "factor_rank",
        "selection": {
            "top_k": top_k,
            "direction": direction,
            "rebalance_frequency": rebalance_frequency,
        },
        "source": source,
        "execution_policy": {
            "status": "requires_confirmation",
            "policy_id": None,
            "message": "执行价格、成本、可交易性和成交时点需要在策略阶段重新确认。",
        },
        "backtest": {"status": "not_run", "result": None},
    }
