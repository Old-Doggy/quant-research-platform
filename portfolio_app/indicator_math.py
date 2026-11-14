"""Shared, deterministic technical-indicator calculations.

The functions in this module are deliberately free of UI and strategy code.
They return aligned Series or named component mappings so the chart registry,
strategy features, and later factor adapters can share one numerical source.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def _period(period: int) -> int:
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("period must be a positive integer")
    return period


def _aligned(*series: pd.Series) -> tuple[pd.Series, ...]:
    if not series:
        raise ValueError("at least one series is required")
    converted = tuple(pd.to_numeric(item, errors="coerce") for item in series)
    index = converted[0].index
    if any(not item.index.equals(index) for item in converted[1:]):
        raise ValueError("indicator inputs must share the same index")
    return converted


def moving_average(series: pd.Series, period: int, min_periods: int | None = 1) -> pd.Series:
    period = _period(period)
    minimum = period if min_periods is None else int(min_periods)
    if minimum < 1 or minimum > period:
        raise ValueError("min_periods must be between 1 and period")
    return _aligned(series)[0].rolling(period, min_periods=minimum).mean()


def ema(series: pd.Series, period: int, min_periods: int | None = 1) -> pd.Series:
    period = _period(period)
    minimum = period if min_periods is None else int(min_periods)
    if minimum < 1 or minimum > period:
        raise ValueError("min_periods must be between 1 and period")
    return _aligned(series)[0].ewm(span=period, adjust=False, min_periods=minimum).mean()


def rate_of_change(close: pd.Series, period: int) -> pd.Series:
    close = _aligned(close)[0]
    return close.pct_change(_period(period)) * 100


def bias(close: pd.Series, period: int, min_periods: int | None = 1) -> pd.Series:
    close = _aligned(close)[0]
    return (close / moving_average(close, period, min_periods=min_periods) - 1) * 100


def bollinger_bands(close: pd.Series, period: int, stddev: float, min_periods: int | None = 1) -> dict[str, pd.Series]:
    close = _aligned(close)[0]
    if not np.isfinite(float(stddev)) or float(stddev) <= 0:
        raise ValueError("stddev must be positive and finite")
    period = _period(period)
    middle = moving_average(close, period, min_periods=min_periods)
    minimum = period if min_periods is None else int(min_periods)
    deviation = close.rolling(period, min_periods=minimum).std(ddof=0)
    return {"middle": middle, "upper": middle + float(stddev) * deviation, "lower": middle - float(stddev) * deviation}


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    close = _aligned(close)[0]
    period = _period(period)
    delta = close.diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
    losses = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
    relative = gains / losses.replace(0, np.nan)
    return (100 - 100 / (1 + relative)).where(losses.ne(0), 100.0).clip(0, 100)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, pd.Series]:
    fast, slow, signal = _period(fast), _period(slow), _period(signal)
    if fast >= slow:
        raise ValueError("fast period must be smaller than slow period")
    close = _aligned(close)[0]
    line = ema(close, fast) - ema(close, slow)
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return {"macd": line, "signal": signal_line, "hist": line - signal_line}


def kdj(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 9, smooth: int = 3) -> dict[str, pd.Series]:
    close, high, low = _aligned(close, high, low)
    period, smooth = _period(period), _period(smooth)
    rolling_low = low.rolling(period, min_periods=period).min()
    rolling_high = high.rolling(period, min_periods=period).max()
    denominator = (rolling_high - rolling_low).replace(0, np.nan)
    rsv = ((close - rolling_low) / denominator * 100).fillna(50)
    k = rsv.ewm(alpha=1 / smooth, adjust=False, min_periods=smooth).mean()
    d = k.ewm(alpha=1 / smooth, adjust=False, min_periods=smooth).mean()
    return {"k": k, "d": d, "j": 3 * k - 2 * d}


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    high, low, close = _aligned(high, low, close)
    previous_close = close.shift(1)
    return pd.concat([high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return true_range(high, low, close).ewm(alpha=1 / _period(period), adjust=False, min_periods=period).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    close, volume = _aligned(close, volume)
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def cumulative_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    high, low, close, volume = _aligned(high, low, close, volume)
    typical_price = (high + low + close) / 3
    cumulative_volume = volume.cumsum()
    return (typical_price * volume).cumsum().div(cumulative_volume.replace(0, np.nan)).ffill()


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    volume = _aligned(volume)[0]
    return volume / volume.rolling(_period(period), min_periods=period).mean()


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    high, low, close = _aligned(high, low, close)
    period = _period(period)
    typical = (high + low + close) / 3
    middle = typical.rolling(period, min_periods=period).mean()
    deviation = typical.rolling(period, min_periods=period).apply(lambda values: np.mean(np.abs(values - values.mean())), raw=True)
    return (typical - middle) / (0.015 * deviation.replace(0, np.nan))


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / _period(period), adjust=False, min_periods=period).mean()


def dmi_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> dict[str, pd.Series]:
    high, low, close = _aligned(high, low, close)
    period = _period(period)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = true_range(high, low, close)
    atr_value = _wilder(tr, period)
    plus_di = 100 * _wilder(plus_dm, period).div(atr_value.replace(0, np.nan))
    minus_di = 100 * _wilder(minus_dm, period).div(atr_value.replace(0, np.nan))
    denominator = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs().div(denominator)
    return {"plus_di": plus_di, "minus_di": minus_di, "adx": _wilder(dx, period)}


def donchian_channels(high: pd.Series, low: pd.Series, period: int = 20) -> dict[str, pd.Series]:
    high, low = _aligned(high, low)
    upper = high.rolling(_period(period), min_periods=period).max()
    lower = low.rolling(_period(period), min_periods=period).min()
    return {"upper": upper, "middle": (upper + lower) / 2, "lower": lower}


def williams_r(close: pd.Series, high: pd.Series, low: pd.Series, period: int = 14) -> pd.Series:
    close, high, low = _aligned(close, high, low)
    channels = donchian_channels(high, low, period)
    denominator = (channels["upper"] - channels["lower"]).replace(0, np.nan)
    return -100 * (channels["upper"] - close).div(denominator)


def calculate_indicators(frame: pd.DataFrame, config: list[Mapping[str, object]] | None) -> pd.DataFrame:
    """Calculate shared indicators for a canonical single-symbol frame."""
    from .indicators import normalize_indicator_config

    result = frame.copy()
    normalized = normalize_indicator_config(config)
    required = {"close", "high", "low"}
    if any(item["key"] in {"OBV", "VWAP", "VOL_MA", "VOLUME_RATIO"} for item in normalized):
        required.add("vol")
    missing = sorted(required - set(result.columns))
    if missing:
        raise ValueError(f"indicator frame is missing required columns: {', '.join(missing)}")
    close = pd.to_numeric(result["close"], errors="coerce")
    high = pd.to_numeric(result["high"], errors="coerce")
    low = pd.to_numeric(result["low"], errors="coerce")
    volume = pd.to_numeric(result["vol"], errors="coerce")
    for item in normalized:
        key, params = item["key"], item["params"]
        if key == "MA":
            result[f"ma{params['period']}"] = moving_average(close, params["period"])
        elif key == "EMA":
            result[f"ema{params['period']}"] = ema(close, params["period"])
        elif key == "BOLL":
            bands = bollinger_bands(close, params["period"], params["stddev"])
            result[f"boll_mid{params['period']}"] = bands["middle"]
            result[f"boll_upper{params['period']}"] = bands["upper"]
            result[f"boll_lower{params['period']}"] = bands["lower"]
        elif key == "RSI":
            result[f"rsi{params['period']}"] = rsi(close, params["period"])
        elif key == "MACD":
            values = macd(close, params["fast"], params["slow"], params["signal"])
            result["macd"] = values["macd"]
            result["macd_signal"] = values["signal"]
            result["macd_hist"] = values["hist"]
        elif key == "KDJ":
            values = kdj(close, high, low, params["period"], params["smooth"])
            result["k"] = values["k"]
            result["d"] = values["d"]
            result["j"] = values["j"]
        elif key == "ATR":
            result[f"atr{params['period']}"] = atr(high, low, close, params["period"])
        elif key == "OBV":
            result["obv"] = obv(close, volume)
        elif key in {"VWAP", "VWAP_DAILY"}:
            result["vwap"] = cumulative_vwap(high, low, close, volume)
        elif key == "ROC":
            result[f"roc{params['period']}"] = rate_of_change(close, params["period"])
        elif key == "CCI":
            result[f"cci{params['period']}"] = cci(high, low, close, params["period"])
        elif key == "DMI":
            values = dmi_adx(high, low, close, params["period"])
            result[f"plus_di{params['period']}"] = values["plus_di"]
            result[f"minus_di{params['period']}"] = values["minus_di"]
            result[f"adx{params['period']}"] = values["adx"]
        elif key == "BIAS":
            result[f"bias{params['period']}"] = bias(close, params["period"])
        elif key == "WR":
            result[f"wr{params['period']}"] = williams_r(close, high, low, params["period"])
        elif key == "DONCHIAN":
            values = donchian_channels(high, low, params["period"])
            result[f"donchian_upper{params['period']}"] = values["upper"]
            result[f"donchian_middle{params['period']}"] = values["middle"]
            result[f"donchian_lower{params['period']}"] = values["lower"]
        elif key == "VOL_MA":
            result[f"vol_ma{params['period']}"] = moving_average(volume, params["period"])
        elif key == "VOLUME_RATIO":
            result[f"volume_ratio{params['period']}"] = volume_ratio(volume, params["period"])
    return result
