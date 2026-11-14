from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.strategy_rules import compile_strategy_rules
from portfolio_app.strategy_signal import (
    PositionRuleError,
    build_signal_preview,
    evaluate_position_rules,
)


FIELDS = {"close": "price", "open": "price", "high": "price", "low": "price"}


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAA"] * 6,
            "trade_date": pd.date_range("2024-01-01", periods=6),
            "open": [10.0, 10.5, 11.0, 10.8, 10.0, 10.2],
            "high": [10.5, 11.5, 11.5, 11.0, 10.3, 10.4],
            "low": [9.8, 10.2, 10.6, 10.0, 9.0, 10.0],
            "close": [10.2, 11.0, 10.8, 10.2, 9.2, 10.3],
        }
    )


def rules():
    return compile_strategy_rules(
        {"type": "threshold", "field": "close", "operator": ">", "value": 10.0},
        {"type": "threshold", "field": "close", "operator": "<", "value": 9.5},
        field_types=FIELDS,
    )


def test_signal_preview_preserves_full_history_and_exposes_reason_source_and_availability():
    preview = build_signal_preview(
        frame(), rules(), strategy_id="demo", execution_lag_sessions=1,
        feature_sources={"close": {"source": "local_demo", "available_at": "decision_date"}},
        display_start="2024-01-03", display_end="2024-01-05",
    )

    assert len(preview.all_signals) == 6
    assert len(preview.visible_signals) == 3
    assert {item["signal_id"] for item in preview.visible_signals} <= {item["signal_id"] for item in preview.all_signals}
    signal = next(item for item in preview.all_signals if item["side"] == "BUY")
    assert signal["reason_code"] == "buy_rule_true"
    assert signal["evidence"]["fields"] == ["close"]
    assert signal["evidence"]["source"] == "local_demo"
    assert signal["evidence"]["available_at"] == "decision_date"
    assert signal["effective_date"] == "2024-01-02"
    assert preview.metadata["warmup_sessions"] == 0


def test_visible_window_does_not_change_signal_history_or_signal_ids():
    full = build_signal_preview(frame(), rules(), strategy_id="demo", execution_lag_sessions=1)
    narrow = build_signal_preview(
        frame(), rules(), strategy_id="demo", execution_lag_sessions=1,
        display_start="2024-01-03", display_end="2024-01-04",
    )

    assert full.all_signals == narrow.all_signals
    assert narrow.metadata["history_fingerprint"] == full.metadata["history_fingerprint"]


def test_position_rules_hold_until_exit_and_trigger_stop_loss():
    positions = evaluate_position_rules(
        frame(),
        buy_dates={pd.Timestamp("2024-01-01")},
        exit_dates={pd.Timestamp("2024-01-06")},
        stop_loss_pct=0.05,
        take_profit_pct=None,
        execution_lag_sessions=1,
    )

    assert positions.loc[0, "state"] == "PENDING_ENTRY"
    assert positions.loc[1, "state"] == "HOLD"
    assert positions.loc[3, "state"] == "EXIT_STOP_LOSS"
    assert positions.loc[4, "state"] == "FLAT"


def test_ambiguous_ohlc_bar_is_conservative_when_stop_and_take_profit_both_touch():
    bars = frame()
    bars.loc[2, ["high", "low"]] = [12.0, 8.0]
    result = evaluate_position_rules(
        bars,
        buy_dates={pd.Timestamp("2024-01-01")},
        exit_dates=set(),
        stop_loss_pct=0.08,
        take_profit_pct=0.08,
        execution_lag_sessions=1,
    )

    assert result.loc[2, "state"] == "EXIT_UNCERTAIN"
    assert result.loc[2, "reason_code"] == "ambiguous_bar_path"
    assert bool(result.loc[2, "executable"]) is False


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"stop_loss_pct": -0.1, "take_profit_pct": None}, "stop_loss"),
        ({"stop_loss_pct": 0.1, "take_profit_pct": -0.1}, "take_profit"),
        ({"stop_loss_pct": None, "take_profit_pct": None}, "exit"),
    ],
)
def test_position_rule_configuration_fails_closed(kwargs, match):
    with pytest.raises(PositionRuleError, match=match):
        evaluate_position_rules(frame(), buy_dates=set(), exit_dates=set(), execution_lag_sessions=1, **kwargs)
