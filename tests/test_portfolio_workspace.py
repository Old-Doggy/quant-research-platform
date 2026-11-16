from dataclasses import replace

import pandas as pd
import pytest

from portfolio_app.offline_execution import ExecutionSpec
from portfolio_app.portfolio_recipe import PortfolioRecipe
from portfolio_app.portfolio_workspace import run_portfolio_workspace, portfolio_drilldown, portfolio_scenarios


def inputs():
    dates = pd.bdate_range("2024-01-02", periods=40)
    frames = {}
    for symbol, offset in (("AAA", 0), ("BBB", 5)):
        close = [10 + offset + n for n in range(40)]
        frames[symbol] = pd.DataFrame(dict(trade_date=dates, open=close, high=close,
            low=close, close=close, volume=10000, symbol=symbol))
    recipe = PortfolioRecipe.from_dict(dict(recipe_id="test", target_weights={"AAA": .4, "BBB": .4}, cash_weight=.2, lot_size=1))
    spec = ExecutionSpec("next-close", "close", "next_close", 10, 0, "us_stock")
    return frames, recipe, spec


def run(frames=None, recipe=None, spec=None, **kwargs):
    defaults = inputs()
    return run_portfolio_workspace(frames if frames is not None else defaults[0],
        recipe=recipe or defaults[1], spec=spec or defaults[2], strategy_key="trend",
        params={"fast_window": 5, "slow_window": 30}, initial_cash=10000, **kwargs)


def test_shared_account_reconciles_cash_fills_and_both_contribution_axes():
    result = run()
    assert result.accounting.diagnostics["contribution_status"] == "reconciled"
    assert result.accounting.ledger.iloc[-1].cash == pytest.approx(result.orders[-1]["cash_after"])
    assert len(result.fills) > 0
    for fill in result.fills:
        assert fill["fill_date"] > fill["decision_date"]
        assert fill["quantity"] > 0
    assert len(result.inputs["data_sha256"]) == 64


def test_drilldown_synchronizes_date_symbol_positions_orders_and_contributions():
    result = run()
    date = result.fills[0]["fill_date"]
    view = portfolio_drilldown(result, date=date, symbol="AAA")
    assert set(view["positions"].symbol) == {"AAA"}
    assert set(view["positions"].trade_date) == {date}
    assert all(row["symbol"] == "AAA" and row["effective_date"] == date for row in view["orders"])
    assert view["ledger"].trade_date.tolist() == [date]
    assert view["curve"].trade_date.max() == date
    assert "leg_contribution" in view
    with pytest.raises(ValueError, match="symbol"):
        portfolio_drilldown(result, date=date, symbol="UNKNOWN")
    with pytest.raises(ValueError, match="date"):
        portfolio_drilldown(result, date="1990-01-01")


def test_all_cash_and_empty_signal_results_are_valid():
    frames, _, spec = inputs()
    recipe = replace(inputs()[1], target_weights={"AAA": 0, "BBB": 0}, cash_weight=1)
    result = run(frames, recipe, spec)
    assert result.accounting.ledger.nav.tolist() == [10000] * 40
    assert not result.orders and not result.fills
    assert result.accounting.risk["status"] == "unavailable"


def test_scenarios_change_one_assumption_and_keep_failures_isolated():
    frames, recipe, spec = inputs()
    report = portfolio_scenarios(frames, recipe=recipe, spec=spec, strategy_key="trend",
        params={"fast_window": 5, "slow_window": 30}, initial_cash=10000,
        variants=[("cost", "cost", 20), ("open", "execution", "next_open"),
                  ("weights", "weights", {"AAA": .2, "BBB": .6}),
                  ("bad", "cost", -1)])
    assert report.scenario_id.tolist() == ["baseline", "cost", "open", "weights", "bad"]
    assert report.iloc[0].delta_total_return == 0
    assert report.iloc[-1].status == "failed"
    assert pd.isna(report.iloc[-1].delta_total_return)
    assert all(report.iloc[1:4].comparable)


