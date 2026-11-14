from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.research_result_cache import (
    ResearchResultCache,
    build_data_fingerprint,
    build_research_cache_key,
)


def _key(*, data_version: str = "data-a", processing: object = None, engine_id: str = "offline_research-v1"):
    return build_research_cache_key(
        dataset_id="seeded_demo",
        data_version=data_version,
        processing=processing if processing is not None else {"strategy": "trend", "cost": 0.001},
        engine_id=engine_id,
    )


def test_cache_does_not_compute_until_explicit_submission():
    cache = ResearchResultCache()
    calls: list[str] = []
    key = _key()

    assert cache.lookup(key) is None
    assert calls == []
    assert cache.stats().submissions == 0

    result = cache.submit(key, lambda: calls.append("computed") or {"nav": 1.02})
    assert result.value == {"nav": 1.02}
    assert result.cache_hit is False
    assert calls == ["computed"]
    assert cache.stats().submissions == 1
    assert cache.stats().computations == 1


def test_same_key_is_cached_and_explicit_resubmission_does_not_recompute():
    cache = ResearchResultCache()
    calls: list[int] = []
    key = _key()

    first = cache.submit(key, lambda: calls.append(1) or {"nav": 1.02})
    second = cache.submit(key, lambda: calls.append(2) or {"nav": 9.99})

    assert first.value == second.value == {"nav": 1.02}
    assert second.cache_hit is True
    assert calls == [1]
    assert cache.stats().submissions == 2
    assert cache.stats().computations == 1
    assert cache.stats().cache_hits == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"data_version": "data-b"},
        {"processing": {"strategy": "mean_reversion", "cost": 0.001}},
        {"engine_id": "offline_research-v2"},
    ],
)
def test_data_processing_or_engine_change_cannot_reuse_result(kwargs):
    cache = ResearchResultCache()
    first_key = _key()
    changed_key = _key(**kwargs)
    assert first_key.key_id != changed_key.key_id

    calls: list[str] = []
    cache.submit(first_key, lambda: calls.append("first") or {"nav": 1.0})
    result = cache.submit(changed_key, lambda: calls.append("changed") or {"nav": 1.1})

    assert result.cache_hit is False
    assert calls == ["first", "changed"]
    assert cache.stats().computations == 2


def test_failed_submission_is_not_cached_or_counted_as_computation():
    cache = ResearchResultCache()
    key = _key()

    with pytest.raises(RuntimeError, match="bad research"):
        cache.submit(key, lambda: (_ for _ in ()).throw(RuntimeError("bad research")))

    assert cache.lookup(key) is None
    assert cache.stats().submissions == 1
    assert cache.stats().computations == 0
    assert cache.stats().failures == 1


def test_data_fingerprint_changes_when_market_data_changes_and_is_order_stable():
    frame = pd.DataFrame({"trade_date": ["2026-01-01", "2026-01-02"], "close": [10.0, 11.0]})
    reordered = frame[["close", "trade_date"]]
    changed = frame.assign(close=[10.0, 12.0])

    assert build_data_fingerprint(frame) == build_data_fingerprint(reordered)
    assert build_data_fingerprint(frame) != build_data_fingerprint(changed)
