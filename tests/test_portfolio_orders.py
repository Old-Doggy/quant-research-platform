from __future__ import annotations

import pytest

from portfolio_app.offline_execution import ExecutionSpec
from portfolio_app.offline_market_rules import AssetRule
from portfolio_app.portfolio_orders import (
    PortfolioOrderError,
    plan_portfolio_orders,
    preflight_portfolio_order_config,
)
from portfolio_app.portfolio_recipe import PortfolioRecipe


def _recipe(**overrides):
    value = {
        "recipe_id": "order-demo-v1",
        "target_weights": {"AAA": 0.5, "BBB": 0.3},
        "cash_weight": 0.2,
        "lower_bounds": {},
        "upper_bounds": {},
        "lot_size": 1,
        "min_rebalance_weight": 0.0,
        "missing_leg_policy": "preserve_cash",
    }
    value.update(overrides)
    return PortfolioRecipe.from_dict(value)


def _spec():
    return ExecutionSpec(
        policy_id="portfolio-next-open",
        price_field="open",
        fill_model="next_open",
        commission_bps=0.0,
        slippage_bps=0.0,
        asset_type="us_stock",
    )


def _signal(signal_id, symbol, side, quantity):
    return {
        "signal_id": signal_id,
        "strategy_id": "demo-strategy",
        "symbol": symbol,
        "side": side,
        "decision_date": "2024-01-05",
        "quantity": quantity,
    }


def _rules(*symbols, t_plus_one=False, lot_size=1):
    return {
        symbol: AssetRule("us_stock", lot_size=lot_size, t_plus_one=t_plus_one)
        for symbol in symbols
    }


def test_portfolio_orders_sell_before_buy_and_share_cash_with_stable_event_keys():
    result = plan_portfolio_orders(
        [_signal("buy-b", "BBB", "BUY", 10), _signal("sell-a", "AAA", "SELL", 10)],
        sessions=("2024-01-05", "2024-01-08"),
        spec=_spec(),
        recipe=_recipe(),
        initial_cash=0.0,
        initial_positions={"AAA": 10},
        prices={"AAA": {"2024-01-08": 10.0}, "BBB": {"2024-01-08": 10.0}},
        rules=_rules("AAA", "BBB"),
    )

    assert [event.side for event in result.events] == ["SELL", "BUY"]
    assert [event.status for event in result.events] == ["FILLED", "FILLED"]
    assert result.cash_after == pytest.approx(0.0)
    assert result.positions_after == {"AAA": 0, "BBB": 10}
    assert result.events[0].portfolio_event_key == result.events[1].portfolio_event_key
    assert result.events[0].leg_event_key != result.events[1].leg_event_key
    assert result.rejected_count == 0


def test_portfolio_orders_reject_later_buy_when_shared_cash_is_exhausted():
    result = plan_portfolio_orders(
        [_signal("buy-a", "AAA", "BUY", 10), _signal("buy-b", "BBB", "BUY", 10)],
        sessions=("2024-01-05", "2024-01-08"),
        spec=_spec(),
        recipe=_recipe(),
        initial_cash=100.0,
        prices={"AAA": {"2024-01-08": 10.0}, "BBB": {"2024-01-08": 10.0}},
        rules=_rules("AAA", "BBB"),
    )

    assert result.events[0].status == "FILLED"
    assert result.events[1].status == "REJECTED"
    assert result.events[1].reason_code == "insufficient_cash"
    assert "现金" in result.events[1].reason
    assert result.positions_after == {"AAA": 10}
    assert result.cash_after == pytest.approx(0.0)


