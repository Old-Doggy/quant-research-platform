from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.data import normalise_market_frame


def _frame(rows: int = 180, *, with_signal: bool = False) -> pd.DataFrame:
    dates = pd.date_range("2022-01-03", periods=rows, freq="B")
    close = pd.Series(100 + pd.Series(range(rows), dtype=float) * 0.4)
    if with_signal:
        close = pd.Series(100.0, index=range(rows))
    frame = normalise_market_frame(
        pd.DataFrame(
            {
                "date": dates.strftime("%Y%m%d"),
                "symbol": "DEMO",
                "open": close * 0.995,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
            }
        )
    )
    if with_signal:
        frame["signal"] = 0
    return frame


def test_sensitivity_report_has_explicit_baseline_and_relative_deltas():
    from portfolio_app.sensitivity import build_single_stock_sensitivity_report

    report = build_single_stock_sensitivity_report(
        _frame(),
        "trend",
        params={"fast_window": 10, "slow_window": 30},
        transaction_cost=0.001,
        transaction_costs=(0.0, 0.001, 0.002),
        slippage_bps=(0, 10),
        execution_policies=("next_day_close", "next_day_open"),
    )

    baseline = report.loc[report["is_baseline"]].iloc[0]
    assert len(report) == 5
    assert baseline["changed_assumption"] == "baseline"
    assert baseline["execution_policy"] == "next_day_close"
    assert baseline["delta_total_return"] == pytest.approx(0.0)
    assert baseline["delta_max_drawdown"] == pytest.approx(0.0)
    assert {"scenario_id", "scenario_count", "baseline_scenario_id", "changed_assumption", "assumption_change", "research_only"}.issubset(report.columns)
    assert report["scenario_count"].eq(len(report)).all()
    assert report["baseline_scenario_id"].eq(baseline["scenario_id"]).all()
    assert report["research_only"].eq(True).all()


def test_sensitivity_separates_transaction_cost_and_slippage_changes():
    from portfolio_app.sensitivity import build_single_stock_sensitivity_report

    report = build_single_stock_sensitivity_report(
        _frame(),
        "trend",
        params={"fast_window": 10, "slow_window": 30},
        transaction_cost=0.001,
        transaction_costs=(0.001, 0.002),
        slippage_bps=(0, 10),
        execution_policies=("next_day_close",),
    )

    assert set(report["changed_assumption"]) == {"baseline", "transaction_cost", "slippage_bps"}
    cost = report.loc[report["changed_assumption"].eq("transaction_cost")].iloc[0]
    slip = report.loc[report["changed_assumption"].eq("slippage_bps")].iloc[0]
    assert cost["transaction_cost"] == pytest.approx(0.002)
    assert cost["slippage_bps"] == 0
    assert cost["transaction_cost_component"] > 0
    assert cost["slippage_component"] == 0
    assert slip["transaction_cost"] == pytest.approx(0.001)
    assert slip["slippage_bps"] == 10
    assert slip["transaction_cost_component"] == pytest.approx(0.001 * slip["turnover"])
    assert slip["slippage_component"] > 0
    assert slip["delta_total_cost"] > 0


def test_sensitivity_labels_execution_policy_and_rejects_unknown_or_negative_values():
    from portfolio_app.sensitivity import build_single_stock_sensitivity_report

    report = build_single_stock_sensitivity_report(
        _frame(),
        "trend",
        params={"fast_window": 10, "slow_window": 30},
        execution_policies=("next_day_close", "next_day_open"),
    )
    policy_row = report.loc[report["changed_assumption"].eq("execution_policy")].iloc[0]
    assert policy_row["execution_policy"] == "next_day_open"
    assert "离线研究假设" in policy_row["execution_policy_label"]
    with pytest.raises(ValueError, match="unknown execution policy"):
        build_single_stock_sensitivity_report(_frame(), "trend", execution_policies=("live_market",))
    with pytest.raises(ValueError, match="transaction_cost cannot be negative"):
        build_single_stock_sensitivity_report(_frame(), "trend", transaction_cost=-0.001)
    with pytest.raises(ValueError, match="slippage_bps cannot be negative"):
        build_single_stock_sensitivity_report(_frame(), "trend", slippage_bps=(-1,))


