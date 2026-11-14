from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.single_stock_performance import (
    PerformanceContractError,
    build_single_stock_performance,
)


def result_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=5),
            "strategy_return": [0.0, 0.10, -0.05, 0.0, 0.02],
            "return": [0.0, 0.05, -0.02, 0.03, 0.01],
            "position": [0.0, 1.0, 1.0, 0.0, 0.0],
            "equity": [1.0, 1.10, 1.045, 1.045, 1.0659],
            "benchmark_equity": [1.0, 1.05, 1.029, 1.05987, 1.0704687],
            "drawdown": [0.0, 0.0, -0.05, -0.05, -0.031],
        }
    )


def test_single_stock_performance_exposes_comparable_nav_benchmark_drawdown_and_cost():
    view = build_single_stock_performance(result_frame(), transaction_cost=0.001)

    assert view["schema_version"] == "single-stock-performance.v1"
    assert view["status"] == "available"
    assert len(view["curve"]) == 5
    assert set(view["curve"][0]) == {"date", "nav", "benchmark_nav", "drawdown", "daily_return", "daily_cost"}
    assert view["curve"][1]["nav"] == pytest.approx(1.10)
    assert view["curve"][1]["benchmark_nav"] == pytest.approx(1.05)
    assert view["metrics"]["total_return"] == pytest.approx(0.0659)
    assert view["metrics"]["benchmark_total_return"] == pytest.approx(0.0704687)
    assert view["metrics"]["total_cost"] == pytest.approx(0.002)
    assert view["metrics"]["trades"] == 2
    assert view["cost_assumption"]["transaction_cost"] == pytest.approx(0.001)


def test_empty_trade_strategy_is_available_and_keeps_zero_cost_explicit():
    frame = result_frame()
    frame["strategy_return"] = frame["return"] * 0
    frame["position"] = 0
    frame["equity"] = 1.0
    frame["drawdown"] = 0.0

    view = build_single_stock_performance(frame, transaction_cost=0.002)

    assert view["status"] == "available"
    assert view["metrics"]["trades"] == 0
    assert view["metrics"]["total_return"] == pytest.approx(0.0)
    assert view["metrics"]["total_cost"] == pytest.approx(0.0)
    assert view["diagnostics"]["empty_trade_state"] is True


def test_curve_does_not_silently_repair_bad_or_misaligned_result_columns():
    missing = result_frame().drop(columns=["benchmark_equity"])
    with pytest.raises(PerformanceContractError, match="benchmark_equity"):
        build_single_stock_performance(missing, transaction_cost=0.001)

    broken = result_frame()
    broken.loc[2, "equity"] = 0.0
    with pytest.raises(PerformanceContractError, match="equity"):
        build_single_stock_performance(broken, transaction_cost=0.001)


def test_cost_assumption_rejects_negative_or_non_finite_values():
    with pytest.raises(PerformanceContractError, match="transaction_cost"):
        build_single_stock_performance(result_frame(), transaction_cost=-0.001)
    with pytest.raises(PerformanceContractError, match="transaction_cost"):
        build_single_stock_performance(result_frame(), transaction_cost=float("inf"))


def test_flat_strategy_keeps_unavailable_risk_ratios_as_none():
    frame = result_frame()
    frame["strategy_return"] = 0.0
    frame["position"] = 0.0
    frame["equity"] = 1.0
    frame["drawdown"] = 0.0
    view = build_single_stock_performance(frame, transaction_cost=0.0)
    assert view["metrics"]["sharpe"] is None
    assert view["metrics"]["sortino"] is None


def test_first_return_can_be_missing_but_later_return_gaps_are_rejected():
    frame = result_frame()
    frame.loc[0, "return"] = float("nan")
    view = build_single_stock_performance(frame, transaction_cost=0.0)
    assert view["curve"][0]["daily_return"] == pytest.approx(0.0)

    frame.loc[2, "return"] = float("nan")
    with pytest.raises(PerformanceContractError, match="return"):
        build_single_stock_performance(frame, transaction_cost=0.0)
