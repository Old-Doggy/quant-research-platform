from __future__ import annotations

import pytest

from portfolio_app.offline_execution import (
    OfflineExecutionError,
    ExecutionSpec,
    OrderStatus,
    build_execution_timeline,
    create_orders_from_signals,
    allocate_session_capacity,
    calculate_post_entry_return,
    resolve_fill_price,
    validate_tradability,
    transition_order,
)


def test_execution_spec_declares_offline_policy_and_market_rules() -> None:
    spec = ExecutionSpec(
        policy_id="daily-next-open",
        price_field="open",
        fill_model="next_open",
        commission_bps=5.0,
        slippage_bps=2.0,
        asset_type="cn_stock",
    )

    assert spec.engine_id == "offline_execution.v1"
    assert spec.execution_mode == "offline_research_simulation"
    assert spec.market_rule_profile.asset_type == "cn_stock"
    assert spec.market_rule_profile.lot_size == 100


def test_timeline_uses_explicit_sessions_and_excludes_weekend_gap() -> None:
    signals = [
        {
            "signal_id": "sig-1",
            "strategy_id": "factor-draft-1",
            "symbol": "600000.SH",
            "side": "BUY",
            "decision_date": "2024-01-05",
            "quantity": 300,
        }
    ]
    timeline = build_execution_timeline(
        signals,
        sessions=("2024-01-05", "2024-01-08", "2024-01-09"),
        spec=ExecutionSpec(
            policy_id="daily-next-open",
            price_field="open",
            fill_model="next_open",
            commission_bps=5.0,
            slippage_bps=2.0,
            asset_type="cn_stock",
        ),
    )

    assert timeline[0]["event_type"] == "SIGNAL"
    assert timeline[0]["decision_date"] == "2024-01-05"
    assert timeline[1]["event_type"] == "ORDER_INTENT"
    assert timeline[1]["order_date"] == "2024-01-08"
    assert timeline[1]["effective_date"] == "2024-01-08"
    assert timeline[1]["fill_date"] == "2024-01-08"
    assert timeline[1]["quantity"] == 300


def test_timeline_rejects_same_bar_future_information_and_missing_or_expired_sessions() -> None:
    signal = {
        "signal_id": "sig-1",
        "strategy_id": "draft",
        "symbol": "600000.SH",
        "side": "BUY",
        "decision_date": "2024-01-05",
        "quantity": 100,
    }
    with pytest.raises(OfflineExecutionError, match="same-bar"):
        ExecutionSpec(
            policy_id="same-bar",
            price_field="close",
            fill_model="same_bar",
            commission_bps=0.0,
            slippage_bps=0.0,
            asset_type="cn_stock",
        )

    missing = {**signal, "decision_date": "2024-01-06"}
    next_open = ExecutionSpec(
        policy_id="daily-next-open",
        price_field="open",
        fill_model="next_open",
        commission_bps=0.0,
        slippage_bps=0.0,
        asset_type="cn_stock",
    )
    with pytest.raises(OfflineExecutionError, match="session"):
        build_execution_timeline([missing], sessions=("2024-01-05", "2024-01-08"), spec=next_open)

    expired_spec = ExecutionSpec(
        policy_id="next-close",
        price_field="close",
        fill_model="next_close",
        commission_bps=0.0,
        slippage_bps=0.0,
        asset_type="cn_stock",
    )
    expired = build_execution_timeline([signal], sessions=("2024-01-05",), spec=expired_spec)
    assert expired[1]["status"] == "EXPIRED"
    assert expired[1]["reason"] == "no_future_session"


def test_order_lifecycle_requires_explicit_quantity_and_tracks_partial_fill_cancel() -> None:
    signal = {
        "signal_id": "sig-2",
        "strategy_id": "draft",
        "symbol": "600000.SH",
        "side": "BUY",
        "decision_date": "2024-01-05",
        "quantity": 300,
    }
    spec = ExecutionSpec(
        policy_id="daily-next-open",
        price_field="open",
        fill_model="next_open",
        commission_bps=0.0,
        slippage_bps=0.0,
        asset_type="cn_stock",
    )
    order = create_orders_from_signals([signal], sessions=("2024-01-05", "2024-01-08"), spec=spec)[0]
    assert order.status is OrderStatus.PLANNED
    assert order.quantity == 300
    assert order.remaining_quantity == 300
    submitted = transition_order(order, "submit")
    partial = transition_order(submitted, "fill", quantity=100)
    assert partial.status is OrderStatus.PARTIALLY_FILLED
    assert partial.filled_quantity == 100
    assert partial.remaining_quantity == 200
    cancelled = transition_order(partial, "cancel", reason="user_cancelled")
    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.remaining_quantity == 200
    assert cancelled.event_ids == tuple(dict.fromkeys(cancelled.event_ids))


