"""Optional point-in-time industry and size neutralization for factor research."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class FactorNeutralizationError(ValueError):
    """Raised when a neutralization request is invalid or numerically unsafe."""


class NeutralizationUnavailable(FactorNeutralizationError):
    """Raised when required public control data is unavailable."""


@dataclass(frozen=True)
class NeutralizationSpec:
    """Public contract for optional cross-sectional residualization."""

    neutralization_id: str
    version: str
    industry_column: str | None
    industry_available_at_column: str | None
    size_column: str | None
    size_available_at_column: str | None
    size_transform: str
    min_observations: int

    def __post_init__(self) -> None:
        if not self.neutralization_id or not self.version:
            raise FactorNeutralizationError("neutralization identity is required")
        if not any((self.industry_column, self.size_column)):
            raise FactorNeutralizationError("at least one control is required")
        if self.industry_column and not self.industry_available_at_column:
            raise FactorNeutralizationError("industry available_at control is required")
        if self.size_column and not self.size_available_at_column:
            raise FactorNeutralizationError("size available_at control is required")
        if self.size_transform not in {"none", "log1p"}:
            raise FactorNeutralizationError("unsupported size transform")
        if isinstance(self.min_observations, bool) or not isinstance(self.min_observations, int) or self.min_observations < 2:
            raise FactorNeutralizationError("min observations must be at least 2")

    def to_dict(self) -> dict[str, object]:
        return {
            "neutralization_id": self.neutralization_id,
            "version": self.version,
            "industry_column": self.industry_column,
            "industry_available_at_column": self.industry_available_at_column,
            "size_column": self.size_column,
            "size_available_at_column": self.size_available_at_column,
            "size_transform": self.size_transform,
            "min_observations": self.min_observations,
        }


@dataclass(frozen=True)
class NeutralizationResult:
    data: pd.DataFrame
    diagnostics: dict[str, Any]
    spec: NeutralizationSpec
    factor_columns: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "neutralization_id": self.spec.neutralization_id,
            "version": self.spec.version,
            "factor_columns": list(self.factor_columns),
            "diagnostics": dict(self.diagnostics),
        }


def _validate_input(frame: pd.DataFrame, factor_columns: list[str] | tuple[str, ...], spec: NeutralizationSpec) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if frame is None or frame.empty:
        raise FactorNeutralizationError("factor frame cannot be empty")
    columns = tuple(str(column) for column in factor_columns)
    if not columns or len(set(columns)) != len(columns):
        raise FactorNeutralizationError("factor columns are required and cannot repeat")
    missing_factors = sorted(set(columns) - set(frame.columns))
    if missing_factors:
        raise FactorNeutralizationError(f"unknown factor column: {missing_factors[0]}")
    controls = [column for column in (spec.industry_column, spec.size_column) if column]
    availability = [column for column in (spec.industry_available_at_column, spec.size_available_at_column) if column]
    missing_controls = sorted(set(controls + availability) - set(frame.columns))
    if missing_controls:
        raise NeutralizationUnavailable(f"neutralization control or available_at field is unavailable: {missing_controls[0]}")
    result = frame.copy(deep=True)
    dates = pd.to_datetime(result["trade_date"], errors="coerce")
    if dates.isna().any():
        raise FactorNeutralizationError("trade_date contains invalid values")
    result["trade_date"] = dates
    if result["symbol"].isna().any() or (result["symbol"].astype(str).str.strip() == "").any():
        raise FactorNeutralizationError("symbol contains missing or empty values")
    result["symbol"] = result["symbol"].astype(str)
    if result.duplicated(["symbol", "trade_date"], keep=False).any():
        raise FactorNeutralizationError("duplicate symbol/trade_date keys are not allowed")
    for column in columns:
        numeric = pd.to_numeric(result[column], errors="coerce")
        if (result[column].notna() & numeric.isna()).any():
            raise FactorNeutralizationError(f"factor column is non-numeric: {column}")
        result[column] = numeric.astype(float)
    for column in [spec.size_column] if spec.size_column else []:
        numeric = pd.to_numeric(result[column], errors="coerce")
        if (result[column].notna() & numeric.isna()).any():
            raise FactorNeutralizationError(f"size control is non-numeric: {column}")
        result[column] = numeric.astype(float)
    for column in availability:
        parsed = pd.to_datetime(result[column], errors="coerce")
        if parsed.isna().any():
            raise FactorNeutralizationError(f"available_at contains invalid values: {column}")
        result[column] = parsed
    return result, columns


def _build_design(group: pd.DataFrame, spec: NeutralizationSpec) -> np.ndarray:
    parts = [np.ones((len(group), 1), dtype=float)]
    if spec.industry_column:
        industry = group[spec.industry_column]
        if industry.isna().any() or (industry.astype(str).str.strip() == "").any():
            raise FactorNeutralizationError("industry control contains missing values")
        dummies = pd.get_dummies(industry.astype(str), drop_first=True, dtype=float)
        if dummies.shape[1] == 0:
            raise FactorNeutralizationError("industry control is constant")
        parts.append(dummies.to_numpy(dtype=float))
    if spec.size_column:
        size = group[spec.size_column].to_numpy(dtype=float)
        if not np.isfinite(size).all():
            raise FactorNeutralizationError("size control contains missing or non-finite values")
        if spec.size_transform == "log1p":
            if (size < 0).any():
                raise FactorNeutralizationError("log1p size control requires non-negative values")
            size = np.log1p(size)
        if np.allclose(size, size[0]):
            raise FactorNeutralizationError("size control is constant")
        parts.append(size.reshape(-1, 1))
    design = np.column_stack(parts)
    rank = int(np.linalg.matrix_rank(design))
    if rank < design.shape[1]:
        raise FactorNeutralizationError("controls are collinear")
    return design


def neutralize_factors(frame: pd.DataFrame, factor_columns: list[str] | tuple[str, ...], spec: NeutralizationSpec) -> NeutralizationResult:
    """Remove same-session industry and/or size exposure by OLS residuals.

    Each control's ``available_at`` timestamp must be no later than the
    observation date. The source frame is copied and never modified.
    """
    clean, columns = _validate_input(frame, factor_columns, spec)
    availability_pairs = []
    if spec.industry_column:
        availability_pairs.append((spec.industry_column, spec.industry_available_at_column))
    if spec.size_column:
        availability_pairs.append((spec.size_column, spec.size_available_at_column))
    for control, available_column in availability_pairs:
        if (clean[available_column] > clean["trade_date"]).any():
            raise FactorNeutralizationError(f"{control} available_at is after observation date")
    output = clean.copy(deep=True)
    for column in columns:
        output[f"{column}_neutralized"] = np.nan
    date_count = 0
    processed_rows = 0
    for trade_date, indices in clean.groupby("trade_date", sort=True).groups.items():
        group = clean.loc[indices]
        usable = group.loc[group.loc[:, columns].notna().all(axis=1)].copy()
        if len(usable) < spec.min_observations:
            raise FactorNeutralizationError(f"insufficient observations on {trade_date.date()}: {len(usable)}")
        design = _build_design(usable, spec)
        if len(usable) <= design.shape[1]:
            raise FactorNeutralizationError(
                f"insufficient observations on {trade_date.date()} for residual degrees of freedom: "
                f"{len(usable)} rows and {design.shape[1]} controls"
            )
        for column in columns:
            values = usable[column].to_numpy(dtype=float)
            coefficients, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
            residual = values - design @ coefficients
            output.loc[usable.index, f"{column}_neutralized"] = residual
        date_count += 1
        processed_rows += len(usable)
    diagnostics = {
        "dates_processed": date_count,
        "rows_processed": processed_rows,
        "input_rows": len(clean),
        "rows_with_missing_factor": int(clean.loc[:, columns].isna().any(axis=1).sum()),
        "controls": [column for column in (spec.industry_column, spec.size_column) if column],
        "availability_checked": True,
        "method": "cross_sectional_ols_residual",
    }
    return NeutralizationResult(data=output, diagnostics=diagnostics, spec=spec, factor_columns=columns)
