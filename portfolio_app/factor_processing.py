"""Auditable missing-value and factor preprocessing for offline research."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .factor_contracts import ProcessingSpec


class FactorProcessingError(ValueError):
    """Raised when a factor processing request cannot be applied safely."""


_MISSING_POLICIES = {"drop_row", "preserve_nan"}
_STANDARDIZATIONS = {"none", "zscore", "rank"}


@dataclass(frozen=True)
class FittedFactorProcessing:
    """Immutable, serializable parameters learned from a training period."""

    spec: ProcessingSpec
    factor_columns: tuple[str, ...]
    training_end: str
    fit_rows: int
    fit_missing_rows: int
    parameters: tuple[tuple[str, tuple[tuple[str, float | None], ...]], ...]

    def parameter_map(self) -> dict[str, dict[str, float | None]]:
        return {factor: dict(values) for factor, values in self.parameters}

    def to_dict(self) -> dict[str, object]:
        return {
            "processing_id": self.spec.processing_id,
            "version": self.spec.version,
            "factor_columns": list(self.factor_columns),
            "training_end": self.training_end,
            "fit_scope": self.spec.fit_scope,
            "fit_rows": self.fit_rows,
            "fit_missing_rows": self.fit_missing_rows,
            "parameters": {factor: dict(values) for factor, values in self.parameters},
        }


@dataclass(frozen=True)
class FactorProcessingResult:
    """Processed factor data and quality evidence for the applied run."""

    data: pd.DataFrame
    quality: dict[str, Any]
    fitted: FittedFactorProcessing


def _validate_request(frame: pd.DataFrame, factor_columns: list[str] | tuple[str, ...], spec: ProcessingSpec) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if frame is None or frame.empty:
        raise FactorProcessingError("factor frame cannot be empty")
    if not isinstance(factor_columns, (list, tuple)) or not factor_columns:
        raise FactorProcessingError("factor columns are required")
    columns = tuple(str(column) for column in factor_columns)
    if len(set(columns)) != len(columns):
        raise FactorProcessingError("factor columns cannot contain duplicates")
    required = {"symbol", "trade_date", *columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        if set(missing).intersection(columns):
            raise FactorProcessingError(f"unknown factor column: {missing[0]}")
        raise FactorProcessingError(f"factor frame is missing required column: {missing[0]}")
    if spec.missing_value_policy not in _MISSING_POLICIES:
        raise FactorProcessingError(f"unsupported missing policy: {spec.missing_value_policy}")
    if spec.standardization not in _STANDARDIZATIONS:
        raise FactorProcessingError(f"unsupported standardization: {spec.standardization}")
    if spec.axis == "time_series" and spec.standardization == "rank":
        raise FactorProcessingError("time-series rank standardization is not supported without a fitted distribution")
    if spec.fit_scope != "training_period" or not spec.fit_train_only:
        raise FactorProcessingError("processing fit must use a training_period and fit_train_only")
    result = frame.copy(deep=True)
    dates = pd.to_datetime(result["trade_date"], errors="coerce")
    if dates.isna().any():
        raise FactorProcessingError("trade_date contains invalid values")
    result["trade_date"] = dates
    if result["symbol"].isna().any() or (result["symbol"].astype(str).str.strip() == "").any():
        raise FactorProcessingError("symbol contains missing or empty values")
    result["symbol"] = result["symbol"].astype(str)
    if result.duplicated(["symbol", "trade_date"], keep=False).any():
        raise FactorProcessingError("duplicate symbol/trade_date keys are not allowed")
    for column in columns:
        original = result[column]
        numeric = pd.to_numeric(original, errors="coerce")
        invalid = original.notna() & numeric.isna()
        if invalid.any():
            raise FactorProcessingError(f"factor column is non-numeric: {column}")
        result[column] = numeric.astype(float)
    return result, columns


def _parse_training_end(training_end: str | pd.Timestamp) -> pd.Timestamp:
    parsed = pd.to_datetime(training_end, errors="coerce")
    if pd.isna(parsed):
        raise FactorProcessingError("training_end must be a valid date")
    return pd.Timestamp(parsed)


def _quantile(values: pd.Series, probability: float | None) -> float | None:
    if probability is None:
        return None
    valid = values.dropna()
    if valid.empty:
        return None
    return float(valid.quantile(probability, interpolation="linear"))


def fit_factor_processing(
    frame: pd.DataFrame,
    factor_columns: list[str] | tuple[str, ...],
    spec: ProcessingSpec,
    *,
    training_end: str | pd.Timestamp,
) -> FittedFactorProcessing:
    """Fit clipping parameters using only rows up to ``training_end``."""
    clean, columns = _validate_request(frame, factor_columns, spec)
    end = _parse_training_end(training_end)
    training = clean.loc[clean["trade_date"] <= end]
    if training.empty:
        raise FactorProcessingError("training period contains no rows")
    missing_mask = training.loc[:, columns].isna().any(axis=1)
    fit_rows = int(len(training))
    fit_missing_rows = int(missing_mask.sum())
    if fit_rows == fit_missing_rows:
        raise FactorProcessingError("training period contains no usable factor values")
    parameters: list[tuple[str, tuple[tuple[str, float | None], ...]]] = []
    for column in columns:
        values = training[column]
        lower = _quantile(values, spec.winsorize_lower)
        upper = _quantile(values, spec.winsorize_upper)
        usable = values.dropna()
        clipped = usable.clip(lower=lower, upper=upper)
        mean = float(clipped.mean()) if not clipped.empty else None
        std = float(clipped.std(ddof=0)) if not clipped.empty else None
        parameters.append((column, (("lower", lower), ("upper", upper), ("mean", mean), ("std", std))))
    return FittedFactorProcessing(
        spec=spec,
        factor_columns=columns,
        training_end=end.strftime("%Y-%m-%d"),
        fit_rows=fit_rows,
        fit_missing_rows=fit_missing_rows,
        parameters=tuple(parameters),
    )


def _clip(values: pd.Series, params: dict[str, float | None]) -> pd.Series:
    return values.clip(lower=params.get("lower"), upper=params.get("upper"))


def _cross_sectional_rank(values: pd.Series) -> pd.Series:
    valid_count = int(values.notna().sum())
    if valid_count <= 1:
        return values.where(values.isna(), 0.0)
    return (values.rank(method="average") - 1.0) / (valid_count - 1.0)


def _standardize(values: pd.Series, standardization: str, params: dict[str, float | None], axis: str, dates: pd.Series) -> pd.Series:
    if standardization == "none":
        return values
    if standardization == "rank":
        if axis == "cross_sectional":
            output = pd.Series(np.nan, index=values.index, dtype=float)
            for _, indices in dates.groupby(dates, sort=False).groups.items():
                output.loc[indices] = _cross_sectional_rank(values.loc[indices])
            return output
        return values.rank(method="average", pct=True)
    if axis == "cross_sectional":
        def zscore(group: pd.Series) -> pd.Series:
            mean = group.mean()
            std = group.std(ddof=0)
            if pd.isna(std) or std == 0:
                return group * 0.0
            return (group - mean) / std
        output = pd.Series(np.nan, index=values.index, dtype=float)
        for _, indices in dates.groupby(dates, sort=False).groups.items():
            output.loc[indices] = zscore(values.loc[indices])
        return output
    mean = params.get("mean")
    std = params.get("std")
    if mean is None or std is None or std == 0:
        return values * 0.0
    return (values - mean) / std


def apply_factor_processing(fitted: FittedFactorProcessing, frame: pd.DataFrame) -> FactorProcessingResult:
    """Apply fitted parameters and return data plus explicit quality evidence."""
    if not isinstance(fitted, FittedFactorProcessing):
        raise FactorProcessingError("fitted processing parameters are required")
    clean, columns = _validate_request(frame, list(fitted.factor_columns), fitted.spec)
    if columns != fitted.factor_columns:
        raise FactorProcessingError("factor columns do not match fitted processing")
    original_rows = len(clean)
    missing_mask = clean.loc[:, columns].isna().any(axis=1)
    missing_rows = int(missing_mask.sum())
    if fitted.spec.missing_value_policy == "drop_row":
        output = clean.loc[~missing_mask].copy()
    else:
        output = clean.copy()
    params = fitted.parameter_map()
    for column in columns:
        output[column] = _clip(output[column], params[column])
        output[column] = _standardize(
            output[column], fitted.spec.standardization, params[column], fitted.spec.axis, output["trade_date"]
        )
    non_missing_output = int(output.loc[:, columns].notna().all(axis=1).sum())
    quality = {
        "input_rows": int(original_rows),
        "output_rows": int(len(output)),
        "missing_rows": missing_rows,
        "dropped_rows": int(original_rows - len(output)),
        "coverage_ratio": float(non_missing_output / original_rows) if original_rows else 0.0,
        "deletion_rate": float((original_rows - len(output)) / original_rows) if original_rows else 0.0,
        "fit_rows": fitted.fit_rows,
        "fit_missing_rows": fitted.fit_missing_rows,
        "factor_columns": list(columns),
        "axis": fitted.spec.axis,
        "missing_value_policy": fitted.spec.missing_value_policy,
        "standardization": fitted.spec.standardization,
    }
    return FactorProcessingResult(data=output, quality=quality, fitted=fitted)