def test_missing_data_does_not_become_zero_return_or_comparable_scenario():
    frames, recipe, spec = inputs()
    frames["BBB"] = frames["BBB"].iloc[1:]
    with pytest.raises(ValueError, match="sessions"):
        run(frames)
    report = portfolio_scenarios(frames, recipe=recipe, spec=spec, strategy_key="trend",
        params={"fast_window": 5, "slow_window": 30}, initial_cash=10000,
        variants=[("cost", "cost", 20)])
    assert set(report.status) == {"data_blocked"}
    assert not report.comparable.any()


def test_future_price_change_does_not_change_an_earlier_order_quantity():
    frames, recipe, spec = inputs()
    original = run(frames, recipe, spec)
    first = original.fills[0]
    future = frames["AAA"].trade_date.dt.strftime("%Y-%m-%d") >= first["fill_date"]
    frames["AAA"].loc[future, ["open", "high", "low", "close"]] *= 2
    changed = run(frames, recipe, spec)
    before = next(o for o in original.orders if o["signal_id"] == first["fill_id"])
    after = next(o for o in changed.orders if o["signal_id"] == first["fill_id"])
    assert before["requested_quantity"] == after["requested_quantity"]


def test_inconsistent_ohlc_and_nonfinite_price_are_data_blocked():
    frames, _, _ = inputs()
    frames["AAA"].loc[0, "high"] = 1
    with pytest.raises(ValueError, match="OHLC"):
        run(frames)


def test_scenarios_cannot_change_universe_or_order_definition_implicitly():
    frames, recipe, spec = inputs()
    report = portfolio_scenarios(frames, recipe=recipe, spec=spec, strategy_key="trend",
        params={"fast_window": 5, "slow_window": 30}, initial_cash=10000,
        variants=[("different-universe", "weights", {"AAA": .8})])
    assert report.iloc[-1].status == "incomparable"
    assert not report.iloc[-1].comparable
    assert pd.isna(report.iloc[-1].delta_total_return)


def test_no_future_session_order_remains_visible_on_its_decision_date():
    result = run()
    date = result.inputs["sessions"][-1]
    rejected = [o for o in result.orders if o["effective_date"] is None]
    assert rejected
    view = portfolio_drilldown(result, date=date)
    assert all(o in view["orders"] for o in rejected)


def test_drilldown_risk_uses_only_history_through_date_and_whole_account():
    from portfolio_app.portfolio_accounting import _risk
    result=run()
    date=result.fills[0]['fill_date']
    view=portfolio_drilldown(result,date=date,symbol='AAA')
    earlier=result.accounting.ledger.loc[result.accounting.ledger.trade_date.le(date)].copy()
    positions=result.positions.loc[result.positions.trade_date.eq(date)]
    expected=_risk(earlier,dict(zip(positions.symbol,positions.quantity)),
        {r.symbol:{date:r.close} for r in positions.itertuples()},252,None,None,False)
    assert view['risk']==expected
    assert view['risk']['observations']<result.accounting.risk['observations']
    assert view['risk']==portfolio_drilldown(result,date=date)['risk']
    # Mutating all future account rows and the full-period summary must not leak backward.
    result.accounting.ledger.loc[result.accounting.ledger.trade_date.gt(date),'daily_return']=.9
    result.accounting.risk['annual_volatility']=999.
    result.positions.loc[result.positions.trade_date.gt(date),'market_value']=1e12
    assert portfolio_drilldown(result,date=date)['risk']==expected


def test_drilldown_cash_only_and_final_risk_match_saved_account():
    result=run()
    start=result.accounting.ledger.trade_date.iloc[0]
    initial=portfolio_drilldown(result,date=start)['risk']
    assert initial['status']=='unavailable' and initial['concentration_hhi'] is None
    final=portfolio_drilldown(result,date=result.accounting.ledger.trade_date.iloc[-1])['risk']
    assert final==result.accounting.risk
