from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.market_periods import aggregate_ohlcv, build_market_window


def _daily_frame() -> pd.DataFrame:
    dates = pd.to_datetime(
        [
            "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08",
            "2025-01-09", "2025-01-10", "2025-01-13", "2025-01-14", "2025-01-15",
        ]
    )
    return pd.DataFrame(
        {
            "symbol": "AAA",
            "trade_date": dates,
            "open": range(10, 20),
            "high": range(11, 21),
            "low": range(9, 19),
            "close": range(10, 20),
            "pre_close": [9] + list(range(10, 19)),
            "vol": [100] * 10,
            "amount": [1000] * 10,
        }
    )


def test_weekly_ohlcv_uses_first_open_last_close_extremes_and_sums():
    weekly = aggregate_ohlcv(_daily_frame(), "1w")

    assert len(weekly) == 3
    first = weekly.iloc[0]
    assert first["trade_date"] == pd.Timestamp("2025-01-03")
    assert first["period_start"] == "2024-12-30"
    assert first["period_end"] == "2025-01-05"
    assert first["open"] == 10
    assert first["high"] == 12
    assert first["low"] == 9
    assert first["close"] == 11
    assert first["vol"] == 200
    assert first["amount"] == 2000
    assert first["is_complete"] is True
    assert pd.isna(first["pre_close"])
    assert weekly.iloc[1]["pre_close"] == first["close"]


def test_monthly_window_marks_latest_partial_period_and_keeps_calendar_metadata():
    monthly = build_market_window(
        _daily_frame(),
        period="1m",
        start="2025-01-01",
        end="2025-01-15",
    )

    assert monthly["status"] == "READY"
    assert monthly["window"]["start"] == "2025-01-01"
    assert monthly["window"]["end"] == "2025-01-15"
    assert len(monthly["frame"]) == 1
    row = monthly["frame"].iloc[0]
    assert row["period_start"] == "2025-01-01"
    assert row["period_end"] == "2025-01-31"
    assert row["trade_date"] == pd.Timestamp("2025-01-15")
    assert row["is_complete"] is False
    assert monthly["observed_sessions"] == 10
    assert monthly["bars"] == 1


def test_date_window_is_independent_from_period_and_handles_no_rows():
    result = build_market_window(_daily_frame(), period="1d", start="2025-01-06", end="2025-01-08")
    empty = build_market_window(_daily_frame(), period="1w", start="2024-01-01", end="2024-01-31")

    assert result["status"] == "READY"
    assert result["bars"] == 3
    assert result["observed_sessions"] == 3
    assert result["frame"]["trade_date"].min() == pd.Timestamp("2025-01-06")
    assert result["frame"]["trade_date"].max() == pd.Timestamp("2025-01-08")
    assert empty["status"] == "EMPTY"
    assert empty["bars"] == 0
    assert empty["frame"].empty


def test_period_and_dates_are_validated():
    with pytest.raises(ValueError, match="period"):
        aggregate_ohlcv(_daily_frame(), "5m")
    with pytest.raises(ValueError, match="start"):
        build_market_window(_daily_frame(), period="1d", start="2025-01-10", end="2025-01-01")
