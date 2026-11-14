from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .indicator_math import (
    atr,
    bias,
    bollinger_bands,
    cci,
    cumulative_vwap,
    dmi_adx,
    donchian_channels,
    ema,
    kdj,
    macd,
    moving_average,
    obv,
    rate_of_change,
    rsi,
    volume_ratio,
    williams_r,
)


@dataclass(frozen=True)
class IndicatorSpec:
    """Stable metadata used by the chart configurator and calculation layer."""

    key: str
    label: str
    pane: str
    parameters: Mapping[str, Mapping[str, Any]]


def _period_parameter(default: int = 20, minimum: int = 1, maximum: int = 500) -> dict[str, Any]:
    return {"type": "int", "default": default, "min": minimum, "max": maximum, "step": 1}


INDICATOR_REGISTRY: dict[str, IndicatorSpec] = {
    "MA": IndicatorSpec("MA", "Moving Average", "overlay", {"period": _period_parameter()}),
    "EMA": IndicatorSpec("EMA", "Exponential Moving Average", "overlay", {"period": _period_parameter()}),
    "BOLL": IndicatorSpec(
        "BOLL",
        "Bollinger Bands",
        "overlay",
        {"period": _period_parameter(), "stddev": {"type": "float", "default": 2.0, "min": 0.1, "max": 6.0, "step": 0.1}},
    ),
    "RSI": IndicatorSpec("RSI", "Relative Strength Index", "panel", {"period": {**_period_parameter(14), "max": 100}}),
    "MACD": IndicatorSpec(
        "MACD",
        "Moving Average Convergence Divergence",
        "panel",
        {"fast": _period_parameter(12, 1, 100), "slow": _period_parameter(26, 2, 200), "signal": _period_parameter(9, 1, 100)},
    ),
    "KDJ": IndicatorSpec(
        "KDJ",
        "KDJ",
        "panel",
        {"period": {**_period_parameter(9), "max": 100}, "smooth": _period_parameter(3, 1, 20)},
    ),
    "ATR": IndicatorSpec("ATR", "Average True Range", "panel", {"period": {**_period_parameter(14), "max": 100}}),
    "OBV": IndicatorSpec("OBV", "On-Balance Volume", "panel", {}),
    "VWAP": IndicatorSpec("VWAP", "累计日线成交量加权价", "overlay", {}),
    "ROC": IndicatorSpec("ROC", "Rate of Change", "panel", {"period": _period_parameter()}),
    "CCI": IndicatorSpec("CCI", "Commodity Channel Index", "panel", {"period": _period_parameter()}),
    "DMI": IndicatorSpec("DMI", "Directional Movement Index / ADX", "panel", {"period": {**_period_parameter(14), "max": 100}}),
    "BIAS": IndicatorSpec("BIAS", "乖离率", "panel", {"period": _period_parameter()}),
    "WR": IndicatorSpec("WR", "Williams %R", "panel", {"period": {**_period_parameter(14), "max": 100}}),
    "DONCHIAN": IndicatorSpec("DONCHIAN", "Donchian Channel", "overlay", {"period": _period_parameter()}),
    "VOL_MA": IndicatorSpec("VOL_MA", "Volume Moving Average", "panel", {"period": _period_parameter()}),
    "VOLUME_RATIO": IndicatorSpec("VOLUME_RATIO", "Volume Ratio", "panel", {"period": _period_parameter()}),
}


def build_default_indicator_config() -> list[dict[str, Any]]:
    """Return the conservative first-render configuration used by the workbench."""
    return normalize_indicator_config([
        {"key": "MA", "params": {"period": 20}},
        {"key": "BOLL", "params": {"period": 20, "stddev": 2.0}},
        {"key": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}},
    ])


