"""Explicit company-action and asset-specific sellability rules."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .offline_ledger import LedgerState


class MarketRuleError(ValueError):
    """Raised when a company action or asset rule is invalid."""


@dataclass(frozen=True)
class AssetRule:
    asset_type: str
    lot_size: int
    t_plus_one: bool

    def __post_init__(self) -> None:
        if self.asset_type not in {"cn_stock", "hk_stock", "us_stock", "etf"}:
            raise MarketRuleError("asset_type is invalid")
        if isinstance(self.lot_size, bool) or not isinstance(self.lot_size, int) or self.lot_size <= 0:
            raise MarketRuleError("lot size must be positive")
        if not isinstance(self.t_plus_one, bool):
            raise MarketRuleError("t_plus_one must be boolean")


@dataclass(frozen=True)
class CompanyAction:
    action_id: str
    action_type: str
    symbol: str
    effective_date: str
    split_ratio: float | None = None
    cash_per_share: float | None = None

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.symbol.strip() or not self.effective_date.strip():
            raise MarketRuleError("company action identity is required")
        if self.action_type not in {"split", "cash_dividend"}:
            raise MarketRuleError("action_type is invalid")
        if self.action_type == "split" and (self.split_ratio is None or self.split_ratio <= 0):
            raise MarketRuleError("split_ratio must be positive")
        if self.action_type == "cash_dividend" and (self.cash_per_share is None or self.cash_per_share < 0):
            raise MarketRuleError("cash_per_share cannot be negative")


@dataclass(frozen=True)
class SellableQuantityResult:
    allowed: bool
    reason: str
    sellable_quantity: int


def apply_company_action(state: LedgerState, action: CompanyAction) -> tuple[LedgerState, dict[str, Any]]:
    if action.action_id in {str(row.get("action_id")) for row in state.ledger}:
        return state, {"status": "rejected", "reason": "duplicate_action", "action_id": action.action_id}
    current = int(state.positions.get(action.symbol, 0))
    positions = dict(state.positions)
    cash = float(state.cash)
    entry: dict[str, Any] = {
        "event_type": "company_action",
        "action_id": action.action_id,
        "action_type": action.action_type,
        "symbol": action.symbol,
        "effective_date": action.effective_date,
    }
    result: dict[str, Any] = {"status": "applied", "action_id": action.action_id, "cash_credit": 0.0}
    if action.action_type == "split":
        ratio = float(action.split_ratio)
        positions[action.symbol] = int(round(current * ratio))
        entry["split_ratio"] = ratio
        result["split_ratio"] = ratio
    else:
        credit = current * float(action.cash_per_share)
        cash += credit
        entry["cash_per_share"] = float(action.cash_per_share)
        entry["cash_credit"] = credit
        result["cash_credit"] = credit
    entry["position_after"] = int(positions.get(action.symbol, 0))
    entry["cash_after"] = cash
    return replace(state, cash=cash, positions=positions, ledger=(*state.ledger, entry)), result


def validate_sellable_quantity(
    *,
    total_quantity: int,
    acquired_today_quantity: int,
    requested_quantity: int,
    rule: AssetRule,
) -> SellableQuantityResult:
    values = (total_quantity, acquired_today_quantity, requested_quantity)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise MarketRuleError("quantities must be non-negative integers")
    if acquired_today_quantity > total_quantity:
        raise MarketRuleError("acquired quantity cannot exceed total quantity")
    sellable = total_quantity - acquired_today_quantity if rule.t_plus_one else total_quantity
    if requested_quantity % rule.lot_size:
        return SellableQuantityResult(False, "invalid_lot", sellable)
    if requested_quantity > sellable:
        reason = "insufficient_sellable_qty" if rule.t_plus_one and sellable < total_quantity else "insufficient_position"
        return SellableQuantityResult(False, reason, sellable)
    return SellableQuantityResult(True, "allowed", sellable)