def test_portfolio_orders_expose_capacity_partial_fill_and_t_plus_one_rejection():
    result = plan_portfolio_orders(
        [_signal("buy-a", "AAA", "BUY", 10), _signal("sell-b", "BBB", "SELL", 10)],
        sessions=("2024-01-05", "2024-01-08"),
        spec=_spec(),
        recipe=_recipe(),
        initial_cash=200.0,
        initial_positions={"BBB": 10},
        acquired_today={"BBB": 10},
        prices={"AAA": {"2024-01-08": 10.0}, "BBB": {"2024-01-08": 10.0}},
        session_volumes={"AAA": {"2024-01-08": 4}},
        participation_rate=0.5,
        allow_partial_fill=True,
        rules={"AAA": AssetRule("us_stock", 1, False), "BBB": AssetRule("cn_stock", 1, True)},
    )

    assert result.events[0].status == "PARTIALLY_FILLED"
    assert result.events[0].filled_quantity == 2
    assert result.events[0].reason_code == "partial_capacity"
    assert "容量" in result.events[0].reason
    assert result.events[1].status == "REJECTED"
    assert result.events[1].reason_code == "insufficient_sellable_qty"
    assert result.positions_after == {"AAA": 2, "BBB": 10}


def test_portfolio_orders_do_not_create_positions_for_missing_or_untradable_legs():
    result = plan_portfolio_orders(
        [_signal("missing", "AAA", "BUY", 10), _signal("blocked", "BBB", "BUY", 10)],
        sessions=("2024-01-05", "2024-01-08"),
        spec=_spec(),
        recipe=_recipe(),
        initial_cash=200.0,
        prices={"BBB": {"2024-01-08": 10.0}},
        price_status={"BBB": "fresh"},
        tradability={"BBB": "suspended"},
        rules=_rules("AAA", "BBB"),
    )

    assert [event.reason_code for event in result.events] == ["missing_price", "suspended"]
    assert "价格" in result.events[0].reason
    assert "停牌" in result.events[1].reason
    assert result.positions_after == {}
    assert result.cash_after == pytest.approx(200.0)
    assert all(event.filled_quantity == 0 for event in result.events)


def test_portfolio_orders_reject_second_sell_when_first_sell_consumes_position():
    result = plan_portfolio_orders(
        [_signal("sell-a-1", "AAA", "SELL", 7), _signal("sell-a-2", "AAA", "SELL", 7)],
        sessions=("2024-01-05", "2024-01-08"),
        spec=_spec(),
        recipe=_recipe(),
        initial_cash=0.0,
        initial_positions={"AAA": 10},
        prices={"AAA": {"2024-01-08": 10.0}},
        rules=_rules("AAA"),
    )

    assert result.events[0].status == "FILLED"
    assert result.events[1].status == "REJECTED"
    assert result.events[1].reason_code == "insufficient_position"
    assert result.positions_after == {"AAA": 3}


def test_portfolio_order_preflight_reports_duplicate_and_lot_conflicts():
    signals = [_signal("same", "AAA", "BUY", 10), _signal("same", "BBB", "BUY", 10)]
    checks = preflight_portfolio_order_config(
        signals,
        recipe=_recipe(lot_size=100),
        rules={"AAA": AssetRule("cn_stock", 100, True), "BBB": AssetRule("us_stock", 1, False)},
    )

    assert checks.ok is False
    assert "duplicate_signal_id" in checks.issue_codes
    assert "lot_size_conflict" in checks.issue_codes
    with pytest.raises(PortfolioOrderError, match="preflight"):
        plan_portfolio_orders(
            signals,
            sessions=("2024-01-05", "2024-01-08"),
            spec=_spec(),
            recipe=_recipe(lot_size=100),
            initial_cash=1000.0,
            prices={"AAA": {"2024-01-08": 10.0}, "BBB": {"2024-01-08": 10.0}},
            rules={"AAA": AssetRule("cn_stock", 100, True), "BBB": AssetRule("us_stock", 1, False)},
        )


def _run(signals, **overrides):
    options = dict(
        sessions=("2024-01-05", "2024-01-08", "2024-01-09"),
        spec=_spec(), recipe=_recipe(), initial_cash=100.0,
        prices={"AAA": {"2024-01-08": 10.0, "2024-01-09": 11.0}},
        rules=_rules("AAA", "BBB"),
        tradability={"AAA": "tradable", "BBB": "tradable"},
    )
    options.update(overrides)
    return plan_portfolio_orders(signals, **options)


