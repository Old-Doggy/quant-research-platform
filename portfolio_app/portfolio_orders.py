"""Portfolio-level order planning for offline research simulation.

The coordinator deliberately stops at planned, simulated fills and remains a
local, offline research component with no external execution integration.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from .offline_execution import (
    ExecutionSpec,
    build_execution_timeline,
    validate_tradability,
)
from .offline_market_rules import AssetRule, validate_sellable_quantity
from .portfolio_recipe import PortfolioRecipe


class PortfolioOrderError(ValueError):
    """Raised when a portfolio order plan cannot pass its preflight gate."""


@dataclass(frozen=True)
class PortfolioPreflight:
    ok: bool
    issue_codes: tuple[str, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioOrderEvent:
    signal_id: str
    strategy_id: str
    symbol: str
    side: str
    effective_date: str | None
    requested_quantity: int
    filled_quantity: int
    remaining_quantity: int
    status: str
    reason_code: str | None
    reason: str | None
    price: float | None
    cash_before: float
    cash_after: float
    portfolio_event_key: str
    leg_event_key: str


@dataclass(frozen=True)
class PortfolioOrderPlan:
    events: tuple[PortfolioOrderEvent, ...]
    cash_after: float
    positions_after: dict[str, int]
    rejected_count: int
    filled_count: int


_REASON_TEXT = {
    "no_future_session": "没有可用的后续交易日",
    "missing_price": "缺少成交价格",
    "invalid_price": "成交价格无效",
    "stale_price": "成交价格已过期",
    "unknown_tradability": "可交易状态未知",
    "suspended": "标的处于停牌状态",
    "limit_up_buy_blocked": "涨停状态禁止买入",
    "limit_down_sell_blocked": "跌停状态禁止卖出",
    "invalid_lot": "数量不符合整手规则",
    "insufficient_sellable_qty": "可卖数量不足，受到 T+1 约束",
    "insufficient_position": "持仓数量不足",
    "partial_capacity": "容量限制导致部分成交",
    "capacity_exhausted": "会话容量不足",
    "missing_capacity_data": "缺少成交量容量数据",
    "invalid_capacity_data": "成交量容量数据无效",
    "partial_cash": "现金限制导致部分成交",
    "insufficient_cash": "共享现金不足",
}


def _reason_text(code: str | None) -> str | None:
    return None if code is None else _REASON_TEXT.get(code, code)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioOrderError(f"{label} is required")
    return value.strip()


def _signals_list(signals: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result = list(signals)
    if not result:
        raise PortfolioOrderError("portfolio signals are required")
    return result


def preflight_portfolio_order_config(
    signals: Iterable[Mapping[str, Any]],
    *,
    recipe: PortfolioRecipe,
    rules: Mapping[str, AssetRule],
) -> PortfolioPreflight:
    """Validate configuration conflicts before creating any simulated fill."""
    issue_codes: list[str] = []
    issues: list[str] = []
    seen: set[str] = set()
    for index, signal in enumerate(signals):
        if not isinstance(signal, Mapping):
            issue_codes.append("invalid_signal")
            issues.append(f"signal {index} is not a mapping")
            continue
        signal_id = signal.get("signal_id")
        if not isinstance(signal_id, str) or not signal_id.strip():
            issue_codes.append("invalid_signal_id")
        else:
            signal_id = signal_id.strip()
        if isinstance(signal_id, str) and signal_id.strip() and signal_id in seen:
            issue_codes.append("duplicate_signal_id")
            issues.append(f"duplicate signal_id: {signal_id}")
        elif isinstance(signal_id, str) and signal_id.strip():
            seen.add(signal_id)
        symbol = signal.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            issue_codes.append("invalid_symbol")
            continue
        symbol = symbol.strip()
        rule = rules.get(symbol)
        if rule is None:
            issue_codes.append("missing_asset_rule")
            issues.append(f"missing asset rule: {symbol}")
        elif rule.lot_size != recipe.lot_size:
            issue_codes.append("lot_size_conflict")
            issues.append(f"lot size conflict: {symbol}")
        quantity = signal.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            issue_codes.append("invalid_quantity")
        elif quantity % recipe.lot_size:
            issue_codes.append("invalid_lot")
            issues.append(f"quantity is not a multiple of recipe lot size: {symbol}")
        side = signal.get("side")
        if str(side).upper() not in {"BUY", "SELL"}:
            issue_codes.append("invalid_side")
            issues.append(f"invalid side: {side}")
    unique_codes = tuple(dict.fromkeys(issue_codes))
    return PortfolioPreflight(ok=not unique_codes, issue_codes=unique_codes, issues=tuple(issues))


def _nested_value(
    values: Mapping[str, Any] | None,
    symbol: str,
    date: str,
    default: Any,
) -> Any:
    if values is None or symbol not in values:
        return default
    value = values[symbol]
    if isinstance(value, Mapping):
        return value.get(date, default)
    return value


def _trade_price(price: float, *, side: str, spec: ExecutionSpec) -> float:
    slip = float(spec.slippage_bps) / 10_000.0
    value = price * (1.0 + slip if side == "BUY" else 1.0 - slip)
    if value <= 0 or not math.isfinite(value):
        raise PortfolioOrderError("effective trade price is invalid")
    return value


def _trade_value(price: float, quantity: int, *, side: str, spec: ExecutionSpec) -> float:
    value = _trade_price(price, side=side, spec=spec) * quantity
    return value * (1.0 + float(spec.commission_bps) / 10_000.0) if side == "BUY" else value * (1.0 - float(spec.commission_bps) / 10_000.0)


def _apply_simulated_fill(
    *,
    cash: float,
    positions: dict[str, int],
    candidate: Mapping[str, Any],
    filled: int,
    spec: ExecutionSpec,
) -> tuple[float, str | None]:
    trade_value = _trade_value(candidate["price"], filled, side=candidate["side"], spec=spec)
    if candidate["side"] == "BUY":
        if trade_value > cash + 1e-9:
            return cash, "insufficient_cash"
        cash -= trade_value
        positions[candidate["symbol"]] = positions.get(candidate["symbol"], 0) + filled
    else:
        cash += trade_value
        positions[candidate["symbol"]] = positions.get(candidate["symbol"], 0) - filled
    return cash, None


def plan_portfolio_orders(
    signals: Iterable[Mapping[str, Any]],
    *,
    sessions: Iterable[str],
    spec: ExecutionSpec,
    recipe: PortfolioRecipe,
    initial_cash: float,
    initial_positions: Mapping[str, int] | None = None,
    acquired_today: Mapping[str, int] | None = None,
    prices: Mapping[str, Any] | None = None,
    price_status: Mapping[str, Any] | None = None,
    tradability: Mapping[str, Any] | None = None,
    session_volumes: Mapping[str, Any] | None = None,
    participation_rate: float = 1.0,
    allow_partial_fill: bool = False,
    rules: Mapping[str, AssetRule],
) -> PortfolioOrderPlan:
    """Resolve one portfolio session into auditable simulated order events."""
    if not math.isfinite(float(initial_cash)) or initial_cash < 0:
        raise PortfolioOrderError("initial_cash must be finite and non-negative")
    for label, snapshot in (("position", initial_positions or {}), ("acquired", acquired_today or {})):
        for symbol, quantity in snapshot.items():
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise PortfolioOrderError(f"{label} quantity must be a non-negative integer")
    if initial_positions and acquired_today:
        for symbol, quantity in acquired_today.items():
            if quantity > int(initial_positions.get(symbol, 0)):
                raise PortfolioOrderError("acquired quantity cannot exceed position")
    signal_rows = _signals_list(signals)
    preflight = preflight_portfolio_order_config(signal_rows, recipe=recipe, rules=rules)
    if not preflight.ok:
        raise PortfolioOrderError(f"portfolio order preflight failed: {', '.join(preflight.issue_codes)}")

    timeline = build_execution_timeline(signal_rows, sessions=sessions, spec=spec)
    by_signal: dict[str, dict[str, Any]] = {
        str(item["signal_id"]): item
        for item in timeline
        if item["event_type"] == "ORDER_INTENT"
    }
    positions = {str(symbol): int(quantity) for symbol, quantity in (initial_positions or {}).items()}
    acquired = {str(symbol): int(quantity) for symbol, quantity in (acquired_today or {}).items()}
    cash = float(initial_cash)
    portfolio_key_by_date: dict[str, str] = {}
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for index, signal in enumerate(signal_rows):
        signal_id = _text(signal.get("signal_id"), "signal_id")
        item = by_signal[signal_id]
        symbol = _text(signal.get("symbol"), "symbol")
        side = _text(signal.get("side"), "side").upper()
        quantity = int(signal["quantity"])
        effective_date = item.get("effective_date")
        date = str(effective_date) if effective_date is not None else None
        date_key = date or "expired"
        portfolio_key_by_date.setdefault(date_key, f"portfolio:{recipe.recipe_id}:{date_key}")
        portfolio_key = portfolio_key_by_date[date_key]
        leg_key = f"{portfolio_key}:leg:{signal_id}"
        common = {
            "signal_id": signal_id,
            "strategy_id": str(signal["strategy_id"]),
            "symbol": symbol,
            "side": side,
            "effective_date": date,
            "requested_quantity": quantity,
            "portfolio_event_key": portfolio_key,
            "leg_event_key": leg_key,
            "signal_index": index,
        }
        if item["status"] != "PLANNED" or date is None:
            rejected.append({**common, "reason_code": "no_future_session", "reason": "没有可用的后续交易日"})
            continue
        raw_price = _nested_value(prices, symbol, date, None)
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            price = None
        status = str(_nested_value(price_status, symbol, date, "fresh" if price is not None else "missing"))
        tradability_value = str(_nested_value(tradability, symbol, date, "tradable"))
        tradable = validate_tradability(side=side, price=price, price_status=status, tradability=tradability_value)
        if not tradable.allowed:
            rejected.append({**common, "reason_code": tradable.reason, "reason": tradable.reason})
            continue
        if price is None or not math.isfinite(price) or price <= 0:
            rejected.append({**common, "reason_code": "invalid_price", "reason": _reason_text("invalid_price")})
            continue
        candidates.append({**common, "price": float(price), "order_index": index})

    # Capacity is shared by symbol and effective session and is consumed only
    # after a fill is affordable and otherwise valid.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        groups.setdefault((candidate["symbol"], candidate["effective_date"]), []).append(candidate)
    capacity_remaining: dict[tuple[str, str], int | None] = {}
    capacity_rejected: set[str] = set()
    first_effective_date = min(
        (str(item["effective_date"]) for item in by_signal.values() if item.get("status") == "PLANNED" and item.get("effective_date") is not None),
        default=None,
    )
    for (symbol, date) in groups:
        group_candidates = groups[(symbol, date)]
        if date == first_effective_date:
            eligible: list[dict[str, Any]] = []
            for candidate in group_candidates:
                if candidate["side"] != "SELL":
                    eligible.append(candidate)
                    continue
                sellable = validate_sellable_quantity(
                    total_quantity=positions.get(symbol, 0),
                    acquired_today_quantity=acquired.get(symbol, 0),
                    requested_quantity=candidate["requested_quantity"],
                    rule=rules[symbol],
                )
                if sellable.allowed:
                    eligible.append(candidate)
                else:
                    capacity_rejected.add(candidate["signal_id"])
                    rejected.append({
                        **candidate,
                        "reason_code": sellable.reason,
                        "reason": _reason_text(sellable.reason),
                    })
            groups[(symbol, date)] = eligible
            group_candidates = eligible
        if not group_candidates:
            capacity_remaining[(symbol, date)] = None
            continue
        if session_volumes is None:
            capacity_remaining[(symbol, date)] = None
            continue
        volume = _nested_value(session_volumes, symbol, date, None)
        if isinstance(volume, bool) or not isinstance(volume, int) or volume < 0:
            for candidate in group_candidates:
                capacity_rejected.add(candidate["signal_id"])
                rejected.append({
                    **candidate,
                    "reason_code": "missing_capacity_data" if volume is None else "invalid_capacity_data",
                    "reason": _reason_text("missing_capacity_data" if volume is None else "invalid_capacity_data"),
                })
            continue
        lot_size = rules[symbol].lot_size
        capacity_remaining[(symbol, date)] = (int(volume * float(participation_rate)) // lot_size) * lot_size

    accepted = sorted(
        [candidate for candidate in candidates if candidate["signal_id"] not in capacity_rejected],
        key=lambda candidate: (
            candidate["effective_date"],
            0 if candidate["side"] == "SELL" else 1,
            candidate["order_index"],
        ),
    )
    events: list[PortfolioOrderEvent] = []
    active_date: str | None = None
    acquired_for_date: dict[str, int] = dict(acquired)
    for candidate in accepted:
        if active_date != candidate["effective_date"]:
            active_date = candidate["effective_date"]
            if active_date != first_effective_date:
                acquired_for_date = {}
        if candidate["side"] == "SELL":
            sellable = validate_sellable_quantity(
                total_quantity=positions.get(candidate["symbol"], 0),
                acquired_today_quantity=acquired_for_date.get(candidate["symbol"], 0),
                requested_quantity=candidate["requested_quantity"],
                rule=rules[candidate["symbol"]],
            )
            if not sellable.allowed:
                before = cash
                events.append(
                    PortfolioOrderEvent(
                        signal_id=candidate["signal_id"],
                        strategy_id=candidate["strategy_id"],
                        symbol=candidate["symbol"],
                        side=candidate["side"],
                        effective_date=candidate["effective_date"],
                        requested_quantity=candidate["requested_quantity"],
                        filled_quantity=0,
                        remaining_quantity=candidate["requested_quantity"],
                        status="REJECTED",
                        reason_code=sellable.reason,
                        reason=_reason_text(sellable.reason),
                        price=candidate["price"],
                        cash_before=before,
                        cash_after=before,
                        portfolio_event_key=candidate["portfolio_event_key"],
                        leg_event_key=candidate["leg_event_key"],
                    )
                )
                continue
        requested = candidate["requested_quantity"]
        capacity_key = (candidate["symbol"], candidate["effective_date"])
        capacity = capacity_remaining[capacity_key]
        if capacity is not None and capacity <= 0:
            filled = 0
            capacity_reason = "capacity_exhausted"
        else:
            filled = requested if capacity is None else min(requested, capacity)
            lot_size = rules[candidate["symbol"]].lot_size
            if filled < requested and not allow_partial_fill:
                filled = 0
                capacity_reason = "capacity_exhausted"
            elif filled > 0:
                filled = (filled // lot_size) * lot_size
                capacity_reason = "partial_capacity" if filled < requested else None
            else:
                capacity_reason = "capacity_exhausted"
        before = cash
        reason_code: str | None = capacity_reason
        reason: str | None = _reason_text(capacity_reason)
        status = "REJECTED" if filled == 0 else ("PARTIALLY_FILLED" if filled < requested else "FILLED")
        if candidate["side"] == "BUY" and filled > 0 and allow_partial_fill:
            lot_size = rules[candidate["symbol"]].lot_size
            unit_cost = _trade_value(candidate["price"], 1, side="BUY", spec=spec)
            affordable = int(max(0.0, cash) / unit_cost) // lot_size * lot_size
            if affordable < filled:
                filled = affordable
                status = "REJECTED" if filled == 0 else "PARTIALLY_FILLED"
                capacity_reason = "partial_cash" if filled else "insufficient_cash"
                reason_code = capacity_reason
                reason = _reason_text(reason_code)
        if filled > 0:
            cash, cash_reason = _apply_simulated_fill(
                cash=cash,
                positions=positions,
                candidate=candidate,
                filled=filled,
                spec=spec,
            )
            if cash_reason is not None:
                filled = 0
                status = "REJECTED"
                reason_code = cash_reason
                reason = _reason_text(cash_reason)
        if filled > 0 and capacity is not None:
            capacity_remaining[capacity_key] = capacity - filled
        if filled > 0 and candidate["side"] == "BUY":
            acquired_for_date[candidate["symbol"]] = acquired_for_date.get(candidate["symbol"], 0) + filled
        remaining = requested - filled
        if status == "PARTIALLY_FILLED" and reason_code is None:
            reason_code = "partial_capacity"
            reason = _reason_text(reason_code)
        if status == "REJECTED" and reason_code is None:
            reason_code = "capacity_exhausted"
            reason = _reason_text(reason_code)
        events.append(
            PortfolioOrderEvent(
                signal_id=candidate["signal_id"],
                strategy_id=candidate["strategy_id"],
                symbol=candidate["symbol"],
                side=candidate["side"],
                effective_date=candidate["effective_date"],
                requested_quantity=requested,
                filled_quantity=filled,
                remaining_quantity=remaining,
                status=status,
                reason_code=reason_code,
                reason=reason,
                price=candidate["price"],
                cash_before=before,
                cash_after=cash,
                portfolio_event_key=candidate["portfolio_event_key"],
                leg_event_key=candidate["leg_event_key"],
            )
        )

    # Rejected legs are retained after executable session events.  Their
    # original order is preserved so diagnostics map directly to input signals.
    for item in sorted(rejected, key=lambda row: row["signal_index"]):
        events.append(
            PortfolioOrderEvent(
                signal_id=item["signal_id"],
                strategy_id=item["strategy_id"],
                symbol=item["symbol"],
                side=item["side"],
                effective_date=item["effective_date"],
                requested_quantity=item["requested_quantity"],
                filled_quantity=0,
                remaining_quantity=item["requested_quantity"],
                status="REJECTED",
                reason_code=item["reason_code"],
                reason=_reason_text(item["reason_code"]) or item["reason"],
                price=None,
                cash_before=cash,
                cash_after=cash,
                portfolio_event_key=item["portfolio_event_key"],
                leg_event_key=item["leg_event_key"],
            )
        )
    ordered_events = tuple(
        sorted(
            events,
            key=lambda event: (
                event.effective_date or "9999-99-99",
                1 if event.status == "REJECTED" else 0,
            ),
        )
    )
    return PortfolioOrderPlan(
        events=ordered_events,
        cash_after=cash,
        # Keep zero positions for symbols that were held and then sold.  This
        # distinguishes a cleared leg from a symbol that never participated.
        positions_after=dict(positions),
        rejected_count=sum(event.status == "REJECTED" for event in ordered_events),
        filled_count=sum(event.filled_quantity > 0 for event in ordered_events),
    )
