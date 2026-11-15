from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.data import normalise_market_frame
from portfolio_app.strategies import (
    STRATEGIES,
    build_strategy_config,
    generate_signal,
    normalize_strategy_params,
)
from portfolio_app.research import run_single_stock_research


def sample_frame(rows: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=rows, freq="B")
    close = pd.Series(100 + pd.Series(range(rows)), dtype=float)
    return normalise_market_frame(
        pd.DataFrame(
            {
                "date": dates.strftime("%Y%m%d"),
                "symbol": "DEMO",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000,
                "roe": 12,
                "pb": 2,
            }
        )
    )


def test_every_strategy_declares_rules_features_and_parameters():
    assert {item.key for item in STRATEGIES} == {"trend", "mean_reversion", "quality_momentum"}
    for strategy in STRATEGIES:
        config = build_strategy_config(strategy.key)
        assert config["strategy_id"] == strategy.key
        assert config["version"]
        assert config["required_features"]
        assert config["rules"]
        assert config["parameters"]
        assert config["execution_lag_days"] == 1


def test_strategy_parameters_change_signal_output_without_changing_contract():
    frame = sample_frame()
    default = generate_signal(frame, "mean_reversion")
    strict = generate_signal(frame, "mean_reversion", params={"entry_zscore": 2.0})
    assert {"signal", "signal_label", "decision_date", "effective_date", "strategy_id"}.issubset(default.columns)
    assert len(default) == len(strict) == len(frame)
    assert default["strategy_id"].eq("mean_reversion").all()
    assert strict["effective_date"].notna().all()
    assert {"reason_code", "reason_text_public", "reason_evidence"}.issubset(default.columns)
    assert default["reason_code"].notna().all()
    assert default["reason_text_public"].ne("").all()


def test_configured_quality_momentum_uses_named_parameters():
    frame = sample_frame()
    frame['roe_available_at'] = frame.trade_date
    frame['pb_available_at'] = frame.trade_date
    result = generate_signal(
        frame,
        "quality_momentum",
        params={"min_roe": 10.0, "max_pb": 3.0, "momentum_window": 40},
    )
    assert result["signal"].isin([-1, 0, 1]).all()
    assert result["strategy_id"].eq("quality_momentum").all()


def test_signal_reason_changes_when_a_trend_breaks():
    frame = sample_frame(140)
    frame.loc[120:, "close"] = frame.loc[120:, "close"] - 80
    result = generate_signal(frame, "trend")

    assert result["reason_code"].eq("trend_break").any()
    assert result.loc[result["reason_code"].eq("trend_break"), "reason_text_public"].str.len().gt(0).all()


def test_strategy_params_are_normalized_against_the_declared_schema():
    normalized = normalize_strategy_params("trend", {"fast_window": 15, "slow_window": 80})
    assert normalized == {"fast_window": 15, "slow_window": 80}
    with pytest.raises(ValueError, match="unknown strategy parameter"):
        normalize_strategy_params("trend", {"not_a_parameter": 1})
    with pytest.raises(ValueError, match="fast_window"):
        normalize_strategy_params("trend", {"fast_window": 2})
    with pytest.raises(ValueError, match="fast_window"):
        normalize_strategy_params("trend", {"fast_window": 100, "slow_window": 50})


def test_single_stock_research_applies_date_bounds_and_exposes_diagnostics():
    frame = sample_frame(180)
    start = frame["trade_date"].iloc[30]
    end = frame["trade_date"].iloc[150]
    result = run_single_stock_research(
        frame,
        strategy_key="trend",
        params={"fast_window": 15, "slow_window": 50},
        start_date=start,
        end_date=end,
        transaction_cost=0.001,
    )
    assert result.frame["trade_date"].min() >= pd.Timestamp(start)
    assert result.frame["trade_date"].max() <= pd.Timestamp(end)
    assert result.metrics["observations"] == len(result.frame)
    assert {"signal_coverage", "turnover", "trades", "warmup_bars", "execution_lag_days", "data_quality_warnings"}.issubset(result.diagnostics)
    assert result.diagnostics["execution_lag_days"] == 1
    assert result.frame.attrs["trade_events"] == result.trade_events


def test_single_stock_research_is_reproducible_and_reports_empty_trade_state():
    frame = sample_frame(120)
    first = run_single_stock_research(frame, strategy_key="trend", params={"fast_window": 20, "slow_window": 60})
    second = run_single_stock_research(frame, strategy_key="trend", params={"fast_window": 20, "slow_window": 60})
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.metrics == second.metrics
    assert first.diagnostics == second.diagnostics

    flat = frame.copy()
    flat["close"] = 100.0
    flat["open"] = 100.0
    flat["high"] = 100.0
    flat["low"] = 100.0
    empty = run_single_stock_research(flat, strategy_key="trend")
    assert empty.metrics["trades"] == 0
    assert empty.trade_events == []
    assert empty.diagnostics["signal_coverage"] == 0.0