def test_sensitivity_reports_empty_trades_and_invalid_data_with_stable_statuses():
    from portfolio_app.sensitivity import build_single_stock_sensitivity_report

    empty_trade = build_single_stock_sensitivity_report(
        _frame(with_signal=True),
        "trend",
        params={"fast_window": 10, "slow_window": 30},
    )
    assert empty_trade["status"].eq("no_trades").all()
    assert empty_trade["trades"].eq(0).all()
    assert empty_trade["sharpe"].isna().all()

    invalid = _frame().drop(columns=["close"])
    invalid_report = build_single_stock_sensitivity_report(invalid, "trend")
    assert invalid_report["status"].eq("invalid_data").all()
    assert invalid_report["total_return"].isna().all()


def test_sensitivity_uses_visible_window_but_keeps_history_for_warmup():
    from portfolio_app.sensitivity import build_single_stock_sensitivity_report

    frame = _frame(180)
    report = build_single_stock_sensitivity_report(
        frame,
        "trend",
        params={"fast_window": 10, "slow_window": 30},
        start_date=frame["trade_date"].iloc[90],
        end_date=frame["trade_date"].iloc[-1],
    )

    assert report["observations"].eq(90).all()
    assert report["status"].isin({"ok", "no_trades"}).all()


def test_next_day_open_policy_uses_open_fill_for_new_position_then_close_to_close():
    from portfolio_app.backtest import run_backtest

    frame = _frame(3)
    frame["open"] = [100.0, 105.0, 115.0]
    frame["close"] = [100.0, 110.0, 120.0]
    frame["return"] = frame["close"].pct_change()
    frame["signal"] = [1, 1, 1]

    result, _ = run_backtest(frame, transaction_cost=0.0, execution_policy="next_day_open")
    assert result["execution_return"].iloc[1] == pytest.approx(110 / 105 - 1)
    assert result["execution_return"].iloc[2] == pytest.approx(120 / 110 - 1)


def test_execution_policies_exclude_pre_entry_gap_and_keep_exit_return():
    from portfolio_app.backtest import run_backtest

    frame = _frame(4)
    frame["open"] = [100., 120., 150., 90.]
    frame["close"] = [100., 132., 144., 99.]
    frame["return"] = frame["close"].pct_change()
    frame["signal"] = [1, 0, 0, 0]
    opened, _ = run_backtest(frame, 0, execution_policy="next_day_open")
    closed, _ = run_backtest(frame, 0, execution_policy="next_day_close")
    proxy, _ = run_backtest(frame, 0)
    assert opened["strategy_return"].tolist() == pytest.approx([0, .1, 150/132-1, 0])
    assert closed["strategy_return"].tolist() == pytest.approx([0, 0, 144/132-1, 0])
    assert proxy["strategy_return"].tolist() == pytest.approx([0, .32, 0, 0])
    fills = [e for e in opened.attrs["trade_events"] if e["event_type"] == "FILL"]
    assert [e["price"] for e in fills] == [120., 150.]


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), -.1])
def test_nonfinite_or_negative_baseline_cost_is_rejected(cost):
    from portfolio_app.sensitivity import build_single_stock_sensitivity_report
    with pytest.raises(ValueError):
        build_single_stock_sensitivity_report(_frame(), "trend", transaction_cost=cost)


def test_scenarios_deduplicate_and_reject_missing_return_data():
    from portfolio_app.sensitivity import build_single_stock_sensitivity_report
    report = build_single_stock_sensitivity_report(
        _frame(), "trend", transaction_costs=(0, 0), slippage_bps=(10, 10),
        execution_policies=("next_day_open", "next_day_open"),
    )
    assert report["scenario_id"].is_unique
    assert len(report) == 4
    broken = _frame()
    broken.loc[40, "close"] = float("nan")
    report = build_single_stock_sensitivity_report(broken, "trend")
    assert report["status"].eq("invalid_data").all()


def test_single_stock_research_uses_the_declared_next_day_close_baseline():
    from portfolio_app.research import run_single_stock_research

    result = run_single_stock_research(
        _frame(),
        strategy_key="trend",
        params={"fast_window": 10, "slow_window": 30},
        transaction_cost=0.001,
    )
    assert result.metrics["execution_policy"] == "next_day_close"
