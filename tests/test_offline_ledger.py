from __future__ import annotations

import pytest

from portfolio_app.offline_ledger import (
    FillEvent,
    LedgerState,
    apply_fill,
)


def test_buy_fill_updates_cash_position_fee_and_auditable_ledger() -> None:
    state = LedgerState(initial_cash=10_000.0)
    next_state, result = apply_fill(
        state,
        FillEvent(
            fill_id="fill-1",
            order_id="order-1",
            symbol="600000.SH",
            side="BUY",
            quantity=100,
            price=20.0,
            fill_date="2024-01-08",
        ),
        commission_bps=5.0,
        min_commission=5.0,
    )

    assert result.accepted is True
    assert result.reason == "accepted"
    assert next_state.cash == pytest.approx(7_995.0)
    assert next_state.positions["600000.SH"] == 100
    assert next_state.total_fees == pytest.approx(5.0)
    assert next_state.ledger[-1]["notional"] == pytest.approx(2_000.0)
    assert next_state.ledger[-1]["cash_after"] == pytest.approx(next_state.cash)


def test_sell_fill_updates_cash_position_and_sell_cost() -> None:
    state = LedgerState(initial_cash=10_000.0, positions={"600000.SH": 100})
    next_state, result = apply_fill(
        state,
        FillEvent(
            fill_id="fill-2",
            order_id="order-2",
            symbol="600000.SH",
            side="SELL",
            quantity=40,
            price=25.0,
            fill_date="2024-01-09",
        ),
        commission_bps=5.0,
        min_commission=5.0,
        sell_stamp_duty_bps=10.0,
    )

    assert result.accepted is True
    assert next_state.cash == pytest.approx(10_000.0 + 1_000.0 - 5.0 - 1.0)
    assert next_state.positions["600000.SH"] == 60
    assert next_state.total_fees == pytest.approx(6.0)


def test_rejected_fills_do_not_change_cash_positions_or_ledger() -> None:
    state = LedgerState(initial_cash=1_000.0, positions={"600000.SH": 20})
    expensive = FillEvent("fill-3", "order-3", "600000.SH", "BUY", 100, 20.0, "2024-01-08")
    after_buy, buy_result = apply_fill(state, expensive, commission_bps=5.0, min_commission=5.0)
    assert buy_result.accepted is False
    assert buy_result.reason == "insufficient_cash"
    assert after_buy == state

    excessive_sell = FillEvent("fill-4", "order-4", "600000.SH", "SELL", 30, 20.0, "2024-01-08")
    after_sell, sell_result = apply_fill(state, excessive_sell, commission_bps=0.0)
    assert sell_result.accepted is False
    assert sell_result.reason == "insufficient_position"
    assert after_sell == state


def test_ledger_rejects_duplicate_fill_and_invalid_fill() -> None:
    state = LedgerState(initial_cash=10_000.0)
    fill = FillEvent("fill-5", "order-5", "600000.SH", "BUY", 100, 10.0, "2024-01-08")
    booked, result = apply_fill(state, fill, commission_bps=0.0)
    assert result.accepted is True
    duplicate_state, duplicate = apply_fill(booked, fill, commission_bps=0.0)
    assert duplicate_state == booked
    assert duplicate.accepted is False
    assert duplicate.reason == "duplicate_fill"

    with pytest.raises(ValueError, match="quantity"):
        FillEvent("fill-6", "order-6", "600000.SH", "BUY", 0, 10.0, "2024-01-08")
