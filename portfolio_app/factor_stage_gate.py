"""Stage-level numerical and privacy gate for public factor assets."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import numpy as np
import pandas as pd

from .factor_compute import BASIC_FACTOR_SPECS, FactorComputeError, compute_basic_factors
from .factor_contracts import DisclosureStatus, FactorSpec, FactorStatus


class FactorStageGateError(ValueError):
    """Raised when the factor stage cannot produce a trustworthy public report."""


_PRIVATE_PATTERN = re.compile(
    r"(?:expression|formula|source_files?|parameters?|account|secret|token|password|[A-Za-z]:[\\/]|/Users/|/home/|\\\\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FactorStageReport:
    status: str
    public_factor_count: int
    private_factor_count: int
    computable_factor_ids: tuple[str, ...]
    status_counts: dict[str, tuple[str, ...]]
    public_factors: tuple[dict[str, object], ...]
    unit_matrix: dict[str, dict[str, str]]
    availability_matrix: dict[str, dict[str, str]]
    missing_matrix: dict[str, dict[str, object]]
    numerical_checks: dict[str, bool]
    privacy_hits: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "public_factor_count": self.public_factor_count,
            "private_factor_count": self.private_factor_count,
            "computable_factor_ids": list(self.computable_factor_ids),
            "status_counts": {key: list(value) for key, value in self.status_counts.items()},
            "public_factors": [dict(item) for item in self.public_factors],
            "unit_matrix": self.unit_matrix,
            "availability_matrix": self.availability_matrix,
            "missing_matrix": self.missing_matrix,
            "numerical_checks": self.numerical_checks,
            "privacy_hits": list(self.privacy_hits),
        }


def _public_spec_payload(spec: FactorSpec) -> dict[str, object]:
    return {
        "factor_id": spec.factor_id,
        "name": spec.name,
        "family": spec.family,
        "input_units": dict(spec.input_units),
        "output_unit": spec.output_unit,
        "direction": str(spec.direction.value if hasattr(spec.direction, "value") else spec.direction),
        "window": spec.window,
        "available_at": spec.available_at,
        "price_convention": spec.price_convention,
        "missing_value_policy": spec.missing_value_policy,
        "data_dependencies": list(spec.data_dependencies),
    }


def _input_fields(spec: FactorSpec) -> set[str]:
    return set(spec.input_fields)


def _expected_warmup(spec: FactorSpec) -> int:
    # The first return needs one prior session; rolling windows that include a
    # prior observation expose their first valid value at window - 1 rows.
    return max(1, spec.window - 1)


def _find_private_hits(payload: object) -> tuple[str, ...]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return tuple(sorted(set(match.group(0).lower() for match in _PRIVATE_PATTERN.finditer(text))))


def _validate_specs(specs: tuple[FactorSpec, ...]) -> None:
    ids = [spec.factor_id for spec in specs]
    if len(ids) != len(set(ids)):
        raise FactorStageGateError("duplicate factor ids")
    for spec in specs:
        if spec.compute_status == FactorStatus.COMPUTABLE and spec.disclosure_status == DisclosureStatus.PUBLIC_DEMO:
            if not _input_fields(spec).issubset(set().union(*(set(item.input_fields) for item in BASIC_FACTOR_SPECS))):
                raise FactorStageGateError(f"factor input is outside public capability: {spec.factor_id}")
        if spec.available_at > "2026-10-30T23:59:59Z":
            raise FactorStageGateError(f"factor availability is after gate date: {spec.factor_id}")


def _calculate_selected(frame: pd.DataFrame, specs: tuple[FactorSpec, ...]) -> pd.DataFrame:
    public_specs = [
        spec for spec in specs
        if spec.compute_status == FactorStatus.COMPUTABLE and spec.disclosure_status == DisclosureStatus.PUBLIC_DEMO
    ]
    public_ids = {spec.factor_id for spec in public_specs}
    if not public_ids:
        return frame.copy()
    if not public_ids.issubset({spec.factor_id for spec in BASIC_FACTOR_SPECS}):
        unknown = sorted(public_ids - {spec.factor_id for spec in BASIC_FACTOR_SPECS})
        raise FactorStageGateError(f"public factor is not in basic factor engine: {unknown[0]}")
    try:
        return compute_basic_factors(frame, factor_ids=public_ids)
    except FactorComputeError as exc:
        raise FactorStageGateError(f"factor input or calculation failed: {exc}") from exc


def build_factor_stage_report(
    frame: pd.DataFrame,
    *,
    specs: tuple[FactorSpec, ...] = BASIC_FACTOR_SPECS,
) -> FactorStageReport:
    """Build the final Stage 25 numerical, capability and privacy report."""
    specs = tuple(specs)
    _validate_specs(specs)
    status_counts: dict[str, list[str]] = {status.value: [] for status in FactorStatus}
    public_specs: list[FactorSpec] = []
    private_count = 0
    for spec in specs:
        status = str(spec.compute_status.value if hasattr(spec.compute_status, "value") else spec.compute_status)
        status_counts.setdefault(status, []).append(spec.factor_id)
        if spec.disclosure_status == DisclosureStatus.PRIVATE:
            private_count += 1
        if spec.compute_status == FactorStatus.COMPUTABLE and spec.disclosure_status == DisclosureStatus.PUBLIC_DEMO:
            public_specs.append(spec)
    calculated = _calculate_selected(frame, specs)
    unit_matrix: dict[str, dict[str, str]] = {}
    availability_matrix: dict[str, dict[str, str]] = {}
    missing_matrix: dict[str, dict[str, object]] = {}
    public_payloads: list[dict[str, object]] = []
    all_outputs_present = True
    finite_valid_values = True
    for spec in public_specs:
        output_column = next(
            column for column in calculated.columns
            if column == spec.factor_id.removeprefix("basic.")
            or column == spec.factor_id.replace("basic.", "", 1)
            or column == spec.factor_id.split(".", 1)[-1]
        ) if spec.factor_id.split(".", 1)[-1] in calculated.columns else None
        output_map = {
            "basic.return_1d": "return_1d", "basic.return_5d": "return_5d", "basic.return_20d": "return_20d",
            "basic.return_60d": "return_60d", "basic.reversal_5d": "reversal_5d", "basic.realized_volatility_20d": "realized_volatility_20d",
            "basic.atr_ratio_14d": "atr_ratio_14d", "basic.ma_deviation_20d": "ma_deviation_20d", "basic.volume_ratio_20d": "volume_ratio_20d",
            "basic.price_volume_corr_20d": "price_volume_corr_20d", "basic.range_position_20d": "range_position_20d", "basic.illiquidity": "illiquidity",
        }
        output_column = output_map.get(spec.factor_id, output_column)
        if not output_column or output_column not in calculated.columns:
            all_outputs_present = False
            raise FactorStageGateError(f"factor output is missing: {spec.factor_id}")
        values = pd.to_numeric(calculated[output_column], errors="coerce")
        valid = values.dropna()
        if not np.isfinite(valid.to_numpy(dtype=float)).all():
            finite_valid_values = False
            raise FactorStageGateError(f"factor output contains non-finite values: {spec.factor_id}")
        expected_warmup = _expected_warmup(spec)
        missing_count = int(values.isna().sum())
        warmup_expected = missing_count >= min(expected_warmup, len(values))
        unit_matrix[spec.factor_id] = dict(spec.input_units)
        availability_matrix[spec.factor_id] = {"available_at": spec.available_at, "observation_time": spec.observation_time or "not_declared"}
        missing_matrix[spec.factor_id] = {
            "missing_count": missing_count,
            "missing_ratio": float(missing_count / len(values)) if len(values) else 0.0,
            "warmup_expected": bool(warmup_expected),
            "output_column": output_column,
        }
        public_payloads.append(_public_spec_payload(spec))
    privacy_hits = _find_private_hits({"public_factors": public_payloads, "unit_matrix": unit_matrix, "availability_matrix": availability_matrix})
    if privacy_hits:
        raise FactorStageGateError(f"public factor summary contains private material: {privacy_hits[0]}")
    numerical_checks = {
        "all_outputs_present": all_outputs_present,
        "finite_valid_values": finite_valid_values,
        "warmup_missing_verified": all(item["warmup_expected"] for item in missing_matrix.values()),
        "units_declared": all(bool(item) for item in unit_matrix.values()),
        "availability_declared": all(bool(item.get("available_at")) for item in availability_matrix.values()),
    }
    status = "PASS" if all(numerical_checks.values()) and not privacy_hits else "FAIL"
    return FactorStageReport(
        status=status,
        public_factor_count=len(public_specs),
        private_factor_count=private_count,
        computable_factor_ids=tuple(spec.factor_id for spec in public_specs),
        status_counts={key: tuple(value) for key, value in status_counts.items()},
        public_factors=tuple(public_payloads),
        unit_matrix=unit_matrix,
        availability_matrix=availability_matrix,
        missing_matrix=missing_matrix,
        numerical_checks=numerical_checks,
        privacy_hits=privacy_hits,
    )
