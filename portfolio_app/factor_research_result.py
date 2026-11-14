"""Versioned, serializable factor-research result and numerical exit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import copy
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .factor_analysis import align_factor_labels, compute_ic_series, summarize_ic


class FactorResearchResultError(ValueError):
    """Raised when a factor result is not safe or numerically trustworthy."""


_PRIVATE_PATTERN = re.compile(r"(?:source_file|source_path|private|account|secret|token|password|[A-Za-z]:[\\/]|/Users/|/home/)", re.IGNORECASE)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _validate_public(value: Any, *, location: str = "result") -> None:
    if callable(value):
        raise FactorResearchResultError(f"{location} contains non-serializable executable value")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _PRIVATE_PATTERN.search(str(key)):
                raise FactorResearchResultError(f"{location} contains private field")
            _validate_public(item, location=f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_public(item, location=f"{location}[{index}]")
    elif isinstance(value, str) and _PRIVATE_PATTERN.search(value):
        raise FactorResearchResultError(f"{location} contains private material")
    elif isinstance(value, (float, np.floating)) and not np.isfinite(float(value)):
        raise FactorResearchResultError(f"{location} contains non-finite value")


@dataclass(frozen=True)
class FactorResearchResult:
    result_id: str
    status: str
    schema_version: str
    fingerprints: Mapping[str, str]
    diagnostics: Mapping[str, Any]
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "status": self.status,
            "schema_version": self.schema_version,
            "fingerprints": _plain(self.fingerprints),
            "diagnostics": _plain(self.diagnostics),
            "payload": _plain(self.payload),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FactorResearchResult":
        if not isinstance(value, Mapping):
            raise FactorResearchResultError("result must be a mapping")
        required = {"result_id", "status", "schema_version", "fingerprints", "diagnostics", "payload"}
        missing = sorted(required - set(value))
        if missing:
            raise FactorResearchResultError(f"result is missing field: {missing[0]}")
        return cls(
            result_id=str(value["result_id"]),
            status=str(value["status"]),
            schema_version=str(value["schema_version"]),
            fingerprints=_freeze(copy.deepcopy(dict(value["fingerprints"]))),
            diagnostics=_freeze(copy.deepcopy(dict(value["diagnostics"]))),
            payload=_freeze(copy.deepcopy(dict(value["payload"]))),
        )


def build_factor_research_result(
    *,
    result_id: str,
    data_fingerprint: str,
    factor_fingerprint: str,
    label_fingerprint: str,
    processing_fingerprint: str,
    engine_id: str,
    engine_version: str,
    diagnostics: Mapping[str, Any],
    payload: Mapping[str, Any],
    status: str = "COMPLETE",
) -> FactorResearchResult:
    if not result_id or not all(isinstance(item, str) and item.strip() for item in (data_fingerprint, factor_fingerprint, label_fingerprint, processing_fingerprint, engine_id, engine_version)):
        raise FactorResearchResultError("result identity and fingerprints are required")
    if not isinstance(diagnostics, Mapping) or not isinstance(payload, Mapping):
        raise FactorResearchResultError("diagnostics and payload must be mappings")
    raw = {"diagnostics": copy.deepcopy(dict(diagnostics)), "payload": copy.deepcopy(dict(payload))}
    _validate_public(raw)
    return FactorResearchResult(
        result_id=result_id,
        status=status,
        schema_version="factor-research-result.v1",
        fingerprints=_freeze({"data": data_fingerprint, "factor": factor_fingerprint, "label": label_fingerprint, "processing": processing_fingerprint, "engine": f"{engine_id}:{engine_version}"}),
        diagnostics=_freeze(raw["diagnostics"]),
        payload=_freeze(raw["payload"]),
    )


@dataclass(frozen=True)
class NumericalExit:
    status: str
    signal_assessment: str
    failure_reason: str | None
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "signal_assessment": self.signal_assessment, "failure_reason": self.failure_reason, "evidence": _plain(self.evidence)}


def build_factor_numerical_exit(
    frame: pd.DataFrame,
    *,
    factor_column: str = "factor",
    label_column: str = "forward_label",
    as_of: pd.Timestamp | str | None = None,
    min_observations: int = 3,
) -> NumericalExit:
    """Run a conservative numerical fixture exit without selecting on IC."""
    data = frame.copy(deep=True)
    required = {"symbol", "trade_date", factor_column, label_column, "factor_available_at"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise FactorResearchResultError(f"numerical exit is missing field: {missing[0]}")
    dates = pd.to_datetime(data["trade_date"], errors="coerce", format="mixed")
    available = pd.to_datetime(data["factor_available_at"], errors="coerce", format="mixed")
    if dates.isna().any() or available.isna().any():
        raise FactorResearchResultError("numerical exit contains invalid time")
    cutoff = pd.Timestamp(as_of) if as_of is not None else dates.max()
    future = available > dates
    evidence: dict[str, Any] = {
        "input_rows": int(len(data)),
        "future_factor_rows": int(future.sum()),
        "valid_rows": 0,
        "finite_ic": False,
        "ic_mean": None,
        "cutoff": cutoff.isoformat(),
    }
    if future.any():
        return NumericalExit("FAIL", "blocked", "future_factor_availability", MappingProxyType(evidence))
    factor = pd.to_numeric(data[factor_column], errors="coerce")
    label = pd.to_numeric(data[label_column], errors="coerce")
    valid = factor.notna() & label.notna() & np.isfinite(factor) & np.isfinite(label)
    evidence["valid_rows"] = int(valid.sum())
    if not valid.any():
        return NumericalExit("FAIL", "blocked", "no_valid_observations", MappingProxyType(evidence))
    if factor.loc[valid].nunique() <= 1:
        return NumericalExit("FAIL", "blocked", "constant_factor", MappingProxyType(evidence))
    aligned = align_factor_labels(data.loc[valid, ["symbol", "trade_date", factor_column, label_column]].rename(columns={factor_column: "factor", label_column: "forward_label"}), min_assets_per_date=1, min_sessions=1)
    ic = compute_ic_series(aligned.data, method="spearman", min_observations=min_observations)
    valid_ic = pd.to_numeric(ic.data["ic"], errors="coerce")
    finite_ic = valid_ic[np.isfinite(valid_ic)]
    evidence["finite_ic"] = bool(len(finite_ic))
    evidence["ic_mean"] = float(finite_ic.mean()) if len(finite_ic) else None
    assessment = "known_signal_fixture" if len(finite_ic) and float(finite_ic.mean()) > 0.5 else "weak_or_noise_fixture"
    return NumericalExit("PASS", assessment, None, MappingProxyType(evidence))