def test_order_quantity_is_not_silently_assumed_or_coerced() -> None:
    signal = {
        "signal_id": "sig-3",
        "strategy_id": "draft",
        "symbol": "600000.SH",
        "side": "BUY",
        "decision_date": "2024-01-05",
    }
    spec = ExecutionSpec(
        policy_id="daily-next-open",
        price_field="open",
        fill_model="next_open",
        commission_bps=0.0,
        slippage_bps=0.0,
        asset_type="cn_stock",
    )
    with pytest.raises(OfflineExecutionError, match="quantity"):
        create_orders_from_signals([signal], sessions=("2024-01-05", "2024-01-08"), spec=spec)


def test_next_open_and_next_close_use_post_entry_prices_and_explicit_sessions() -> None:
    bars = {
        "2024-01-05": {"open": 100.0, "close": 100.0},
        "2024-01-08": {"open": 120.0, "close": 132.0},
        "2024-01-09": {"open": 125.0, "close": 144.0},
    }
    next_open = ExecutionSpec(
        policy_id="next-open",
        price_field="open",
        fill_model="next_open",
        commission_bps=0.0,
        slippage_bps=0.0,
        asset_type="cn_stock",
    )
    next_close = ExecutionSpec(
        policy_id="next-close",
        price_field="close",
        fill_model="next_close",
        commission_bps=0.0,
        slippage_bps=0.0,
        asset_type="cn_stock",
    )

    assert resolve_fill_price(bars["2024-01-08"], side="BUY", spec=next_open) == pytest.approx(120.0)
    assert calculate_post_entry_return(
        bars, sessions=("2024-01-05", "2024-01-08", "2024-01-09"), decision_date="2024-01-05", spec=next_open
    ) == pytest.approx(0.10)
    assert calculate_post_entry_return(
        bars, sessions=("2024-01-05", "2024-01-08", "2024-01-09"), decision_date="2024-01-05", spec=next_close
    ) == pytest.approx(144.0 / 132.0 - 1.0)


def test_tradability_is_directional_and_missing_price_is_not_silent_halt() -> None:
    assert validate_tradability(side="BUY", price=10.0, price_status="fresh", tradability="limit_up").allowed is False
    assert validate_tradability(side="SELL", price=10.0, price_status="fresh", tradability="limit_up").allowed is True
    assert validate_tradability(side="BUY", price=10.0, price_status="fresh", tradability="limit_down").allowed is True
    assert validate_tradability(side="SELL", price=10.0, price_status="fresh", tradability="limit_down").allowed is False
    missing = validate_tradability(side="BUY", price=None, price_status="missing", tradability="unknown")
    assert missing.allowed is False
    assert missing.reason == "missing_price"
    unknown = validate_tradability(side="BUY", price=10.0, price_status="fresh", tradability="unknown")
    assert unknown.allowed is False
    assert unknown.reason == "unknown_tradability"


def test_session_capacity_is_shared_and_allows_audited_partial_fills() -> None:
    result = allocate_session_capacity(
        orders=(
            {"order_id": "o1", "quantity": 300},
            {"order_id": "o2", "quantity": 100},
            {"order_id": "o3", "quantity": 80},
        ),
        session_volume=1_000,
        participation_rate=0.20,
        lot_size=100,
        allow_partial_fill=True,
    )

    assert result.capacity_quantity == 200
    rows = {row["order_id"]: row for row in result.orders}
    assert rows["o1"]["filled_quantity"] == 200
    assert rows["o1"]["remaining_quantity"] == 100
    assert rows["o1"]["reason"] == "partial_capacity"
    assert rows["o2"]["filled_quantity"] == 0
    assert rows["o2"]["reason"] == "capacity_exhausted"
    assert rows["o3"]["filled_quantity"] == 0
    assert rows["o3"]["reason"] == "invalid_lot"
    assert sum(row["filled_quantity"] for row in result.orders) == 200


def test_capacity_rejects_unknown_volume_and_invalid_lot_without_rounding() -> None:
    with pytest.raises(OfflineExecutionError, match="volume"):
        allocate_session_capacity(
            orders=({"order_id": "o1", "quantity": 100},),
            session_volume=None,
            participation_rate=0.1,
            lot_size=100,
            allow_partial_fill=True,
        )
    result = allocate_session_capacity(
        orders=({"order_id": "o1", "quantity": 80},),
        session_volume=1_000,
        participation_rate=0.2,
        lot_size=100,
        allow_partial_fill=True,
    )
    assert result.orders[0]["filled_quantity"] == 0
    assert result.orders[0]["reason"] == "invalid_lot"
