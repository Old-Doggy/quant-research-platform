"""Small in-process cache for explicitly submitted offline research results."""
from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
import copy
import hashlib
import json
import sys
from threading import RLock
from typing import Any, Callable, Mapping

import pandas as pd


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any, prefix: str) -> str:
    return prefix + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:16]


def build_data_fingerprint(frame: pd.DataFrame) -> str:
    """Return a stable fingerprint for the values and columns in a market frame."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    normalized = frame.reset_index(drop=True).copy()
    normalized = normalized.reindex(sorted(normalized.columns), axis=1)
    from .snapshot_contracts import frame_provenance
    digest = hashlib.sha256(_canonical_json({
        'schema': [(str(c), str(normalized[c].dtype)) for c in normalized],
        'provenance': frame_provenance(frame)}).encode())
    digest.update(pd.util.hash_pandas_object(normalized, index=False).to_numpy().tobytes())
    return 'data-' + digest.hexdigest()


@dataclass(frozen=True)
class ResearchCacheKey:
    dataset_id: str
    data_version: str
    processing: Mapping[str, Any]
    engine_id: str
    key_id: str


def build_research_cache_key(
    *,
    dataset_id: str,
    data_version: str,
    processing: Mapping[str, Any],
    engine_id: str,
) -> ResearchCacheKey:
    """Build an auditable key; every computation-affecting input must be explicit."""
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("dataset_id is required")
    if not isinstance(data_version, str) or not data_version.strip():
        raise ValueError("data_version is required")
    if not isinstance(engine_id, str) or not engine_id.strip():
        raise ValueError("engine_id is required")
    if not isinstance(processing, Mapping):
        raise TypeError("processing must be a mapping")
    normalized = json.loads(_canonical_json(dict(processing)))
    identity = {
        "dataset_id": dataset_id,
        "data_version": data_version,
        "processing": normalized,
        "engine_id": engine_id,
    }
    return ResearchCacheKey(
        dataset_id=dataset_id,
        data_version=data_version,
        processing=normalized,
        engine_id=engine_id,
        key_id=_digest(identity, "cache-"),
    )


@dataclass(frozen=True)
class ResearchCacheStats:
    submissions: int = 0
    computations: int = 0
    cache_hits: int = 0
    failures: int = 0
    entries: int = 0
    bytes_used: int = 0
    evictions: int = 0


def result_bytes(value, seen=None):
    """Conservative retained-size estimate, not a process RSS measurement."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    if isinstance(value, pd.DataFrame):
        return int(value.memory_usage(index=True, deep=True).sum())
    if isinstance(value, pd.Series):
        return int(value.memory_usage(index=True, deep=True))
    size = sys.getsizeof(value)
    if isinstance(value, Mapping):
        return size + sum(result_bytes(k, seen) + result_bytes(v, seen) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return size + sum(result_bytes(v, seen) for v in value)
    if hasattr(value, '__dataclass_fields__'):
        return size + result_bytes(vars(value), seen)
    return size


@dataclass(frozen=True)
class ResearchCacheResult:
    value: Mapping[str, Any]
    cache_hit: bool
    key_id: str


class ResearchResultCache:
    """Session-local cache with explicit submission and observable counters."""

    def __init__(self, *, max_entries=4, max_bytes=96 * 1024 * 1024) -> None:
        if max_entries < 1 or max_bytes < 1:
            raise ValueError('cache limits must be positive')
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._values = OrderedDict()
        self._sizes = {}
        self._lock = RLock()
        self._stats = ResearchCacheStats()

    def lookup(self, key: ResearchCacheKey) -> Mapping[str, Any] | None:
        with self._lock:
            value = self._values.get(key.key_id)
            if value is not None:
                self._values.move_to_end(key.key_id)
            return copy.deepcopy(value) if value is not None else None

    def submit(self, key: ResearchCacheKey, compute: Callable[[], Mapping[str, Any]]) -> ResearchCacheResult:
        with self._lock:
            return self._submit(key, compute)

    def _submit(self, key, compute):
        self._stats = ResearchCacheStats(
            submissions=self._stats.submissions + 1,
            computations=self._stats.computations,
            cache_hits=self._stats.cache_hits,
            failures=self._stats.failures,
            evictions=self._stats.evictions,
        )
        cached = self._values.get(key.key_id)
        if cached is not None:
            self._stats = ResearchCacheStats(
                submissions=self._stats.submissions,
                computations=self._stats.computations,
                cache_hits=self._stats.cache_hits + 1,
                failures=self._stats.failures,
                evictions=self._stats.evictions,
            )
            self._values.move_to_end(key.key_id)
            return ResearchCacheResult(copy.deepcopy(cached), True, key.key_id)
        try:
            computed = compute()
            if not isinstance(computed, Mapping):
                raise TypeError("research result must be a mapping")
            value = copy.deepcopy(dict(computed))
        except Exception:
            self._stats = ResearchCacheStats(
                submissions=self._stats.submissions,
                computations=self._stats.computations,
                cache_hits=self._stats.cache_hits,
                failures=self._stats.failures + 1,
                evictions=self._stats.evictions,
            )
            raise
        size = result_bytes(value)
        evictions = self._stats.evictions
        if size <= self.max_bytes:
            while self._values and (len(self._values) >= self.max_entries or sum(self._sizes.values()) + size > self.max_bytes):
                old, _ = self._values.popitem(last=False)
                self._sizes.pop(old)
                evictions += 1
            self._values[key.key_id] = value
            self._sizes[key.key_id] = size
        self._stats = ResearchCacheStats(
            submissions=self._stats.submissions,
            computations=self._stats.computations + 1,
            cache_hits=self._stats.cache_hits,
            failures=self._stats.failures,
            evictions=evictions,
        )
        return ResearchCacheResult(copy.deepcopy(value), False, key.key_id)

    def stats(self) -> ResearchCacheStats:
        from dataclasses import replace
        with self._lock:
            return replace(self._stats, entries=len(self._values), bytes_used=sum(self._sizes.values()))

    def discard(self, key):
        """Roll back a newly staged result when durable task completion fails."""
        with self._lock:
            self._values.pop(key.key_id, None)
            self._sizes.pop(key.key_id, None)
