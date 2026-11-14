"""Stable contracts for factor, processing and forward-label research assets."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math
import re
from enum import StrEnum
from typing import Any


class ContractViolation(ValueError):
    """Raised when a research contract is incomplete or unsafe."""


class FactorStatus(StrEnum):
    DESIGN_ONLY = "design_only"
    DATA_UNAVAILABLE = "data_unavailable"
    COMPUTABLE = "computable"
    VALIDATED = "validated"
    ARCHIVED = "archived"


class DisclosureStatus(StrEnum):
    PRIVATE = "private"
    PUBLIC_REDACTED = "public_redacted"
    PUBLIC_DEMO = "public_demo"


class FactorDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    TWO_SIDED = "two_sided"


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:/-]+$")
_PRIVATE_MATERIAL = re.compile(
    r"(?:expression|formula|source_files?|parameters?|account|secret|token|password|__import__|exec\s*\(|eval\s*\(|[A-Za-z]:[\\/]|/Users/|/home/|\\\\)",
    re.IGNORECASE,
)


def _serializable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serializable(item) for item in value]
    return value


def _require_version(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or not _SAFE_TOKEN.fullmatch(value):
        raise ContractViolation(f"{label} is required and must be a safe version token")


def _parse_time(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractViolation(f"{label} must be an ISO timestamp") from exc
    return parsed


def _reject_private_values(values: object) -> None:
    if callable(values):
        raise ContractViolation("executable objects are not allowed in research contracts")
    if isinstance(values, dict):
        for key, value in values.items():
            if _PRIVATE_MATERIAL.search(str(key)):
                raise ContractViolation(f"private field is not allowed: {key}")
            _reject_private_values(value)
    elif isinstance(values, (tuple, list, set)):
        for value in values:
            _reject_private_values(value)
    elif isinstance(values, str) and _PRIVATE_MATERIAL.search(values):
        raise ContractViolation("private path, code or strategy material is not allowed")


@dataclass(frozen=True)
class FactorSpec:
    factor_id: str
    name: str
    version: str
    family: str
    input_fields: tuple[str, ...]
    input_units: dict[str, str]
    output_unit: str
    direction: FactorDirection | str
    window: int
    available_at: str
    price_convention: str
    missing_value_policy: str
    compute_status: FactorStatus | str
    disclosure_status: DisclosureStatus | str
    data_dependencies: tuple[str, ...]
    asset_scope: tuple[str, ...]
    observation_time: str | None = None

    def __post_init__(self) -> None:
        if not self.factor_id or not self.name or not self.family:
            raise ContractViolation("FactorSpec identity fields are required")
        if _PRIVATE_MATERIAL.search(self.name) or _PRIVATE_MATERIAL.search(self.factor_id):
            raise ContractViolation("FactorSpec contains private material")
        _require_version(self.version, "FactorSpec.version")
        if not self.input_fields or not self.input_units:
            raise ContractViolation("FactorSpec input fields and units are required")
        if any(not isinstance(field, str) or not field.strip() for field in self.input_fields):
            raise ContractViolation("FactorSpec input_fields must be non-empty text")
        if set(self.input_fields) != set(self.input_units):
            raise ContractViolation("FactorSpec input_fields and input_units must match")
        if any(not isinstance(field, str) or not isinstance(unit, str) for field, unit in self.input_units.items()):
            raise ContractViolation("FactorSpec input fields and units must be text")
        if any(not field or not unit for field, unit in self.input_units.items()):
            raise ContractViolation("FactorSpec input units must be non-empty")
        if not self.output_unit.strip():
            raise ContractViolation("FactorSpec.output_unit is required")
        try:
            FactorDirection(self.direction)
            FactorStatus(self.compute_status)
            DisclosureStatus(self.disclosure_status)
        except ValueError as exc:
            raise ContractViolation("FactorSpec enum field is invalid") from exc
        if not isinstance(self.window, int) or self.window <= 0:
            raise ContractViolation("FactorSpec.window must be positive")
        available = _parse_time(self.available_at, "FactorSpec.available_at")
        if self.observation_time is not None and available < _parse_time(self.observation_time, "FactorSpec.observation_time"):
            raise ContractViolation("FactorSpec.available_at cannot precede observation_time")
        if not self.price_convention or not self.missing_value_policy:
            raise ContractViolation("FactorSpec price and missing value policies are required")
        if not self.data_dependencies or not self.asset_scope:
            raise ContractViolation("FactorSpec dependencies and asset scope are required")
        if any(not isinstance(item, str) or not item.strip() for item in (*self.data_dependencies, *self.asset_scope)):
            raise ContractViolation("FactorSpec dependencies and asset scope must be non-empty text")
        _reject_private_values(self.input_units)
        _reject_private_values(self.data_dependencies)

    def to_dict(self) -> dict[str, object]:
        return _serializable(asdict(self))


@dataclass(frozen=True)
class ProcessingSpec:
    processing_id: str
    version: str
    missing_value_policy: str
    winsorize_lower: float | None
    winsorize_upper: float | None
    standardization: str
    axis: str
    fit_scope: str
    fit_train_only: bool

    def __post_init__(self) -> None:
        if not self.processing_id:
            raise ContractViolation("ProcessingSpec.processing_id is required")
        _require_version(self.version, "ProcessingSpec.version")
        if self.axis not in {"cross_sectional", "time_series"}:
            raise ContractViolation("ProcessingSpec.axis is invalid")
        if self.fit_scope not in {"none", "training_period", "expanding_training"}:
            raise ContractViolation("ProcessingSpec.fit_scope is invalid")
        if self.fit_scope != "none" and not self.fit_train_only:
            raise ContractViolation("fitted processing must be restricted to training data")
        for value in (self.winsorize_lower, self.winsorize_upper):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ContractViolation("ProcessingSpec winsorize bounds are invalid")
        if self.winsorize_lower is not None and self.winsorize_upper is not None and self.winsorize_lower >= self.winsorize_upper:
            raise ContractViolation("ProcessingSpec winsorize bounds must be ordered")

    def to_dict(self) -> dict[str, object]:
        return _serializable(asdict(self))


@dataclass(frozen=True)
class LabelSpec:
    label_id: str
    version: str
    prediction_direction: str
    horizon_sessions: int
    anchor: str
    return_convention: str
    tail_policy: str
    overlapping: bool
    available_at_policy: str

    def __post_init__(self) -> None:
        if not self.label_id:
            raise ContractViolation("LabelSpec.label_id is required")
        _require_version(self.version, "LabelSpec.version")
        if self.prediction_direction not in {"forward_return", "forward_excess_return", "forward_rank"}:
            raise ContractViolation("LabelSpec.prediction_direction is invalid")
        if not isinstance(self.horizon_sessions, int) or self.horizon_sessions <= 0:
            raise ContractViolation("LabelSpec.horizon_sessions must be positive")
        if self.anchor not in {"observation_close", "next_open", "observation_open"}:
            raise ContractViolation("LabelSpec.anchor is invalid")
        if self.return_convention not in {"close_to_close", "next_open_to_next_close", "open_to_close"}:
            raise ContractViolation("LabelSpec.return_convention is invalid")
        if self.tail_policy != "preserve_missing":
            raise ContractViolation("LabelSpec.tail_policy must preserve incomplete tails")
        if self.available_at_policy not in {"future_session_close", "future_session_open"}:
            raise ContractViolation("LabelSpec.available_at_policy is invalid")

    def to_dict(self) -> dict[str, object]:
        return _serializable(asdict(self))
