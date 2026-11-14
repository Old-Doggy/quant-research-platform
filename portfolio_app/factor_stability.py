"""IC decay, temporal stability and factor-correlation diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .factor_analysis import FactorAnalysisError, compute_ic_series


class FactorStabilityError(ValueError):
    """Raised when stability diagnostics cannot be computed safely."""


@dataclass(frozen=True)
class ICDecayResult:
    ic_series: pd.DataFrame
    decay_summary: pd.DataFrame
    annual_summary: pd.DataFrame
    rolling_summary: pd.DataFrame
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class FactorCorrelationResult:
    matrix: pd.DataFrame
    diagnostics: dict[str, Any]


def _dates(frame: pd.DataFrame) -> pd.Series:
    values = pd.to_datetime(frame["trade_date"], errors="coerce", format="mixed")
    if values.isna().any():
        raise FactorStabilityError("trade_date contains invalid values")
    return values.dt.normalize()


def _numeric(series: pd.Series, label: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    invalid = series.notna() & values.isna()
    if invalid.any():
        raise FactorStabilityError(f"{label} contains non-numeric values")
    values[~np.isfinite(values)] = np.nan
    return values


def _validate(frame: pd.DataFrame, required: set[str]) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise FactorStabilityError("stability data cannot be empty")
    missing = sorted(required - set(frame.columns))
    if missing:
        raise FactorStabilityError(f"stability input is missing required field: {missing[0]}")
    data = frame.copy(deep=True)
    data["trade_date"] = _dates(data)
    data["symbol"] = data["symbol"].astype(str)
    if data.duplicated(["symbol", "trade_date"], keep=False).any():
        raise FactorStabilityError("duplicate symbol/trade_date rows are not allowed")
    return data.sort_values(["trade_date", "symbol"], kind="mergesort").reset_index(drop=True)


def compute_ic_decay(
    frame: pd.DataFrame,
    *,
    label_columns: dict[str, str],
    factor_column: str = "factor",
    min_observations: int = 30,
    rolling_window: int = 20,
) -> ICDecayResult:
    """Compute multiple-horizon IC on one shared session anchor."""
    if not label_columns:
        raise FactorStabilityError("label_columns cannot be empty")
    if not isinstance(rolling_window, int) or rolling_window <= 0:
        raise FactorStabilityError("rolling_window must be positive")
    if not isinstance(min_observations, int) or min_observations <= 1:
        raise FactorStabilityError("min_observations must be greater than one")
    required = {"symbol", "trade_date", factor_column, *label_columns.values()}
    data = _validate(frame, required)
    data[factor_column] = _numeric(data[factor_column], factor_column)
    series_rows: list[pd.DataFrame] = []
    for horizon, label_column in label_columns.items():
        labeled = data[["trade_date", "symbol", factor_column, label_column]].copy()
        labeled[label_column] = _numeric(labeled[label_column], label_column)
        labeled = labeled.rename(columns={label_column: "forward_label", factor_column: "factor"})
        try:
            result = compute_ic_series(labeled, factor_column="factor", label_column="forward_label", method="spearman", min_observations=min_observations)
        except FactorAnalysisError as exc:
            raise FactorStabilityError(str(exc)) from exc
        output = result.data.copy()
        output["horizon"] = str(horizon)
        series_rows.append(output)
    ic_series = pd.concat(series_rows, ignore_index=True)
    decay_rows: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    for horizon, group in ic_series.groupby("horizon", sort=True):
        group = group.sort_values("trade_date").reset_index(drop=True)
        valid = group.loc[group["status"] == "ok", "ic"].astype(float)
        decay_rows.append({
            "horizon": horizon,
            "valid_sessions": int(len(valid)),
            "ic_mean": float(valid.mean()) if len(valid) else np.nan,
            "ic_std": float(valid.std(ddof=1)) if len(valid) >= 2 else np.nan,
            "first_valid_date": group.loc[group["status"] == "ok", "trade_date"].min() if len(valid) else pd.NaT,
            "last_valid_date": group.loc[group["status"] == "ok", "trade_date"].max() if len(valid) else pd.NaT,
        })
        for year, annual in group.groupby(group["trade_date"].dt.year, sort=True):
            valid_annual = annual.loc[annual["status"] == "ok", "ic"].astype(float)
            annual_rows.append({
                "horizon": horizon,
                "year": int(year),
                "valid_sessions": int(len(valid_annual)),
                "ic_mean": float(valid_annual.mean()) if len(valid_annual) else np.nan,
                "complete_year": bool(len(annual) >= 200),
            })
        for index, row in group.iterrows():
            window = group.loc[max(0, index - rolling_window + 1): index]
            valid_window = window.loc[window["status"] == "ok", "ic"].astype(float)
            rolling_rows.append({
                "trade_date": row["trade_date"],
                "horizon": horizon,
                "ic_mean": float(valid_window.mean()) if len(valid_window) else np.nan,
                "ic_std": float(valid_window.std(ddof=1)) if len(valid_window) >= 2 else np.nan,
                "window_observations": int(len(valid_window)),
            })
    diagnostics = {
        "shared_session_anchor": True,
        "horizons": [str(item) for item in label_columns],
        "rolling_window": rolling_window,
        "annual_completeness_threshold_sessions": 200,
        "negative_windows_hidden": False,
        "overlapping_labels_retained": True,
    }
    return ICDecayResult(
        ic_series=ic_series,
        decay_summary=pd.DataFrame(decay_rows),
        annual_summary=pd.DataFrame(annual_rows),
        rolling_summary=pd.DataFrame(rolling_rows),
        diagnostics=diagnostics,
    )


def _rank_corr(left: pd.Series, right: pd.Series) -> float:
    left_rank = left.rank(method="average").to_numpy(dtype=float, copy=True)
    right_rank = right.rank(method="average").to_numpy(dtype=float, copy=True)
    left_rank -= left_rank.mean()
    right_rank -= right_rank.mean()
    denominator = float(np.sqrt(np.dot(left_rank, left_rank) * np.dot(right_rank, right_rank)))
    return float(np.dot(left_rank, right_rank) / denominator) if denominator else np.nan


def compute_factor_correlation(
    frame: pd.DataFrame,
    *,
    factor_columns: list[str],
    group_column: str | None = None,
    min_observations: int = 30,
) -> FactorCorrelationResult:
    """Compute pairwise Rank correlation with common-sample counts."""
    if len(factor_columns) < 2:
        raise FactorStabilityError("factor_columns must contain at least two factors")
    data = _validate(frame, {"symbol", "trade_date", *factor_columns, *( [group_column] if group_column else [] )})
    for column in factor_columns:
        data[column] = _numeric(data[column], column)
    groups: list[tuple[str, pd.DataFrame]] = [("__all__", data)]
    if group_column:
        groups.extend((str(value), group) for value, group in data.groupby(group_column, dropna=False, sort=True))
    rows: list[dict[str, Any]] = []
    for group_name, group in groups:
        for left_index, left in enumerate(factor_columns):
            for right in factor_columns[left_index + 1:]:
                pair = group[[left, right]].dropna()
                count = int(len(pair))
                status = "ok"
                value = np.nan
                if count < min_observations:
                    status = "insufficient_observations"
                elif pair[left].nunique() <= 1 or pair[right].nunique() <= 1:
                    status = "constant_factor"
                else:
                    value = _rank_corr(pair[left], pair[right])
                    if not np.isfinite(value):
                        status = "undefined_correlation"
                        value = np.nan
                rows.append({"group": group_name, "left": left, "right": right, "correlation": value, "common_n": count, "status": status})
    return FactorCorrelationResult(
        matrix=pd.DataFrame(rows, columns=["group", "left", "right", "correlation", "common_n", "status"]),
        diagnostics={"method": "spearman", "group_column": group_column, "min_observations": min_observations, "common_sample_only": True},
    )
