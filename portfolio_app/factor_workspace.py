"""Factor workspace catalog, serializable configuration and preflight gate."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .factor_contracts import DisclosureStatus, FactorSpec, FactorStatus


class FactorWorkspaceError(ValueError):
    """Raised when a factor workspace request is invalid."""


_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date(value: str, label: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise FactorWorkspaceError(f"{label} must be an ISO date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise FactorWorkspaceError(f"{label} must be an ISO date") from exc


def _id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value) or "private" in value.lower():
        raise FactorWorkspaceError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class FactorResearchConfig:
    factor_id: str
    dataset_id: str
    date_start: str
    date_end: str
    label_horizon_sessions: int = 5
    quantiles: int = 5
    min_assets_per_date: int = 30
    max_missing_ratio: float = 0.25
    disclosure_mode: str = "public_demo"
    schema_version: str = "factor-research-config.v1"

    def __post_init__(self) -> None:
        _id(self.factor_id, "factor_id")
        if not isinstance(self.dataset_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', self.dataset_id):
            raise FactorWorkspaceError('dataset_id is invalid')
        start = _date(self.date_start, "date_start")
        end = _date(self.date_end, "date_end")
        if end < start:
            raise FactorWorkspaceError("date_end cannot precede date_start")
        if not isinstance(self.label_horizon_sessions, int) or self.label_horizon_sessions <= 0:
            raise FactorWorkspaceError("label_horizon_sessions must be positive")
        if not isinstance(self.quantiles, int) or not 2 <= self.quantiles <= 20:
            raise FactorWorkspaceError("quantiles must be between 2 and 20")
        if not isinstance(self.min_assets_per_date, int) or self.min_assets_per_date <= 0:
            raise FactorWorkspaceError("min_assets_per_date must be positive")
        if not np.isfinite(float(self.max_missing_ratio)) or not 0 <= self.max_missing_ratio <= 1:
            raise FactorWorkspaceError("max_missing_ratio must be between 0 and 1")
        if self.disclosure_mode not in {"public_demo", "public_redacted", "private_local"}:
            raise FactorWorkspaceError("disclosure_mode is invalid")
        if self.schema_version != "factor-research-config.v1":
            raise FactorWorkspaceError("unsupported schema_version")
        object.__setattr__(self, "date_start", start)
        object.__setattr__(self, "date_end", end)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FactorResearchConfig":
        if not isinstance(payload, dict):
            raise FactorWorkspaceError("factor config must be a mapping")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise FactorWorkspaceError(f"unknown config field: {unknown[0]}")
        try:
            return cls(**payload)
        except TypeError as exc:
            raise FactorWorkspaceError("factor config fields are incomplete") from exc


@dataclass(frozen=True)
class FactorPreflightReport:
    status: str
    submittable: bool
    factor_id: str
    effective_assets: int
    period: dict[str, str | None]
    rows: int
    valid_rows: int
    missing_ratio: float
    warmup_rows: int
    label_tail_rows: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "submittable": self.submittable,
            "factor_id": self.factor_id,
            "effective_assets": self.effective_assets,
            "period": dict(self.period),
            "rows": self.rows,
            "valid_rows": self.valid_rows,
            "missing_ratio": self.missing_ratio,
            "warmup_rows": self.warmup_rows,
            "label_tail_rows": self.label_tail_rows,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def filter_factor_catalog(
    specs: Iterable[FactorSpec],
    *,
    disclosure_mode: str,
    query: str = "",
    family: str | None = None,
    status: FactorStatus | str | None = None,
) -> tuple[FactorSpec, ...]:
    """Filter contract entries without exposing private formula material."""
    if disclosure_mode not in {"public_demo", "public_redacted", "private_local"}:
        raise FactorWorkspaceError("disclosure_mode is invalid")
    normalized_query = str(query or "").strip().lower()
    expected_status = FactorStatus(status) if status is not None else None
    output: list[FactorSpec] = []
    for spec in tuple(specs):
        disclosure = DisclosureStatus(spec.disclosure_status)
        if disclosure_mode == "public_demo" and disclosure is not DisclosureStatus.PUBLIC_DEMO:
            continue
        if disclosure_mode == "public_redacted" and disclosure not in {DisclosureStatus.PUBLIC_DEMO, DisclosureStatus.PUBLIC_REDACTED}:
            continue
        if expected_status is not None and FactorStatus(spec.compute_status) is not expected_status:
            continue
        if family is not None and spec.family != family:
            continue
        haystack = f"{spec.factor_id} {spec.name} {spec.family}".lower()
        if normalized_query and normalized_query not in haystack:
            continue
        output.append(spec)
    return tuple(output)


def preflight_factor_research(
    frame: pd.DataFrame,
    config: FactorResearchConfig,
    *,
    specs: Iterable[FactorSpec],
) -> FactorPreflightReport:
    """Check data capability and sample quality before allowing submission."""
    spec_map = {spec.factor_id: spec for spec in specs}
    selected = spec_map.get(config.factor_id)
    errors: list[str] = []
    warnings: list[str] = []
    if selected is None:
        errors.append("factor_id is not in the selected catalog")
    elif DisclosureStatus(selected.disclosure_status) is DisclosureStatus.PRIVATE and config.disclosure_mode != "private_local":
        errors.append("factor disclosure is not available in this mode")
    elif FactorStatus(selected.compute_status) not in {FactorStatus.COMPUTABLE, FactorStatus.VALIDATED}:
        errors.append("factor is not computable in the selected catalog")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        errors.append("input data is empty")
        return FactorPreflightReport("BLOCKED", False, config.factor_id, 0, {"start": None, "end": None}, 0, 0, 1.0, 0, 0, tuple(errors), tuple(warnings))
    required = {"trade_date", "symbol", *selected.input_fields} if selected is not None else {"trade_date", "symbol"}
    missing_fields = sorted(required - set(frame.columns))
    if missing_fields:
        errors.append(f"missing input field: {missing_fields[0]}")
    data = frame.copy(deep=True)
    dates = pd.to_datetime(data["trade_date"], errors="coerce", format="mixed")
    if dates.isna().any():
        errors.append("trade_date contains invalid values")
        dates = dates.fillna(pd.Timestamp(config.date_start))
    data["trade_date"] = dates.dt.normalize()
    selected_data = data.loc[(data["trade_date"] >= pd.Timestamp(config.date_start)) & (data["trade_date"] <= pd.Timestamp(config.date_end))].copy()
    period = {"start": config.date_start, "end": config.date_end}
    rows = int(len(selected_data))
    assets = int(selected_data["symbol"].astype(str).nunique()) if rows else 0
    missing_mask = selected_data[list(required - {"trade_date", "symbol"})].isna().any(axis=1) if rows and required - {"trade_date", "symbol"} and set(required - {"trade_date", "symbol"}).issubset(selected_data.columns) else pd.Series(False, index=selected_data.index)
    missing_ratio = float(missing_mask.mean()) if rows else 1.0
    valid_rows = int(rows - missing_mask.sum())
    warmup_rows = max(0, int(selected.window) - 1) if selected is not None else 0
    label_tail_rows = int(assets * config.label_horizon_sessions) if assets else 0
    if assets < config.min_assets_per_date:
        errors.append(f"effective assets {assets} below minimum {config.min_assets_per_date}")
    if rows == 0:
        errors.append("selected date range has no rows")
    if missing_ratio > config.max_missing_ratio:
        errors.append(f"missing ratio {missing_ratio:.4f} exceeds limit {config.max_missing_ratio:.4f}")
    if rows and warmup_rows >= rows:
        errors.append("factor warmup consumes the selected period")
    if label_tail_rows:
        warnings.append(f"label tail keeps {label_tail_rows} incomplete rows until future sessions are available")
    submittable = not errors
    return FactorPreflightReport("READY" if submittable else "BLOCKED", submittable, config.factor_id, assets, period, rows, valid_rows, missing_ratio, warmup_rows, label_tail_rows, tuple(errors), tuple(warnings))
