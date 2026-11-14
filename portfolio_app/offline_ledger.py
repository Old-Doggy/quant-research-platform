"""Cash and position ledger for the offline research execution engine."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


def _cost(
    notional: float,
    *,
    side: str,
    commission_bps: float,
    min_commission: float = 0.0,
    sell_stamp_duty_bps: float = 0.0,
) -> float:
    commission = max(float(min_commission), notional * float(commission_bps) / 10_000.0) if notional else 0.0
    stamp = notional * float(sell_stamp_duty_bps) / 10_000.0 if side == "SELL" else 0.0
    return commission + stamp


class LedgerError(ValueError):
    """Raised when a ledger input is invalid."""


@dataclass(frozen=True)
class FillEvent:
    fill_id: str
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    fill_date: str

    def __post_init__(self) -> None:
        if not self.fill_id.strip() or not self.order_id.strip() or not self.symbol.strip():
            raise LedgerError("fill identity is required")
        if self.side not in {"BUY", "SELL"}:
            raise LedgerError("fill side must be BUY or SELL")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise LedgerError("fill quantity must be positive")
        if self.price <= 0:
            raise LedgerError("fill price must be positive")
        if not self.fill_date.strip():
            raise LedgerError("fill date is required")


@dataclass(frozen=True)
class LedgerState:
    initial_cash: float
    cash: float | None = None
    positions: dict[str, int] = field(default_factory=dict)
    total_fees: float = 0.0
    ledger: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.initial_cash < 0:
            raise LedgerError("initial cash cannot be negative")
        if self.cash is None:
            object.__setattr__(self, "cash", float(self.initial_cash))
        if self.cash < 0 or self.total_fees < 0:
            raise LedgerError("cash and fees cannot be negative")
        if any(not isinstance(quantity, int) or quantity < 0 for quantity in self.positions.values()):
            raise LedgerError("positions must contain non-negative integer quantities")
        object.__setattr__(self, "positions", dict(self.positions))
        object.__setattr__(self, "ledger", tuple(dict(row) for row in self.ledger))


@dataclass(frozen=True)
class FillResult:
    accepted: bool
    reason: str
    fee: float = 0.0
    notional: float = 0.0


def apply_fill(
    state: LedgerState,
    fill: FillEvent,
    *,
    commission_bps: float,
    min_commission: float = 0.0,
    sell_stamp_duty_bps: float = 0.0,
) -> tuple[LedgerState, FillResult]:
    """Apply one fill atomically, returning the unchanged state on rejection."""
    if fill.fill_id in {str(row.get("fill_id")) for row in state.ledger}:
        return state, FillResult(False, "duplicate_fill")
    notional = float(fill.quantity * fill.price)
    fee = _cost(
        notional,
        side=fill.side,
        commission_bps=commission_bps,
        min_commission=min_commission,
        sell_stamp_duty_bps=sell_stamp_duty_bps,
    )
    positions = dict(state.positions)
    current = int(positions.get(fill.symbol, 0))
    if fill.side == "BUY":
        total = notional + fee
        if total > float(state.cash) + 1e-12:
            return state, FillResult(False, "insufficient_cash", fee=fee, notional=notional)
        cash_after = float(state.cash) - total
        positions[fill.symbol] = current + fill.quantity
    else:
        if fill.quantity > current:
            return state, FillResult(False, "insufficient_position", fee=fee, notional=notional)
        cash_after = float(state.cash) + notional - fee
        remaining = current - fill.quantity
        if remaining:
            positions[fill.symbol] = remaining
        else:
            positions.pop(fill.symbol, None)
    entry = {
        "fill_id": fill.fill_id,
        "order_id": fill.order_id,
        "symbol": fill.symbol,
        "side": fill.side,
        "quantity": fill.quantity,
        "price": fill.price,
        "fill_date": fill.fill_date,
        "notional": notional,
        "fee": fee,
        "cash_after": cash_after,
        "position_after": int(positions.get(fill.symbol, 0)),
    }
    next_state = replace(
        state,
        cash=cash_after,
        positions=positions,
        total_fees=float(state.total_fees) + fee,
        ledger=(*state.ledger, entry),
    )
    return next_state, FillResult(True, "accepted", fee=fee, notional=notional)
