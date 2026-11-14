"""Fail-closed capability gate before an offline strategy run."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class PreflightStatus(StrEnum):
    READY = "READY"
    PROXY_ONLY = "PROXY_ONLY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class StrategyRunSpec:
    strategy_id: str
    dataset_id: str
    history_start: str
    history_end: str
    history_sessions: int
    buy_rule: Mapping[str, Any] | None
    sell_rule: Mapping[str, Any] | None
    execution_policy: Mapping[str, Any]
    commission_bps: float
    slippage_bps: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StrategyRunSpec":
        return cls(
            strategy_id=str(payload.get("strategy_id", "")), dataset_id=str(payload.get("dataset_id", "")),
            history_start=str(payload.get("history_start", "")), history_end=str(payload.get("history_end", "")),
            history_sessions=payload.get("history_sessions", 0), buy_rule=payload.get("buy_rule"), sell_rule=payload.get("sell_rule"),
            execution_policy=payload.get("execution_policy") if isinstance(payload.get("execution_policy"), Mapping) else {},
            commission_bps=payload.get("commission_bps", -1), slippage_bps=payload.get("slippage_bps", -1),
        )


@dataclass(frozen=True)
class PreflightReport:
    status: PreflightStatus
    can_run: bool
    trusted_cash_simulation: bool
    execution_label: str
    reasons: tuple[str, ...]


def preflight_strategy_run(spec: StrategyRunSpec, manifest: Mapping[str, Any]) -> PreflightReport:
    reasons: list[str] = []
    if not spec.strategy_id or not spec.dataset_id:
        reasons.append("strategy or dataset identity is missing")
    if spec.dataset_id != manifest.get("dataset_id"):
        reasons.append("dataset identity does not match")
    if not isinstance(spec.history_sessions, int) or spec.history_sessions <= 0:
        reasons.append("history sessions are insufficient")
    if not spec.buy_rule:
        reasons.append("buy_rule is missing")
    if not spec.sell_rule:
        reasons.append("sell_rule is missing")
    required_columns = set(manifest.get("required_columns", ())) if isinstance(manifest.get("required_columns"), list) else set()
    if not {"trade_date", "symbol", "open", "high", "low", "close"}.issubset(required_columns):
        reasons.append("required columns are incomplete")
    if manifest.get("quality_status") == "failed":
        reasons.append("dataset quality failed")
    if spec.commission_bps is None or not isinstance(spec.commission_bps, (int, float)) or spec.commission_bps < 0:
        reasons.append("commission is invalid")
    if spec.slippage_bps is None or not isinstance(spec.slippage_bps, (int, float)) or spec.slippage_bps < 0:
        reasons.append("slippage is invalid")
    policy = spec.execution_policy
    if policy.get("fill_model") not in {"next_open", "next_close"}:
        reasons.append("execution policy is unsupported")
    if policy.get("price_field") not in {"open", "close"}:
        reasons.append("raw execution price is required")
    if reasons:
        return PreflightReport(PreflightStatus.BLOCKED, False, False, "blocked", tuple(reasons))
    capabilities = set(manifest.get("capabilities", ()))
    trusted = (
        manifest.get("price_mode") == "raw"
        and manifest.get("corporate_actions") == "complete"
        and manifest.get("point_in_time") == "known"
        and manifest.get("quality_status") == "passed"
        and {"raw_price_share_ledger", "cash_backtest"}.issubset(capabilities)
    )
    if trusted:
        return PreflightReport(PreflightStatus.READY, True, True, "offline_cash_ledger_simulation", ())
    proxy_reasons = list(reasons)
    if manifest.get("price_mode") != "raw":
        proxy_reasons.append("raw price data is required for trusted cash simulation")
    if not {"raw_price_share_ledger", "cash_backtest"}.issubset(capabilities):
        proxy_reasons.append("dataset capability is proxy-only")
    return PreflightReport(PreflightStatus.PROXY_ONLY, True, False, "research_proxy_only", tuple(proxy_reasons))
