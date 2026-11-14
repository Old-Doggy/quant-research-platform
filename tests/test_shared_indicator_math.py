from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.indicator_math import (
    atr,
    bias,
    bollinger_bands,
    cci,
    cumulative_vwap,
    dmi_adx,
    donchian_channels,
    ema,
    kdj,
    moving_average,
    obv,
    rate_of_change,
    rsi,
    volume_ratio,
    williams_r,
)
from portfolio_app.indicators import INDICATOR_REGISTRY, calculate_registered_indicators
from portfolio_app.strategies import add_features


def bars(rows: int = 80) -> pd.DataFrame:
    close = pd.Series(np.linspace(10.0, 18.0, rows), dtype=float)
    return pd.DataFrame(
        {
            "trade_date": pd.bdate_range("2026-01-02", periods=rows),
            "symbol": "AAA",
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "vol": np.arange(1000, 1000 + rows, dtype=float),
            "amount": close * np.arange(1000, 1000 + rows, dtype=float),
        }
    )


def test_shared_functions_match_hand_calculation_for_basic_indicators() -> None:
    frame = bars()
    close, high, low, volume = frame["close"], frame["high"], frame["low"], frame["vol"]

    assert moving_average(close, 5).iloc[4] == pytest.approx(close.iloc[:5].mean())
    assert ema(close, 5).iloc[0] == pytest.approx(close.iloc[0])
    assert rate_of_change(close, 5).iloc[5] == pytest.approx(close.iloc[5] / close.iloc[0] * 100 - 100)
    assert bias(close, 5).iloc[5] == pytest.approx((close.iloc[5] / close.iloc[1:6].mean() - 1) * 100)
    assert volume_ratio(volume, 5).iloc[5] == pytest.approx(volume.iloc[5] / volume.iloc[1:6].mean())


def test_shared_functions_cover_range_momentum_and_volume_indicators() -> None:
    frame = bars()
    bands = bollinger_bands(frame["close"], 5, 2.0)
    k_values = kdj(frame["close"], frame["high"], frame["low"], 9, 3)
    dmi = dmi_adx(frame["high"], frame["low"], frame["close"], 14)
    donchian = donchian_channels(frame["high"], frame["low"], 20)

    assert set(bands) == {"middle", "upper", "lower"}
    assert set(k_values) == {"k", "d", "j"}
    assert set(dmi) == {"plus_di", "minus_di", "adx"}
    assert set(donchian) == {"upper", "middle", "lower"}
    assert williams_r(frame["close"], frame["high"], frame["low"], 14).dropna().between(-100, 0).all()
    assert cci(frame["high"], frame["low"], frame["close"], 20).notna().any()
    assert atr(frame["high"], frame["low"], frame["close"], 14).notna().any()
    assert obv(frame["close"], frame["vol"]).iloc[-1] > 0
    assert cumulative_vwap(frame["high"], frame["low"], frame["close"], frame["vol"]).notna().all()


def test_registry_exposes_shared_indicator_set_and_accurate_daily_vwap_label() -> None:
    expected = {"MA", "EMA", "BOLL", "RSI", "MACD", "KDJ", "ATR", "OBV", "VWAP", "ROC", "CCI", "DMI", "BIAS", "WR", "DONCHIAN", "VOL_MA", "VOLUME_RATIO"}
    assert expected.issubset(INDICATOR_REGISTRY)
    assert "累计" in INDICATOR_REGISTRY["VWAP"].label
    assert "盘中" not in INDICATOR_REGISTRY["VWAP"].label

    calculated = calculate_registered_indicators(
        frame=bars(),
        config=[{"key": "ROC"}, {"key": "CCI"}, {"key": "DMI"}, {"key": "BIAS"}, {"key": "WR"}, {"key": "DONCHIAN"}, {"key": "VOL_MA"}, {"key": "VOLUME_RATIO"}],
    )
    assert {"roc20", "cci20", "plus_di14", "minus_di14", "adx14", "bias20", "wr14", "donchian_upper20", "donchian_lower20", "vol_ma20", "volume_ratio20"}.issubset(calculated.columns)


def test_strategy_features_reuse_shared_indicator_values() -> None:
    frame = bars().assign(return_=lambda data: data["close"].pct_change().fillna(0), roe=12.0, pb=2.0)
    frame["return"] = frame["return_"]
    result = add_features(frame, params={"fast_window": 20, "slow_window": 60, "lookback_window": 20})

    assert result["ma20"].equals(moving_average(frame["close"], 20, min_periods=5))
    assert result["ma60"].equals(moving_average(frame["close"], 60, min_periods=15))
    pd.testing.assert_series_equal(result["rsi14"], rsi(frame["close"], 14), check_names=False)
    pd.testing.assert_series_equal(result["ret20"], rate_of_change(frame["close"], 20) / 100, check_names=False)


def test_shared_indicator_functions_reject_invalid_periods() -> None:
    with pytest.raises(ValueError):
        moving_average(pd.Series([1.0]), 0)
    with pytest.raises(ValueError):
        ema(pd.Series([1.0]), -1)