def get_indicator_spec(key: str) -> IndicatorSpec:
    normalized = str(key).strip().upper()
    try:
        return INDICATOR_REGISTRY[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown indicator: {key}") from exc


def _validate_parameter(spec: IndicatorSpec, name: str, value: Any) -> int | float:
    definition = spec.parameters[name]
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{spec.key}.{name} must be numeric") from exc
    if not np.isfinite(numeric):
        raise ValueError(f"{spec.key}.{name} must be finite")
    if numeric < definition["min"] or numeric > definition["max"]:
        raise ValueError(f"{spec.key}.{name} must be between {definition['min']} and {definition['max']}")
    if definition["type"] == "int":
        if not numeric.is_integer():
            raise ValueError(f"{spec.key}.{name} must be an integer")
        return int(numeric)
    return numeric


def normalize_indicator_config(config: list[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize ordered indicator selections and validate their parameters."""
    normalized: list[dict[str, Any]] = []
    for item in config or []:
        if isinstance(item, str):
            key, supplied = item, {}
        else:
            key, supplied = item.get("key", ""), item.get("params") or {}
        spec = get_indicator_spec(str(key))
        unknown = sorted(set(supplied) - set(spec.parameters))
        if unknown:
            raise ValueError(f"unknown parameter for {spec.key}: {unknown[0]}")
        params: dict[str, Any] = {}
        for name, definition in spec.parameters.items():
            params[name] = _validate_parameter(spec, name, supplied.get(name, definition["default"]))
        if spec.key == "MACD" and params["fast"] >= params["slow"]:
            raise ValueError("MACD.fast must be smaller than MACD.slow")
        normalized.append({"key": spec.key, "params": params})
    return normalized


def validate_indicator_layout(
    config: list[Mapping[str, Any]] | None,
    *,
    max_panels: int = 3,
) -> list[dict[str, Any]]:
    """Normalize a visible indicator layout and enforce its pane budget.

    Visibility is represented by selection: an indicator absent from ``config``
    is hidden.  The overlay order is preserved, while panel count is bounded so
    a narrow chart cannot become an unreadable stack of subplots.
    """
    if isinstance(max_panels, bool) or not isinstance(max_panels, int) or max_panels < 0:
        raise ValueError("max_panels must be a non-negative integer")
    normalized = normalize_indicator_config(config)
    panel_count = sum(get_indicator_spec(item["key"]).pane == "panel" for item in normalized)
    if panel_count > max_panels:
        raise ValueError(f"indicator layout supports at most {max_panels} panels")
    return normalized


def order_indicator_config(
    config: list[Mapping[str, Any]] | None,
    *,
    panel_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Order panels without moving main-chart overlays or changing visibility."""
    normalized = validate_indicator_layout(config)
    requested = [str(key).strip().upper() for key in (panel_order or [])]
    if len(set(requested)) != len(requested):
        raise ValueError("panel_order cannot contain duplicates")
    panel_keys = [item["key"] for item in normalized if get_indicator_spec(item["key"]).pane == "panel"]
    unknown = [key for key in requested if key not in panel_keys]
    if unknown:
        raise ValueError(f"panel_order contains an unselected panel: {unknown[0]}")
    requested += [key for key in panel_keys if key not in requested]
    positions = {key: index for index, key in enumerate(requested)}
    overlays = [item for item in normalized if get_indicator_spec(item["key"]).pane == "overlay"]
    panels = sorted(
        (item for item in normalized if get_indicator_spec(item["key"]).pane == "panel"),
        key=lambda item: positions[item["key"]],
    )
    return overlays + panels


def add_indicator_selection(
    config: list[Mapping[str, Any]] | None,
    key: str,
    params: Mapping[str, Any] | None = None,
    position: int | None = None,
) -> list[dict[str, Any]]:
    """Return a normalized config with one indicator inserted at ``position``."""
    normalized = normalize_indicator_config(config)
    selection = normalize_indicator_config([{"key": key, "params": dict(params or {})}])[0]
    insert_at = len(normalized) if position is None else position
    if insert_at < 0 or insert_at > len(normalized):
        raise IndexError("indicator insertion position is out of range")
    normalized.insert(insert_at, selection)
    return normalized


def remove_indicator_selection(config: list[Mapping[str, Any]] | None, position: int) -> list[dict[str, Any]]:
    """Return a normalized config without the item at ``position``."""
    normalized = normalize_indicator_config(config)
    if position < 0 or position >= len(normalized):
        raise IndexError("indicator removal position is out of range")
    del normalized[position]
    return normalized


def move_indicator_selection(config: list[Mapping[str, Any]] | None, position: int, new_position: int) -> list[dict[str, Any]]:
    """Return a normalized config with one item moved to ``new_position``."""
    normalized = normalize_indicator_config(config)
    if position < 0 or position >= len(normalized):
        raise IndexError("indicator position is out of range")
    if new_position < 0 or new_position >= len(normalized):
        raise IndexError("indicator destination is out of range")
    item = normalized.pop(position)
    normalized.insert(new_position, item)
    return normalized


def _market_series(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    required = {"close", "high", "low"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"indicator frame is missing required columns: {', '.join(missing)}")
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    volume_column = "vol" if "vol" in frame.columns else "volume" if "volume" in frame.columns else None
    volume = pd.to_numeric(frame[volume_column], errors="coerce").fillna(0) if volume_column else pd.Series(0.0, index=frame.index)
    return close, high, low, volume, close.shift(1)


def _calculate_registered_indicators_legacy(frame: pd.DataFrame, config: list[Mapping[str, Any]] | None) -> pd.DataFrame:
    """Calculate the selected registry indicators without mutating ``frame``."""
    result = frame.copy()
    close, high, low, volume, previous_close = _market_series(result)
    for selection in normalize_indicator_config(config):
        key = selection["key"]
        params = selection["params"]
        if key == "MA":
            period = params["period"]
            result[f"ma{period}"] = close.rolling(period, min_periods=1).mean()
        elif key == "EMA":
            period = params["period"]
            result[f"ema{period}"] = close.ewm(span=period, adjust=False, min_periods=1).mean()
        elif key == "BOLL":
            period, stddev = params["period"], params["stddev"]
            middle = close.rolling(period, min_periods=1).mean()
            deviation = close.rolling(period, min_periods=1).std(ddof=0)
            result[f"boll_mid{period}"] = middle
            result[f"boll_upper{period}"] = middle + stddev * deviation
            result[f"boll_lower{period}"] = middle - stddev * deviation
        elif key == "RSI":
            period = params["period"]
            delta = close.diff()
            gains = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
            losses = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
            relative = gains / losses.replace(0, np.nan)
            result[f"rsi{period}"] = (100 - 100 / (1 + relative)).where(losses.ne(0), 100.0).clip(0, 100)
        elif key == "MACD":
            fast, slow, signal = params["fast"], params["slow"], params["signal"]
            macd = close.ewm(span=fast, adjust=False, min_periods=1).mean() - close.ewm(span=slow, adjust=False, min_periods=1).mean()
            result["macd"] = macd
            result["macd_signal"] = macd.ewm(span=signal, adjust=False, min_periods=1).mean()
            result["macd_hist"] = result["macd"] - result["macd_signal"]
        elif key == "KDJ":
            period, smooth = params["period"], params["smooth"]
            rolling_low = low.rolling(period, min_periods=1).min()
            rolling_high = high.rolling(period, min_periods=1).max()
            denominator = (rolling_high - rolling_low).replace(0, np.nan)
            rsv = ((close - rolling_low) / denominator * 100).fillna(50)
            result["k"] = rsv.ewm(alpha=1 / smooth, adjust=False, min_periods=1).mean()
            result["d"] = result["k"].ewm(alpha=1 / smooth, adjust=False, min_periods=1).mean()
            result["j"] = 3 * result["k"] - 2 * result["d"]
        elif key == "ATR":
            period = params["period"]
            true_range = pd.concat([high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
            result[f"atr{period}"] = true_range.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
        elif key == "OBV":
            direction = np.sign(close.diff().fillna(0))
            result["obv"] = (direction * volume).cumsum()
        elif key == "VWAP":
            typical_price = (high + low + close) / 3
            cumulative_volume = volume.cumsum()
            result["vwap"] = (typical_price * volume).cumsum().div(cumulative_volume.replace(0, np.nan)).ffill()
    return result


def calculate_registered_indicators(frame: pd.DataFrame, config: list[Mapping[str, Any]] | None) -> pd.DataFrame:
    """Calculate registry selections through the shared numerical functions."""
    from .indicator_math import calculate_indicators

    return calculate_indicators(frame, config)


def add_chart_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Add display-oriented technical indicators without mutating the input frame."""
    result = frame.copy()
    if "vol" not in result:
        result["vol"] = 0.0
    calculated = calculate_registered_indicators(
        result,
        [
            {"key": "MA", "params": {"period": 5}},
            {"key": "MA", "params": {"period": 20}},
            {"key": "MA", "params": {"period": 60}},
            {"key": "EMA", "params": {"period": 12}},
            {"key": "EMA", "params": {"period": 26}},
            {"key": "BOLL", "params": {"period": 20, "stddev": 2.0}},
            {"key": "RSI", "params": {"period": 14}},
            {"key": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}},
            {"key": "KDJ", "params": {"period": 9, "smooth": 3}},
            {"key": "ATR", "params": {"period": 14}},
            {"key": "VOL_MA", "params": {"period": 5}},
            {"key": "VOL_MA", "params": {"period": 20}},
        ],
    )
    result = calculated
    result["bb_mid"] = result["boll_mid20"]
    result["bb_upper"] = result["boll_upper20"]
    result["bb_lower"] = result["boll_lower20"]
    result["rsv"] = result["k"]
    return result
