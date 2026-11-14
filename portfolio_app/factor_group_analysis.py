"""Quantile, research-return and coverage diagnostics for factor studies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class GroupAnalysisError(ValueError):
    """Raised when factor grouping or research-return input is invalid."""


@dataclass(frozen=True)
class QuantileGroupResult:
    data: pd.DataFrame
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class GroupReturnResult:
    daily: pd.DataFrame
    cumulative: pd.DataFrame
    diagnostics: dict[str, Any]


@dataclass(frozen=True)
class GroupTurnoverResult:
    turnover: pd.DataFrame
    rank_autocorrelation: dict[str, Any]
    coverage: dict[str, Any]


def _validate_identity(frame: pd.DataFrame, *, required: set[str]) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise GroupAnalysisError("group-analysis data cannot be empty")
    missing = sorted(required - set(frame.columns))
    if missing:
        raise GroupAnalysisError(f"group-analysis input is missing required field: {missing[0]}")
    data = frame.copy(deep=True)
    dates = pd.to_datetime(data["trade_date"], errors="coerce", format="mixed")
    if dates.isna().any():
        raise GroupAnalysisError("trade_date contains invalid values")
    data["trade_date"] = dates.dt.normalize()
    data["symbol"] = data["symbol"].astype(str)
    if (data["symbol"].str.strip() == "").any():
        raise GroupAnalysisError("symbol contains empty values")
    if data.duplicated(["symbol", "trade_date"], keep=False).any():
        raise GroupAnalysisError("duplicate symbol/trade_date rows are not allowed")
    return data.sort_values(["trade_date", "symbol"], kind="mergesort").reset_index(drop=True)


def _numeric(series: pd.Series, label: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    invalid = series.notna() & values.isna()
    if invalid.any():
        raise GroupAnalysisError(f"{label} contains non-numeric values")
    values[~np.isfinite(values)] = np.nan
    return values


def build_quantile_groups(
    frame: pd.DataFrame,
    *,
    factor_column: str = "factor",
    quantiles: int = 5,
    min_assets_per_group: int = 3,
) -> QuantileGroupResult:
    """Assign stable rank-based groups without splitting equal factor values."""
    if not isinstance(quantiles, int) or quantiles < 2 or quantiles > 20:
        raise GroupAnalysisError("quantiles must be between 2 and 20")
    if not isinstance(min_assets_per_group, int) or min_assets_per_group <= 0:
        raise GroupAnalysisError("min_assets_per_group must be positive")
    data = _validate_identity(frame, required={"symbol", "trade_date", factor_column})
    data[factor_column] = _numeric(data[factor_column], factor_column)
    data["factor_quantile"] = pd.Series(pd.NA, index=data.index, dtype="Int64")
    group_sizes: list[int] = []
    underfilled_dates = 0
    insufficient_quantile_dates = 0
    for date, indices in data.groupby("trade_date", sort=True).groups.items():
        values = data.loc[indices, factor_column]
        valid = values.notna()
        if not valid.any():
            continue
        ranks = values.loc[valid].rank(method="average")
        distinct = int(values.loc[valid].nunique())
        effective = min(quantiles, distinct)
        # Rank bins are monotonic and stable. Equal values share a bin; when a
        # tie crosses a boundary it remains in the same bin and the bin count
        # may be smaller than the requested count.
        labels = np.ceil(ranks * effective / len(ranks)).astype(int)
        data.loc[labels.index, "factor_quantile"] = labels.astype("Int64")
        sizes = labels.value_counts()
        group_sizes.extend(int(value) for value in sizes.tolist())
        if effective < quantiles:
            insufficient_quantile_dates += 1
        if len(sizes) < effective or (sizes < min_assets_per_group).any():
            underfilled_dates += 1
    assigned = data["factor_quantile"].notna()
    status = "READY"
    if insufficient_quantile_dates:
        status = "INSUFFICIENT_QUANTILES"
    elif underfilled_dates:
        status = "INSUFFICIENT_GROUP_SIZE"
    diagnostics = {
        "input_rows": int(len(data)),
        "assigned_rows": int(assigned.sum()),
        "missing_factor_rows": int(len(data) - assigned.sum()),
        "requested_quantiles": quantiles,
        "effective_group_count": int(data.loc[assigned, "factor_quantile"].nunique()),
        "min_assets_per_group": min_assets_per_group,
        "underfilled_dates": underfilled_dates,
        "insufficient_quantile_dates": insufficient_quantile_dates,
        "group_size_min": min(group_sizes) if group_sizes else 0,
        "quality_status": status,
        "ties_preserved": True,
    }
    return QuantileGroupResult(data=data, diagnostics=diagnostics)


def compute_group_returns(
    frame: pd.DataFrame,
    *,
    return_columns: dict[str, str],
) -> GroupReturnResult:
    """Compute equal-weighted research group returns for each supplied horizon."""
    if not return_columns:
        raise GroupAnalysisError("return_columns cannot be empty")
    data = _validate_identity(frame, required={"symbol", "trade_date", "factor_quantile", *return_columns.values()})
    group_values = pd.to_numeric(data["factor_quantile"], errors="coerce")
    if group_values.isna().all():
        raise GroupAnalysisError("factor_quantile has no assigned rows")
    data["factor_quantile"] = group_values.astype("Int64")
    rows: list[dict[str, Any]] = []
    missing_total = 0
    for horizon, column in return_columns.items():
        data[column] = _numeric(data[column], column)
        for (date, quantile), group in data.dropna(subset=["factor_quantile"]).groupby(["trade_date", "factor_quantile"], sort=True):
            values = group[column]
            valid = values.dropna()
            missing_total += int(values.isna().sum())
            rows.append({
                "trade_date": date,
                "horizon": str(horizon),
                "factor_quantile": int(quantile),
                "mean_return": float(valid.mean()) if len(valid) else np.nan,
                "valid_n": int(len(valid)),
                "input_n": int(len(values)),
            })
    daily = pd.DataFrame(rows, columns=["trade_date", "horizon", "factor_quantile", "mean_return", "valid_n", "input_n"])
    cumulative_rows: list[dict[str, Any]] = []
    for (horizon, quantile), group in daily.groupby(["horizon", "factor_quantile"], sort=True):
        group = group.sort_values("trade_date")
        wealth = 1.0
        for row in group.itertuples(index=False):
            if pd.notna(row.mean_return):
                wealth *= 1.0 + float(row.mean_return)
                cumulative = wealth - 1.0
            else:
                cumulative = np.nan
            cumulative_rows.append({
                "trade_date": row.trade_date,
                "horizon": str(horizon),
                "factor_quantile": int(quantile),
                "cumulative_return": cumulative,
                "portfolio_type": "research_equal_weight",
            })
    cumulative = pd.DataFrame(cumulative_rows)
    if not daily.empty:
        for horizon, group in daily.groupby("horizon", sort=False):
            top = group[group["factor_quantile"] == group["factor_quantile"].max()][["trade_date", "mean_return"]].rename(columns={"mean_return": "top_return"})
            bottom = group[group["factor_quantile"] == group["factor_quantile"].min()][["trade_date", "mean_return"]].rename(columns={"mean_return": "bottom_return"})
            spread = top.merge(bottom, on="trade_date", how="outer")
            spread_wealth = 1.0
            for row in spread.itertuples(index=False):
                spread_return = float(row.top_return) - float(row.bottom_return) if pd.notna(row.top_return) and pd.notna(row.bottom_return) else None
                if spread_return is None:
                    spread_cumulative = np.nan
                else:
                    spread_wealth *= 1.0 + spread_return
                    spread_cumulative = spread_wealth - 1.0
                cumulative_rows.append({
                    "trade_date": row.trade_date,
                    "horizon": str(horizon),
                    "factor_quantile": 0,
                    "cumulative_return": spread_cumulative,
                    "portfolio_type": "long_short_daily_spread",
                })
    cumulative = pd.DataFrame(cumulative_rows)
    diagnostics = {
        "horizons": [str(item) for item in return_columns],
        "missing_return_rows": int(missing_total),
        "tradable": False,
        "portfolio_type": "research_equal_weight",
        "overlapping_labels_retained": True,
        "missing_values_filled": False,
    }
    return GroupReturnResult(daily=daily, cumulative=cumulative, diagnostics=diagnostics)


def compute_group_turnover(frame: pd.DataFrame, *, top_quantile: int | None = None) -> GroupTurnoverResult:
    """Compute top-group turnover, rank autocorrelation and coverage evidence."""
    data = _validate_identity(frame, required={"symbol", "trade_date", "factor", "factor_quantile"})
    factors = _numeric(data["factor"], "factor")
    groups = pd.to_numeric(data["factor_quantile"], errors="coerce")
    assigned = factors.notna() & groups.notna()
    work = data.loc[assigned, ["trade_date", "symbol", "factor", "factor_quantile"]].copy()
    work["factor"] = factors.loc[assigned]
    work["factor_quantile"] = groups.loc[assigned].astype(int)
    target = int(top_quantile) if top_quantile is not None else int(work["factor_quantile"].max())
    dates = sorted(work["trade_date"].unique())
    rows: list[dict[str, Any]] = []
    top_sets: dict[pd.Timestamp, set[str]] = {}
    rank_frames: dict[pd.Timestamp, pd.Series] = {}
    for date in dates:
        current = work[work["trade_date"] == date]
        top_sets[date] = set(current.loc[current["factor_quantile"] == target, "symbol"])
        rank_frames[date] = current.set_index("symbol")["factor"].rank(method="average")
    for index, date in enumerate(dates):
        current = top_sets[date]
        if index == 0:
            rows.append({"trade_date": date, "turnover": np.nan, "numerator": np.nan, "denominator": len(current), "status": "no_previous_session"})
            continue
        previous = top_sets[dates[index - 1]]
        denominator = len(previous)
        numerator = len(previous - current)
        rows.append({"trade_date": date, "turnover": float(numerator / denominator) if denominator else np.nan, "numerator": numerator, "denominator": denominator, "status": "ok" if denominator else "empty_previous_group"})
    autocorrelations: list[float] = []
    for previous_date, current_date in zip(dates, dates[1:]):
        joined = pd.concat([rank_frames[previous_date].rename("previous"), rank_frames[current_date].rename("current")], axis=1).dropna()
        if len(joined) >= 2 and joined["previous"].std(ddof=0) and joined["current"].std(ddof=0):
            autocorrelations.append(float(joined["previous"].corr(joined["current"])))
    coverage = {
        "input_rows": int(len(data)),
        "assigned_rows": int(len(work)),
        "missing_factor_rows": int(factors.isna().sum()),
        "missing_group_rows": int(groups.isna().sum()),
        "exited_rows": int((data.get("asset_status", pd.Series("active", index=data.index)).astype(str) == "exited").sum()),
        "coverage_ratio": float(len(work) / len(data)) if len(data) else 0.0,
        "denominator_definition": "previous session top-quantile membership count",
    }
    return GroupTurnoverResult(
        turnover=pd.DataFrame(rows),
        rank_autocorrelation={"valid_pairs": len(autocorrelations), "mean": float(np.mean(autocorrelations)) if autocorrelations else None, "values": autocorrelations},
        coverage=coverage,
    )
