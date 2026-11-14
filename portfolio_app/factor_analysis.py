"""Point-in-time factor/label alignment and cross-sectional IC diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class FactorAnalysisError(ValueError):
    """Raised when factor-analysis input or statistical semantics are invalid."""


def _as_dates(frame: pd.DataFrame) -> pd.Series:
    dates = pd.to_datetime(frame["trade_date"], errors="coerce", format="mixed")
    if dates.isna().any():
        raise FactorAnalysisError("trade_date contains invalid values")
    return dates.dt.normalize()


def _numeric(series: pd.Series, label: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    invalid = series.notna() & values.isna()
    if invalid.any():
        raise FactorAnalysisError(f"{label} contains non-numeric values")
    values[~np.isfinite(values)] = np.nan
    return values


@dataclass(frozen=True)
class FactorAlignmentResult:
    data: pd.DataFrame
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        return {"diagnostics": dict(self.diagnostics), "rows": int(len(self.data))}


@dataclass(frozen=True)
class ICSeriesResult:
    data: pd.DataFrame
    diagnostics: dict[str, Any]
    factor_column: str
    label_column: str

    def to_dict(self) -> dict[str, object]:
        return {
            "diagnostics": dict(self.diagnostics),
            "factor_column": self.factor_column,
            "label_column": self.label_column,
            "rows": int(len(self.data)),
        }


@dataclass(frozen=True)
class ICSummary:
    metrics: dict[str, Any]
    rolling: tuple[dict[str, Any], ...]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        return {"metrics": dict(self.metrics), "rolling": [dict(item) for item in self.rolling], "diagnostics": dict(self.diagnostics)}


def align_factor_labels(
    frame: pd.DataFrame,
    *,
    factor_column: str = "factor",
    label_column: str = "forward_label",
    min_assets_per_date: int = 30,
    min_sessions: int = 60,
) -> FactorAlignmentResult:
    """Clean one factor/label pair without inventing values or changing identity."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise FactorAnalysisError("factor-analysis data cannot be empty")
    if not isinstance(min_assets_per_date, int) or min_assets_per_date <= 0:
        raise FactorAnalysisError("min_assets_per_date must be positive")
    if not isinstance(min_sessions, int) or min_sessions <= 0:
        raise FactorAnalysisError("min_sessions must be positive")
    required = {"symbol", "trade_date", factor_column, label_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise FactorAnalysisError(f"factor-analysis input is missing required field: {missing[0]}")

    data = frame.copy(deep=True)
    data["trade_date"] = _as_dates(data)
    data["symbol"] = data["symbol"].astype(str)
    if (data["symbol"].str.strip() == "").any():
        raise FactorAnalysisError("symbol contains empty values")
    if data.duplicated(["symbol", "trade_date"], keep=False).any():
        raise FactorAnalysisError("duplicate symbol/trade_date rows are not allowed")

    factor = _numeric(data[factor_column], factor_column)
    label = _numeric(data[label_column], label_column)
    missing_factor = factor.isna()
    missing_label = label.isna()
    both = missing_factor & missing_label
    dropped = {
        "missing_factor": int((missing_factor & ~both).sum()),
        "missing_label": int((missing_label & ~both).sum()),
    }
    # A row missing both fields is counted once per cause for auditability, but
    # the row counter below remains the authoritative number of removed rows.
    if both.any():
        dropped["missing_factor"] += int(both.sum())
        dropped["missing_label"] += int(both.sum())
    valid = ~(missing_factor | missing_label)
    output = data.loc[valid].copy()
    output[factor_column] = factor.loc[valid]
    output[label_column] = label.loc[valid]
    output = output.sort_values(["trade_date", "symbol"], kind="mergesort").reset_index(drop=True)
    counts = output.groupby("trade_date", sort=True)["symbol"].nunique()
    valid_sessions = int(len(counts))
    underfilled = int((counts < min_assets_per_date).sum())
    if not len(output):
        quality_status = "NO_VALID_OBSERVATIONS"
    elif underfilled:
        quality_status = "INSUFFICIENT_CROSS_SECTION"
    elif valid_sessions < min_sessions:
        quality_status = "INSUFFICIENT_SESSIONS"
    else:
        quality_status = "READY"
    diagnostics = {
        "input_rows": int(len(data)),
        "output_rows": int(len(output)),
        "dropped_rows": int(len(data) - len(output)),
        "dropped_by_reason": dropped,
        "valid_sessions": valid_sessions,
        "underfilled_sessions": underfilled,
        "min_assets_per_date": min_assets_per_date,
        "min_sessions": min_sessions,
        "quality_status": quality_status,
        "symbols": int(output["symbol"].nunique()),
    }
    return FactorAlignmentResult(data=output, diagnostics=diagnostics)


def _correlation(left: pd.Series, right: pd.Series, method: str) -> float:
    x = left.to_numpy(dtype=float)
    y = right.to_numpy(dtype=float)
    if method == "spearman":
        x = pd.Series(x).rank(method="average").to_numpy(dtype=float)
        y = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    x_centered = x - x.mean()
    y_centered = y - y.mean()
    denominator = float(np.sqrt(np.dot(x_centered, x_centered) * np.dot(y_centered, y_centered)))
    if denominator == 0.0:
        return float("nan")
    return float(np.dot(x_centered, y_centered) / denominator)


def compute_ic_series(
    frame: pd.DataFrame,
    *,
    factor_column: str = "factor",
    label_column: str = "forward_label",
    method: str = "spearman",
    min_observations: int = 30,
) -> ICSeriesResult:
    """Compute one cross-sectional IC observation per trading date."""
    normalized_method = {"rank": "spearman", "spearman": "spearman", "pearson": "pearson"}.get(method.lower() if isinstance(method, str) else "")
    if normalized_method is None:
        raise FactorAnalysisError("method must be pearson or spearman")
    if not isinstance(min_observations, int) or min_observations <= 1:
        raise FactorAnalysisError("min_observations must be greater than one")
    required = {"symbol", "trade_date", factor_column, label_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise FactorAnalysisError(f"IC input is missing required field: {missing[0]}")
    data = frame.copy(deep=True)
    data["trade_date"] = _as_dates(data)
    data["symbol"] = data["symbol"].astype(str)
    if data.duplicated(["symbol", "trade_date"], keep=False).any():
        raise FactorAnalysisError("duplicate symbol/trade_date rows are not allowed")
    data[factor_column] = _numeric(data[factor_column], factor_column)
    data[label_column] = _numeric(data[label_column], label_column)
    rows: list[dict[str, Any]] = []
    for date, group in data.groupby("trade_date", sort=True):
        valid = group[[factor_column, label_column]].notna().all(axis=1)
        sample = group.loc[valid, [factor_column, label_column]]
        n = int(len(sample))
        status = "ok"
        value = float("nan")
        if n < min_observations:
            status = "insufficient_observations"
        elif sample[factor_column].nunique(dropna=True) <= 1:
            status = "constant_factor"
        elif sample[label_column].nunique(dropna=True) <= 1:
            status = "constant_label"
        else:
            value = _correlation(sample[factor_column], sample[label_column], normalized_method)
            if not np.isfinite(value):
                status = "undefined_correlation"
                value = float("nan")
        rows.append({"trade_date": date, "ic": value, "valid_n": n, "status": status})
    result = pd.DataFrame(rows, columns=["trade_date", "ic", "valid_n", "status"])
    status_counts = {str(key): int(value) for key, value in result["status"].value_counts().to_dict().items()}
    diagnostics = {
        "method": normalized_method,
        "min_observations": min_observations,
        "sessions": int(len(result)),
        "valid_sessions": int((result["status"] == "ok").sum()),
        "status_counts": status_counts,
        "statistical_guarantee": False,
    }
    return ICSeriesResult(data=result, diagnostics=diagnostics, factor_column=factor_column, label_column=label_column)


def summarize_ic(
    series: ICSeriesResult | pd.DataFrame,
    *,
    frequency: str = "daily",
    annualize: bool = True,
    rolling_window: int = 20,
) -> ICSummary:
    """Summarize valid IC observations while keeping annualization explicit."""
    factors = {"daily": 252, "weekly": 52, "monthly": 12}
    if frequency not in factors:
        raise FactorAnalysisError("frequency must be daily, weekly or monthly")
    if not isinstance(rolling_window, int) or rolling_window <= 0:
        raise FactorAnalysisError("rolling_window must be positive")
    data = series.data.copy(deep=True) if isinstance(series, ICSeriesResult) else series.copy(deep=True)
    if "ic" not in data.columns or "trade_date" not in data.columns:
        raise FactorAnalysisError("IC series requires trade_date and ic")
    values = pd.to_numeric(data["ic"], errors="coerce")
    valid = values[np.isfinite(values.to_numpy(dtype=float))]
    count = int(len(valid))
    mean = float(valid.mean()) if count else None
    std = float(valid.std(ddof=1)) if count >= 2 else None
    icir = float(mean / std) if mean is not None and std not in (None, 0.0) else None
    annualized_icir = float(icir * np.sqrt(factors[frequency])) if annualize and icir is not None else None
    rolling: list[dict[str, Any]] = []
    for index, row in data.reset_index(drop=True).iterrows():
        window = values.iloc[max(0, index - rolling_window + 1): index + 1]
        finite = window[np.isfinite(window.to_numpy(dtype=float))]
        window_std = float(finite.std(ddof=1)) if len(finite) >= 2 else None
        window_mean = float(finite.mean()) if len(finite) else None
        window_icir = float(window_mean / window_std) if window_mean is not None and window_std not in (None, 0.0) else None
        rolling.append({
            "trade_date": row["trade_date"],
            "ic_mean": window_mean,
            "ic_std": window_std,
            "icir": window_icir,
            "window_observations": int(len(finite)),
        })
    metrics = {
        "valid_sessions": count,
        "ic_mean": mean,
        "ic_std": std,
        "icir": icir,
        "annualized_icir": annualized_icir,
        "annualization_factor": factors[frequency],
        "frequency": frequency,
        "annualize": bool(annualize),
    }
    diagnostics = {
        "rolling_window": rolling_window,
        "statistical_guarantee": count >= 30,
        "valid_observations_only": True,
        "zero_variance_is_missing": True,
    }
    return ICSummary(metrics=metrics, rolling=tuple(rolling), diagnostics=diagnostics)
