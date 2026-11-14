from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.data import normalise_market_frame
from portfolio_app.indicators import (
    INDICATOR_REGISTRY,
    build_default_indicator_config,
    calculate_registered_indicators,
    get_indicator_spec,
    add_indicator_selection,
    move_indicator_selection,
    normalize_indicator_config,
    order_indicator_config,
    remove_indicator_selection,
    validate_indicator_layout,
)


def _market_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=80, freq="B")
    close = pd.Series(100 + pd.Series(range(len(dates))) * 0.25, dtype=float)
    return normalise_market_frame(
        pd.DataFrame(
            {
                "date": dates.strftime("%Y%m%d"),
                "symbol": "DEMO",
                "open": close - 0.4,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000 + pd.Series(range(len(dates))) * 10,
            }
        )
    )


def test_registry_exposes_stable_overlay_and_panel_indicator_specs():
    assert {"MA", "EMA", "BOLL", "RSI", "MACD", "KDJ", "ATR", "OBV", "VWAP"}.issubset(INDICATOR_REGISTRY)
    assert get_indicator_spec("MA").pane == "overlay"
    assert get_indicator_spec("BOLL").pane == "overlay"
    assert get_indicator_spec("RSI").pane == "panel"
    assert get_indicator_spec("MACD").pane == "panel"
    assert get_indicator_spec("MA").parameters["period"]["default"] == 20


def test_indicator_configuration_is_normalized_and_rejects_unknown_or_invalid_values():
    normalized = normalize_indicator_config(
        [
            {"key": "MA", "params": {"period": 30}},
            {"key": "RSI", "params": {"period": 14}},
        ]
    )
    assert normalized == [
        {"key": "MA", "params": {"period": 30}},
        {"key": "RSI", "params": {"period": 14}},
    ]
    with pytest.raises(ValueError, match="unknown indicator"):
        normalize_indicator_config([{"key": "NOT_REAL"}])
    with pytest.raises(ValueError, match="period"):
        normalize_indicator_config([{"key": "MA", "params": {"period": 0}}])


def test_registered_calculation_returns_expected_columns_without_mutating_input():
    frame = _market_frame()
    original_columns = list(frame.columns)
    result = calculate_registered_indicators(
        frame,
        [
            {"key": "MA", "params": {"period": 20}},
            {"key": "BOLL", "params": {"period": 20, "stddev": 2.0}},
            {"key": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}},
            {"key": "OBV", "params": {}},
            {"key": "VWAP", "params": {}},
        ],
    )
    assert list(frame.columns) == original_columns
    assert {"ma20", "boll_mid20", "boll_upper20", "boll_lower20", "macd", "macd_signal", "macd_hist", "obv", "vwap"}.issubset(result.columns)
    assert result.index.equals(frame.index)
    assert result["obv"].iloc[-1] > 0
    assert result["vwap"].notna().all()


def test_registered_calculation_is_deterministic_for_all_public_indicators():
    frame = _market_frame()
    configs = [{"key": key, "params": {}} for key in ("MA", "EMA", "BOLL", "RSI", "MACD", "KDJ", "ATR", "OBV", "VWAP")]
    first = calculate_registered_indicators(frame, configs)
    second = calculate_registered_indicators(frame, configs)
    assert first.equals(second)
    assert {"ma20", "ema20", "boll_mid20", "rsi14", "macd", "k", "d", "j", "atr14", "obv", "vwap"}.issubset(first.columns)


def test_indicator_selection_supports_add_remove_and_ordered_reconfiguration():
    config = [{"key": "MA", "params": {"period": 20}}, {"key": "RSI", "params": {}}]
    with_second_ma = add_indicator_selection(config, "MA", {"period": 60}, position=1)
    assert [item["params"] for item in with_second_ma] == [{"period": 20}, {"period": 60}, {"period": 14}]
    moved = move_indicator_selection(with_second_ma, 2, 0)
    assert [item["key"] for item in moved] == ["RSI", "MA", "MA"]
    removed = remove_indicator_selection(moved, 1)
    assert removed == [{"key": "RSI", "params": {"period": 14}}, {"key": "MA", "params": {"period": 60}}]


def test_indicator_selection_operations_fail_closed_for_bad_positions():
    config = [{"key": "MA", "params": {"period": 20}}]
    with pytest.raises(IndexError):
        remove_indicator_selection(config, 2)
    with pytest.raises(IndexError):
        move_indicator_selection(config, 0, 2)


def test_default_indicator_layout_is_visible_and_conservative():
    config = build_default_indicator_config()
    assert [item["key"] for item in config] == ["MA", "BOLL", "MACD"]
    assert sum(get_indicator_spec(item["key"]).pane == "panel" for item in config) == 1


def test_indicator_layout_limits_panels_and_keeps_overlay_visibility_explicit():
    config = [{"key": key} for key in ("MA", "RSI", "MACD", "KDJ", "ATR")]
    with pytest.raises(ValueError, match="at most 3"):
        validate_indicator_layout(config)
    visible = validate_indicator_layout(config[:4], max_panels=3)
    assert [item["key"] for item in visible] == ["MA", "RSI", "MACD", "KDJ"]
    assert validate_indicator_layout([{ "key": "MA" }], max_panels=0) == [{"key": "MA", "params": {"period": 20}}]


def test_indicator_panel_order_changes_only_panel_order():
    config = [{"key": key} for key in ("MACD", "MA", "RSI", "BOLL")]
    ordered = order_indicator_config(config, panel_order=["RSI", "MACD"])
    assert [item["key"] for item in ordered] == ["MA", "BOLL", "RSI", "MACD"]


def test_indicator_calculation_uses_same_semantics_after_period_aggregation():
    from portfolio_app.market_periods import aggregate_ohlcv

    daily = _market_frame()
    config = [{"key": "MA", "params": {"period": 3}}, {"key": "RSI", "params": {"period": 3}}]
    for period in ("1d", "1w", "1m"):
        aggregated = aggregate_ohlcv(daily, period)
        calculated = calculate_registered_indicators(aggregated, config)
        assert len(calculated) == len(aggregated)
        assert calculated["ma3"].iloc[0] == calculated["close"].iloc[0]
        valid_rsi = calculated["rsi3"].dropna()
        assert not valid_rsi.empty
        assert valid_rsi.between(0, 100).all()
