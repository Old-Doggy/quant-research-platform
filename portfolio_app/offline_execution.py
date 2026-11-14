"""Explicit offline execution semantics for research backtests.

This module consumes an explicit session table and produces auditable order
events. It has no broker, account, live submission, or external runtime hook.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Iterable, Mapping


class OfflineExecutionError(ValueError):
    """Raised when an offline execution contract is incomplete or invalid."""


class OrderStatus(StrEnum):
    PLANNED = "PLANNED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class MarketRuleProfile:
    asset_type: str
    lot_size: int
    supports_short: bool = False
    session_source: str = "explicit_session_table"

    def __post_init__(self) -> None:
        if self.asset_type not in {"cn_stock", "us_stock", "hk_stock", "etf"}:
            raise OfflineExecutionError("asset_type is invalid")
        if self.lot_size <= 0:
            raise OfflineExecutionError("lot_size must be positive")


@dataclass(frozen=True)
class ExecutionSpec:
    policy_id: str
    price_field: str
    fill_model: str
    commission_bps: float
    slippage_bps: float
    asset_type: str
    market_rule_profile: MarketRuleProfile | None = None
    engine_id: str = "offline_execution.v1"
    execution_mode: str = "offline_research_simulation"
    execution_lag_sessions: int = 1

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise OfflineExecutionError("policy_id is required")
        if self.price_field not in {"open", "close", "high", "low"}:
            raise OfflineExecutionError("price_field is invalid")
        if self.fill_model not in {"next_open", "next_close", "next_session", "same_bar"}:
            raise OfflineExecutionError("fill_model is invalid")
        if self.fill_model == "same_bar":
            raise OfflineExecutionError("same-bar execution is future information")
        if self.execution_mode != "offline_research_simulation":
            raise OfflineExecutionError("only offline research simulation is supported")
        if self.execution_lag_sessions < 1:
            raise OfflineExecutionError("execution lag must be at least one session")
        if self.commission_bps < 0 or self.slippage_bps < 0:
            raise OfflineExecutionError("execution costs cannot be negative")
        if self.market_rule_profile is None:
            object.__setattr__(self, "market_rule_profile", MarketRuleProfile(self.asset_type, 100 if self.asset_type == "cn_stock" else 1))


@dataclass(frozen=True)
class OfflineOrder:
    order_id: str
    signal_id: str
    strategy_id: str
    symbol: str
    side: str
    order_date: str
    effective_date: str | None
    quantity: int
    status: OrderStatus = OrderStatus.PLANNED
    filled_quantity: int = 0
    remaining_quantity: int | None = None
    reason: str | None = None
    event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise OfflineExecutionError("order side must be BUY or SELL")
        if self.quantity <= 0:
            raise OfflineExecutionError("order quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.quantity:
            raise OfflineExecutionError("filled quantity is invalid")
        remaining = self.quantity - self.filled_quantity if self.remaining_quantity is None else self.remaining_quantity
        if remaining != self.quantity - self.filled_quantity or remaining < 0:
            raise OfflineExecutionError("remaining quantity is inconsistent")
        object.__setattr__(self, "remaining_quantity", remaining)


@dataclass(frozen=True)
class TradabilityResult:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class CapacityAllocation:
    capacity_quantity: int
    orders: tuple[dict[str, Any], ...]


def _sessions(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(str(value) for value in values)
    if not result or tuple(sorted(set(result))) != result:
        raise OfflineExecutionError("sessions must be a non-empty sorted unique date table")
    return result


def _next_session(sessions: tuple[str, ...], decision: str, offset: int) -> str | None:
    try:
        index = sessions.index(decision)
    except ValueError as exc:
        raise OfflineExecutionError("decision date is not an explicit session") from exc
    target = index + offset
    return sessions[target] if target < len(sessions) else None


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineExecutionError(f"{label} is required")
    return value.strip()


def resolve_fill_price(bar: Mapping[str, Any], *, side: str, spec: ExecutionSpec) -> float:
    if side not in {"BUY", "SELL"}:
        raise OfflineExecutionError("side must be BUY or SELL")
    value = bar.get(spec.price_field)
    if value is None:
        raise OfflineExecutionError("fill price is missing")
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise OfflineExecutionError("fill price is invalid") from exc
    if price <= 0:
        raise OfflineExecutionError("fill price must be positive")
    return price


def calculate_post_entry_return(
    bars: Mapping[str, Mapping[str, Any]],
    *,
    sessions: Iterable[str],
    decision_date: str,
    spec: ExecutionSpec,
) -> float:
    session_table = _sessions(sessions)
    entry_date = _next_session(session_table, decision_date, spec.execution_lag_sessions)
    if entry_date is None:
        raise OfflineExecutionError("no future session for entry")
    exit_offset = 0 if spec.fill_model == "next_open" else 1
    exit_date = _next_session(session_table, entry_date, exit_offset)
    if exit_date is None:
        raise OfflineExecutionError("no future session for post-entry return")
    entry_price = resolve_fill_price(bars[entry_date], side="BUY", spec=spec)
    exit_field = "close"
    exit_price = bars[exit_date].get(exit_field)
    if exit_price is None or float(exit_price) <= 0:
        raise OfflineExecutionError("post-entry exit price is missing")
    return float(exit_price) / entry_price - 1.0


def validate_tradability(
    *,
    side: str,
    price: float | None,
    price_status: str,
    tradability: str,
) -> TradabilityResult:
    if side not in {"BUY", "SELL"}:
        raise OfflineExecutionError("side must be BUY or SELL")
    if price_status not in {"fresh", "stale", "missing"}:
        raise OfflineExecutionError("price_status is invalid")
    if tradability not in {"tradable", "limit_up", "limit_down", "suspended", "unknown"}:
        raise OfflineExecutionError("tradability is invalid")
    if price is None or price_status == "missing":
        return TradabilityResult(False, "missing_price")
    if price_status != "fresh":
        return TradabilityResult(False, "stale_price")
    if tradability == "unknown":
        return TradabilityResult(False, "unknown_tradability")
    if tradability == "suspended":
        return TradabilityResult(False, "suspended")
    if tradability == "limit_up" and side == "BUY":
        return TradabilityResult(False, "limit_up_buy_blocked")
    if tradability == "limit_down" and side == "SELL":
        return TradabilityResult(False, "limit_down_sell_blocked")
    return TradabilityResult(True, "allowed")


def allocate_session_capacity(
    *,
    orders: Iterable[Mapping[str, Any]],
    session_volume: int | None,
    participation_rate: float,
    lot_size: int,
    allow_partial_fill: bool,
) -> CapacityAllocation:
    if not isinstance(session_volume, int) or isinstance(session_volume, bool) or session_volume < 0:
        raise OfflineExecutionError("session volume is required and must be non-negative")
    if not isinstance(lot_size, int) or isinstance(lot_size, bool) or lot_size <= 0:
        raise OfflineExecutionError("lot_size must be positive")
    if not 0 <= float(participation_rate) <= 1:
        raise OfflineExecutionError("participation rate must be between zero and one")
    capacity = (int(session_volume * float(participation_rate)) // lot_size) * lot_size
    remaining = capacity
    rows: list[dict[str, Any]] = []
    for index, order in enumerate(orders):
        order_id = _text(order.get("order_id", f"order-{index}"), "order_id")
        quantity = order.get("quantity")
        row = {"order_id": order_id, "requested_quantity": quantity, "filled_quantity": 0, "remaining_quantity": quantity, "reason": None}
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            row["reason"] = "invalid_quantity"
        elif quantity % lot_size:
            row["reason"] = "invalid_lot"
        elif remaining <= 0:
            row["reason"] = "capacity_exhausted"
        elif quantity <= remaining:
            row["filled_quantity"] = quantity
            row["remaining_quantity"] = 0
            remaining -= quantity
        elif allow_partial_fill:
            fill = (remaining // lot_size) * lot_size
            row["filled_quantity"] = fill
            row["remaining_quantity"] = quantity - fill
            row["reason"] = "partial_capacity" if fill else "capacity_exhausted"
            remaining -= fill
        else:
            row["reason"] = "capacity_exhausted"
        rows.append(row)
    return CapacityAllocation(capacity, tuple(rows))


def build_execution_timeline(
    signals: Iterable[Mapping[str, Any]],
    *,
    sessions: Iterable[str],
    spec: ExecutionSpec,
) -> list[dict[str, Any]]:
    session_table = _sessions(sessions)
    timeline: list[dict[str, Any]] = []
    for signal in signals:
        signal_id = _text(signal.get("signal_id"), "signal_id")
        strategy_id = _text(signal.get("strategy_id"), "strategy_id")
        symbol = _text(signal.get("symbol"), "symbol")
        side = _text(signal.get("side"), "side").upper()
        decision_date = _text(signal.get("decision_date"), "decision_date")
        quantity = signal.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise OfflineExecutionError("signal quantity must be a positive integer")
        if decision_date not in session_table:
            raise OfflineExecutionError("decision date is not an explicit session")
        event_base = {"signal_id": signal_id, "strategy_id": strategy_id, "symbol": symbol, "side": side, "decision_date": decision_date, "quantity": quantity}
        timeline.append({"event_type": "SIGNAL", **event_base})
        effective_date = _next_session(session_table, decision_date, spec.execution_lag_sessions)
        if effective_date is None:
            timeline.append({"event_type": "ORDER_INTENT", "order_id": f"order-{signal_id}", "status": "EXPIRED", "reason": "no_future_session", "order_date": None, "effective_date": None, "fill_date": None, **event_base})
            continue
        timeline.append({"event_type": "ORDER_INTENT", "order_id": f"order-{signal_id}", "status": "PLANNED", "reason": None, "order_date": effective_date, "effective_date": effective_date, "fill_date": effective_date if spec.fill_model in {"next_open", "next_close", "next_session"} else None, **event_base})
    return timeline


def create_orders_from_signals(
    signals: Iterable[Mapping[str, Any]],
    *,
    sessions: Iterable[str],
    spec: ExecutionSpec,
) -> list[OfflineOrder]:
    timeline = build_execution_timeline(signals, sessions=sessions, spec=spec)
    return [
        OfflineOrder(
            order_id=str(item["order_id"]),
            signal_id=str(item["signal_id"]),
            strategy_id=str(item["strategy_id"]),
            symbol=str(item["symbol"]),
            side=str(item["side"]),
            order_date=str(item["order_date"]),
            effective_date=item["effective_date"],
            quantity=int(item["quantity"]),
            status=OrderStatus.PLANNED if item["status"] == "PLANNED" else OrderStatus.EXPIRED,
            reason=item.get("reason"),
            event_ids=(f"signal-{item['signal_id']}", f"order-{item['order_id']}"),
        )
        for item in timeline
        if item["event_type"] == "ORDER_INTENT" and item["status"] == "PLANNED"
    ]


def transition_order(order: OfflineOrder, action: str, *, quantity: int | None = None, reason: str | None = None) -> OfflineOrder:
    if action == "submit":
        if order.status is not OrderStatus.PLANNED:
            raise OfflineExecutionError("only planned orders can be submitted")
        return replace(order, status=OrderStatus.SUBMITTED, event_ids=(*order.event_ids, f"submit-{order.order_id}"))
    if action == "fill":
        if order.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
            raise OfflineExecutionError("only submitted orders can be filled")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0 or quantity > order.remaining_quantity:
            raise OfflineExecutionError("fill quantity exceeds remaining quantity")
        filled = order.filled_quantity + quantity
        return replace(order, status=OrderStatus.FILLED if filled == order.quantity else OrderStatus.PARTIALLY_FILLED, filled_quantity=filled, remaining_quantity=order.quantity - filled, event_ids=(*order.event_ids, f"fill-{order.order_id}-{filled}"))
    if action == "cancel":
        if order.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
            raise OfflineExecutionError("only active orders can be cancelled")
        return replace(order, status=OrderStatus.CANCELLED, reason=_text(reason, "cancel reason"), event_ids=(*order.event_ids, f"cancel-{order.order_id}"))
    raise OfflineExecutionError("unknown order transition")
