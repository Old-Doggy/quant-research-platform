"""Deterministic price-volume factors for the offline research workspace."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .factor_contracts import DisclosureStatus, FactorDirection, FactorSpec, FactorStatus


class FactorComputeError(ValueError):
    """Raised when the input data cannot support the requested factors."""


@dataclass(frozen=True)
class _FactorDefinition:
    factor_id: str
    name: str
    family: str
    input_fields: tuple[str, ...]
    input_units: dict[str, str]
    output_unit: str
    direction: FactorDirection
    window: int

    def to_spec(self) -> FactorSpec:
        return FactorSpec(
            factor_id=self.factor_id,
            name=self.name,
            version="1.0.0",
            family=self.family,
            input_fields=self.input_fields,
            input_units=self.input_units,
            output_unit=self.output_unit,
            direction=self.direction,
            window=self.window,
            available_at="2026-10-29T00:00:00Z",
            price_convention="raw_ohlcv",
            missing_value_policy="preserve_nan_until_warmup",
            compute_status=FactorStatus.COMPUTABLE,
            disclosure_status=DisclosureStatus.PUBLIC_DEMO,
            data_dependencies=("canonical_daily_ohlcv",),
            asset_scope=("equity",),
        )


_DEFINITIONS = (
    _FactorDefinition("basic.return_1d", "1D Return", "price_return", ("close",), {"close": "currency_per_share"}, "return", FactorDirection.HIGHER_IS_BETTER, 1),
    _FactorDefinition("basic.return_5d", "5D Return", "price_return", ("close",), {"close": "currency_per_share"}, "return", FactorDirection.HIGHER_IS_BETTER, 5),
    _FactorDefinition("basic.return_20d", "20D Return", "price_return", ("close",), {"close": "currency_per_share"}, "return", FactorDirection.HIGHER_IS_BETTER, 20),
    _FactorDefinition("basic.return_60d", "60D Return", "price_return", ("close",), {"close": "currency_per_share"}, "return", FactorDirection.HIGHER_IS_BETTER, 60),
    _FactorDefinition("basic.reversal_5d", "5D Reversal", "price_reversal", ("close",), {"close": "currency_per_share"}, "return", FactorDirection.HIGHER_IS_BETTER, 5),
    _FactorDefinition("basic.realized_volatility_20d", "20D Realized Volatility", "price_volatility", ("close",), {"close": "currency_per_share"}, "return_std", FactorDirection.LOWER_IS_BETTER, 20),
    _FactorDefinition("basic.atr_ratio_14d", "14D ATR Ratio", "range_volatility", ("high", "low", "close"), {"high": "currency_per_share", "low": "currency_per_share", "close": "currency_per_share"}, "ratio", FactorDirection.LOWER_IS_BETTER, 14),
    _FactorDefinition("basic.ma_deviation_20d", "20D Moving Average Deviation", "price_trend", ("close",), {"close": "currency_per_share"}, "ratio", FactorDirection.TWO_SIDED, 20),
    _FactorDefinition("basic.volume_ratio_20d", "20D Volume Ratio", "volume_activity", ("vol",), {"vol": "shares"}, "ratio", FactorDirection.TWO_SIDED, 20),
    _FactorDefinition("basic.price_volume_corr_20d", "20D Price Volume Correlation", "price_volume", ("close", "vol"), {"close": "currency_per_share", "vol": "shares"}, "correlation", FactorDirection.TWO_SIDED, 20),
    _FactorDefinition("basic.range_position_20d", "20D Range Position", "price_range", ("high", "low", "close"), {"high": "currency_per_share", "low": "currency_per_share", "close": "currency_per_share"}, "ratio", FactorDirection.TWO_SIDED, 20),
    _FactorDefinition("basic.illiquidity", "Amihud Illiquidity", "liquidity", ("close", "amount"), {"close": "currency_per_share", "amount": "currency"}, "return_per_currency", FactorDirection.LOWER_IS_BETTER, 1),
)

BASIC_FACTOR_SPECS = tuple(definition.to_spec() for definition in _DEFINITIONS)


def _validate_frame(frame: pd.DataFrame, required_inputs: set[str]) -> None:
    if frame is None or frame.empty:
        raise FactorComputeError("market frame cannot be empty")
    required = {"trade_date", "symbol", *required_inputs}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise FactorComputeError(f"missing factor inputs: {', '.join(missing)}")
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    if dates.isna().any():
        raise FactorComputeError("trade_date contains invalid values")
    for column in required_inputs:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any():
            raise FactorComputeError(f"factor input {column} contains missing or non-numeric values")
    if required_inputs.intersection({"open", "high", "low", "close"}):
        price_columns = sorted(required_inputs.intersection({"open", "high", "low", "close"}))
        prices = frame[price_columns].apply(pd.to_numeric, errors="coerce")
        if (prices <= 0).any().any():
            raise FactorComputeError("factor price inputs must be positive")
        if {"open", "high", "low", "close"}.issubset(required_inputs) and (
            (prices["high"] < prices[["open", "close"]].max(axis=1)).any()
            or (prices["low"] > prices[["open", "close"]].min(axis=1)).any()
            or (prices["high"] < prices["low"]).any()
        ):
            raise FactorComputeError("factor OHLC inputs are inconsistent")
    if "vol" in required_inputs and (pd.to_numeric(frame["vol"], errors="coerce") < 0).any():
        raise FactorComputeError("volume cannot be negative")
    if "amount" in required_inputs and (pd.to_numeric(frame["amount"], errors="coerce") < 0).any():
        raise FactorComputeError("amount cannot be negative")


def _group_rolling(frame: pd.DataFrame, column: str, window: int, operation: str) -> pd.Series:
    grouped = frame.groupby("symbol", sort=False)[column]
    rolling = grouped.rolling(window, min_periods=window)
    if operation == "mean":
        return rolling.mean().reset_index(level=0, drop=True)
    if operation == "min":
        return rolling.min().reset_index(level=0, drop=True)
    if operation == "max":
        return rolling.max().reset_index(level=0, drop=True)
    if operation == "std":
        return rolling.std(ddof=0).reset_index(level=0, drop=True)
    raise FactorComputeError(f"unsupported rolling operation: {operation}")


def compute_basic_factors(frame: pd.DataFrame, factor_ids: set[str] | None = None) -> pd.DataFrame:
    """Compute the first twelve price-volume factors without future information.

    Windows are measured in rows within each symbol's sorted session history.
    Warm-up observations remain ``NaN``. The input row order is restored before
    returning so callers can safely join results to their original records.
    """
    available_ids = {spec.factor_id for spec in BASIC_FACTOR_SPECS}
    selected_ids = set(factor_ids) if factor_ids is not None else available_ids
    unknown_ids = selected_ids.difference(available_ids)
    if unknown_ids:
        raise FactorComputeError(f"unknown factor ids: {', '.join(sorted(unknown_ids))}")
    input_by_factor = {definition.factor_id: set(definition.input_fields) for definition in _DEFINITIONS}
    required_inputs = set().union(*(input_by_factor[factor_id] for factor_id in selected_ids))
    _validate_frame(frame, required_inputs)
    result = frame.copy(deep=True)
    result["_input_order"] = np.arange(len(result))
    result["trade_date"] = pd.to_datetime(result["trade_date"])
    result["symbol"] = result["symbol"].astype(str)
    result = result.sort_values(["symbol", "trade_date", "_input_order"], kind="mergesort").reset_index(drop=True)
    for column in ("open", "high", "low", "close", "vol", "amount"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        else:
            result[column] = np.nan

    close = result["close"]
    high = result["high"]
    low = result["low"]
    volume = result["vol"] if "vol" in result else pd.Series(np.nan, index=result.index)
    amount = result["amount"] if "amount" in result else pd.Series(np.nan, index=result.index)
    grouped_close = result.groupby("symbol", sort=False)["close"]
    grouped_volume = result.groupby("symbol", sort=False)["vol"] if "vol" in result else None

    result["return_1d"] = grouped_close.pct_change(1)
    result["return_5d"] = grouped_close.pct_change(5)
    result["return_20d"] = grouped_close.pct_change(20)
    result["return_60d"] = grouped_close.pct_change(60)
    result["reversal_5d"] = -result["return_5d"]
    result["realized_volatility_20d"] = _group_rolling(result.assign(_return=result["return_1d"]), "_return", 20, "std")

    previous_close = grouped_close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    atr14 = (
        pd.DataFrame({"symbol": result["symbol"], "true_range": true_range})
        .groupby("symbol", sort=False)["true_range"]
        .rolling(14, min_periods=14)
        .mean()
        .reset_index(level=0, drop=True)
    )
    result["atr_ratio_14d"] = atr14 / close

    moving_average20 = _group_rolling(result, "close", 20, "mean")
    result["ma_deviation_20d"] = close / moving_average20 - 1
    volume_average20 = _group_rolling(result, "vol", 20, "mean") if "vol" in result else pd.Series(np.nan, index=result.index)
    result["volume_ratio_20d"] = volume / volume_average20

    if grouped_volume is not None:
        volume_change = grouped_volume.pct_change(1)
        price_volume_corr = pd.Series(np.nan, index=result.index, dtype=float)
        for _, indices in result.groupby("symbol", sort=False).groups.items():
            price_volume_corr.loc[indices] = (
                result.loc[indices, "return_1d"]
                .rolling(20, min_periods=20)
                .corr(volume_change.loc[indices])
                .to_numpy()
            )
        result["price_volume_corr_20d"] = price_volume_corr
    else:
        result["price_volume_corr_20d"] = np.nan
    rolling_low20 = _group_rolling(result, "low", 20, "min")
    rolling_high20 = _group_rolling(result, "high", 20, "max")
    range_width = (rolling_high20 - rolling_low20).replace(0, np.nan)
    result["range_position_20d"] = (close - rolling_low20) / range_width
    result["illiquidity"] = result["return_1d"].abs() / amount.replace(0, np.nan)

    duplicate_keys = result.duplicated(["symbol", "trade_date"], keep=False)
    if duplicate_keys.any():
        raise FactorComputeError("duplicate symbol/trade_date rows are not allowed")
    output_columns = list(frame.columns)
    computed_columns = [
        "return_1d", "return_5d", "return_20d", "return_60d", "reversal_5d", "realized_volatility_20d",
        "atr_ratio_14d", "ma_deviation_20d", "volume_ratio_20d", "price_volume_corr_20d", "range_position_20d", "illiquidity",
    ]
    selected_columns = [
        column for column, definition in zip(computed_columns, _DEFINITIONS)
        if definition.factor_id in selected_ids
    ]
    result = result.sort_values("_input_order", kind="mergesort").drop(columns="_input_order").reset_index(drop=True)
    return result[output_columns + selected_columns]