def test_buy_then_sell_across_sessions_uses_updated_position_and_unlocks_t_plus_one():
    buy = _signal("buy", "AAA", "BUY", 10)
    sell = {**_signal("sell", "AAA", "SELL", 10), "decision_date": "2024-01-08"}
    result = _run([sell, buy], rules=_rules("AAA", t_plus_one=True))
    assert [event.status for event in result.events] == ["FILLED", "FILLED"]
    assert [event.effective_date for event in result.events] == ["2024-01-08", "2024-01-09"]
    assert result.cash_after == pytest.approx(110)
    assert result.positions_after == {"AAA": 0}


def test_initial_t_plus_one_lock_applies_to_first_effective_session_only():
    sell = _signal("locked", "AAA", "SELL", 10)
    next_sell = {**sell, "signal_id": "unlocked", "decision_date": "2024-01-08"}
    result = _run([sell, next_sell], initial_positions={"AAA": 10},
                  acquired_today={"AAA": 10}, rules=_rules("AAA", t_plus_one=True))
    assert [event.reason_code for event in result.events] == ["insufficient_sellable_qty", None]
    assert result.cash_after == pytest.approx(210)


def test_failed_buy_does_not_consume_capacity_needed_by_later_affordable_buy():
    result = _run([_signal("too-big", "AAA", "BUY", 10), _signal("small", "AAA", "BUY", 5)],
                  initial_cash=50.0, session_volumes={"AAA": {"2024-01-08": 10}})
    assert {event.signal_id: event.filled_quantity for event in result.events} == {"too-big": 0, "small": 5}
    assert result.positions_after == {"AAA": 5}


def test_capacity_matching_uses_sell_then_buy_order_and_actual_shared_consumption():
    result = _run([_signal("buy", "AAA", "BUY", 5), _signal("sell", "AAA", "SELL", 5)],
                  initial_cash=0.0, initial_positions={"AAA": 5},
                  session_volumes={"AAA": {"2024-01-08": 7}}, allow_partial_fill=True)
    assert [event.side for event in result.events] == ["SELL", "BUY"]
    assert [event.filled_quantity for event in result.events] == [5, 2]
    assert result.cash_after == pytest.approx(30)


def test_missing_volume_is_a_leg_rejection_without_losing_other_results():
    result = _run([_signal("a", "AAA", "BUY", 1), _signal("b", "BBB", "BUY", 1)],
                  session_volumes={"BBB": {"2024-01-08": 10}},
                  prices={"AAA": {"2024-01-08": 10}, "BBB": {"2024-01-08": 10}})
    assert {event.signal_id: event.reason_code for event in result.events} == {
        "a": "missing_capacity_data", "b": None}
    assert result.positions_after == {"BBB": 1}


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_prices_never_change_cash_or_position(price):
    result = _run([_signal("invalid", "AAA", "BUY", 1)], prices={"AAA": {"2024-01-08": price}})
    assert result.events[0].reason_code == "invalid_price"
    assert result.cash_after == 100
    assert result.positions_after == {}


@pytest.mark.parametrize("positions,acquired", [({"AAA": -1}, {}), ({"AAA": 1.5}, {}),
                                             ({"AAA": True}, {}), ({"AAA": 1}, {"AAA": 2})])
def test_invalid_position_snapshots_fail_before_simulation(positions, acquired):
    with pytest.raises(PortfolioOrderError, match="position|acquired"):
        _run([_signal("a", "AAA", "BUY", 1)], initial_positions=positions, acquired_today=acquired)


def test_duplicate_normalized_signal_ids_fail_preflight():
    checks = preflight_portfolio_order_config(
        [_signal("same", "AAA", "BUY", 1), _signal(" same ", "AAA", "BUY", 1)],
        recipe=_recipe(), rules=_rules("AAA"))
    assert not checks.ok
    assert "duplicate_signal_id" in checks.issue_codes
