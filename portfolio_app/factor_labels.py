"""Session-aware forward labels and reproducible research cache keys."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from .factor_contracts import LabelSpec


class LabelBuildError(ValueError):
    """Raised when label input or label semantics are invalid."""


@dataclass(frozen=True)
class LabelBuildResult:
    data: pd.DataFrame
    diagnostics: dict[str, Any]
    spec: LabelSpec

    def to_dict(self) -> dict[str, object]:
        return {
            "label_id": self.spec.label_id,
            "label_version": self.spec.version,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class ResearchCacheKey:
    cache_id: str
    data_fingerprint: str
    factor_version: str
    processing_version: str
    label_version: str
    label_fingerprint: str
    engine_id: str
    engine_version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "cache_id": self.cache_id,
            "data_fingerprint": self.data_fingerprint,
            "factor_version": self.factor_version,
            "processing_version": self.processing_version,
            "label_version": self.label_version,
            "label_fingerprint": self.label_fingerprint,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
        }


class ResearchCache:
    """Small process-local cache that returns defensive frame copies."""

    def __init__(self) -> None:
        self._entries: dict[str, pd.DataFrame] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: ResearchCacheKey) -> pd.DataFrame | None:
        if key.cache_id not in self._entries:
            self._misses += 1
            return None
        self._hits += 1
        return self._entries[key.cache_id].copy(deep=True)

    def put(self, key: ResearchCacheKey, value: pd.DataFrame) -> None:
        if not isinstance(value, pd.DataFrame):
            raise LabelBuildError("cache values must be data frames")
        self._entries[key.cache_id] = value.copy(deep=True)

    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "entries": len(self._entries)}


def _canonical_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise LabelBuildError("data must be a data frame")
    data = frame.copy(deep=True)
    for column in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[column]):
            data[column] = data[column].dt.strftime("%Y-%m-%dT%H:%M:%S.%f")
    data = data.reindex(sorted(data.columns), axis=1)
    sort_columns = [column for column in ("symbol", "trade_date") if column in data.columns]
    if sort_columns:
        data = data.sort_values(sort_columns, kind="mergesort")
    data = data.reset_index(drop=True)
    return data


def fingerprint_frame(frame: pd.DataFrame) -> str:
    """Hash canonical values, column names and dtypes independent of row order."""
    canonical = _canonical_frame(frame)
    payload = {
        "columns": [(str(column), str(canonical[column].dtype)) for column in canonical.columns],
        "rows": int(len(canonical)),
        "values": pd.util.hash_pandas_object(canonical, index=False).astype("uint64").tolist(),
    }
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _label_payload(spec: LabelSpec) -> str:
    return json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_research_cache_key(
    frame: pd.DataFrame,
    *,
    factor_version: str,
    processing_version: str,
    label_spec: LabelSpec,
    engine_id: str,
    engine_version: str,
) -> ResearchCacheKey:
    """Build a cache key from every semantic input to label computation."""
    values = {
        "data_fingerprint": fingerprint_frame(frame),
        "factor_version": str(factor_version),
        "processing_version": str(processing_version),
        "label_payload": _label_payload(label_spec),
        "engine_id": str(engine_id),
        "engine_version": str(engine_version),
    }
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    cache_id = hashlib.sha256(encoded).hexdigest()
    return ResearchCacheKey(
        cache_id=cache_id,
        data_fingerprint=values["data_fingerprint"],
        factor_version=values["factor_version"],
        processing_version=values["processing_version"],
        label_version=label_spec.version,
        label_fingerprint=hashlib.sha256(values["label_payload"].encode("utf-8")).hexdigest(),
        engine_id=values["engine_id"],
        engine_version=values["engine_version"],
    )


def _validate_bars(frame: pd.DataFrame, *, label_columns: tuple[str, ...]) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise LabelBuildError("label data cannot be empty")
    missing = sorted({"symbol", "trade_date", *label_columns} - set(frame.columns))
    if missing:
        raise LabelBuildError(f"label input is missing required field: {missing[0]}")
    data = frame.copy(deep=True)
    dates = pd.to_datetime(data["trade_date"], errors="coerce", format="mixed")
    if dates.isna().any():
        raise LabelBuildError("trade_date contains invalid values")
    data["trade_date"] = dates.dt.normalize()
    data["symbol"] = data["symbol"].astype(str)
    if (data["symbol"].str.strip() == "").any():
        raise LabelBuildError("symbol contains empty values")
    if data.duplicated(["symbol", "trade_date"], keep=False).any():
        raise LabelBuildError("duplicate symbol/trade_date rows are not allowed")
    for column in label_columns:
        numeric = pd.to_numeric(data[column], errors="coerce")
        if numeric.isna().any():
            raise LabelBuildError(f"label input {column} contains missing or non-numeric values")
        data[column] = numeric.astype(float)
    data["_label_input_order"] = np.arange(len(data))
    return data.sort_values(["symbol", "trade_date", "_label_input_order"], kind="mergesort").reset_index(drop=True)


def _validate_semantics(spec: LabelSpec) -> None:
    valid_pairs = {
        ("observation_close", "close_to_close"),
        ("next_open", "next_open_to_next_close"),
        ("observation_open", "open_to_close"),
    }
    if (spec.anchor, spec.return_convention) not in valid_pairs:
        raise LabelBuildError("label anchor and return convention are inconsistent")


def _raw_forward_values(data: pd.DataFrame, spec: LabelSpec) -> tuple[pd.Series, pd.Series]:
    labels = pd.Series(np.nan, index=data.index, dtype=float)
    available = pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns]")
    horizon = spec.horizon_sessions
    for _, indices in data.groupby("symbol", sort=False).groups.items():
        group = data.loc[indices].sort_values("trade_date", kind="mergesort")
        current_close = group["close"]
        future_close = current_close.shift(-horizon)
        target_date = group["trade_date"].shift(-horizon)
        if spec.return_convention == "close_to_close":
            values = future_close / current_close - 1.0
        elif spec.return_convention == "next_open_to_next_close":
            start = group["open"].shift(-1)
            values = future_close / start - 1.0
        else:
            values = future_close / group["open"] - 1.0
        labels.loc[group.index] = values.to_numpy()
        available.loc[group.index] = target_date.to_numpy()
    return labels, available


def build_forward_labels(frame: pd.DataFrame, spec: LabelSpec, *, benchmark_frame: pd.DataFrame | None = None) -> LabelBuildResult:
    """Build forward labels on per-symbol session order and preserve incomplete tails."""
    _validate_semantics(spec)
    data = _validate_bars(frame, label_columns=("open", "close"))
    labels, available = _raw_forward_values(data, spec)
    if spec.prediction_direction == "forward_excess_return":
        if benchmark_frame is None:
            raise LabelBuildError("benchmark data is required for forward excess return")
        benchmark = _validate_bars(benchmark_frame, label_columns=("open", "close"))
        benchmark_symbols = benchmark["symbol"].unique()
        if len(benchmark_symbols) != 1:
            raise LabelBuildError("benchmark data must contain exactly one symbol")
        benchmark_labels, _ = _raw_forward_values(benchmark, spec)
        benchmark_by_date = pd.Series(
            benchmark_labels.to_numpy(), index=benchmark["trade_date"].to_numpy()
        )
        data_dates = data["trade_date"]
        labels = labels - data_dates.map(benchmark_by_date)
        available = available.where(available.notna(), pd.NaT)
        missing_benchmark = data_dates.map(benchmark_by_date).isna() & labels.notna()
        labels.loc[missing_benchmark] = np.nan
    if spec.prediction_direction == "forward_rank":
        rank_output = pd.Series(np.nan, index=data.index, dtype=float)
        for _, indices in data.groupby("trade_date", sort=False).groups.items():
            values = labels.loc[indices]
            valid = values.notna()
            count = int(valid.sum())
            if count:
                rank_output.loc[indices[valid.to_numpy()]] = (values.loc[valid].rank(method="average") - 1.0) / max(count - 1, 1)
        labels = rank_output
    data["forward_label"] = labels
    data["label_available_at"] = available
    data["label_status"] = np.where(labels.notna(), "valid", "incomplete_tail")
    data = data.sort_values("_label_input_order", kind="stable").drop(columns="_label_input_order").reset_index(drop=True)
    diagnostics = {
        "input_rows": int(len(data)),
        "valid_labels": int(data["forward_label"].notna().sum()),
        "incomplete_tail_rows": int(data["forward_label"].isna().sum()),
        "symbols": int(data["symbol"].nunique()),
        "horizon_sessions": spec.horizon_sessions,
        "prediction_direction": spec.prediction_direction,
        "return_convention": spec.return_convention,
        "session_based": True,
    }
    return LabelBuildResult(data=data, diagnostics=diagnostics, spec=spec)
