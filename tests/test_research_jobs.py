from __future__ import annotations

import pytest

from portfolio_app.research_jobs import (
    JobStatus,
    ResearchCancelled,
    ResearchJobCoordinator,
    ResearchJobError,
)
from portfolio_app.research_result_cache import ResearchResultCache, build_research_cache_key


def _key(name: str = "trend"):
    return build_research_cache_key(
        dataset_id="seeded_demo",
        data_version="data-a",
        processing={"strategy": name},
        engine_id="offline_research-v1",
    )


def test_successful_job_commits_only_after_full_compute_and_is_idempotent():
    cache = ResearchResultCache()
    coordinator = ResearchJobCoordinator(cache)
    calls: list[str] = []

    first = coordinator.submit(_key(), lambda token: calls.append("computed") or {"nav": 1.02})
    second = coordinator.submit(_key(), lambda token: calls.append("unexpected") or {"nav": 9.99})

    assert first.status is JobStatus.SUCCEEDED
    assert first.result == {"nav": 1.02}
    assert first.cache_hit is False
    assert second.status is JobStatus.SUCCEEDED
    assert second.result == first.result
    assert second.cache_hit is True
    assert calls == ["computed"]
    assert cache.lookup(_key()) == {"nav": 1.02}


def test_only_one_job_can_run_and_watch_data_remains_available_during_compute():
    cache = ResearchResultCache()
    coordinator = ResearchJobCoordinator(cache)
    other_key = _key("mean_reversion")

    def compute(token):
        assert coordinator.active_job is not None
        with pytest.raises(ResearchJobError, match="already running"):
            coordinator.submit(other_key, lambda inner: {"nav": 2.0})
        return {"nav": 1.0}

    result = coordinator.submit(_key(), compute)

    assert result.status is JobStatus.SUCCEEDED
    assert coordinator.active_job is None
    assert cache.lookup(other_key) is None


def test_cancelled_queued_job_never_runs_or_creates_a_result():
    cache = ResearchResultCache()
    coordinator = ResearchJobCoordinator(cache)
    key = _key()
    job = coordinator.create_job(key)
    cancelled = coordinator.cancel(job.job_id)

    assert cancelled.status is JobStatus.CANCELLED
    with pytest.raises(ResearchCancelled):
        coordinator.run(job.job_id, lambda token: {"nav": 1.0})
    assert cache.lookup(key) is None


def test_cooperative_cancel_during_compute_is_not_committed():
    cache = ResearchResultCache()
    coordinator = ResearchJobCoordinator(cache)
    key = _key()

    def compute(token):
        token.request_cancel()
        token.checkpoint()
        return {"nav": 1.0}

    result = coordinator.submit(key, compute)

    assert result.status is JobStatus.CANCELLED
    assert result.result is None
    assert cache.lookup(key) is None
    assert cache.stats().computations == 0


def test_failed_job_is_not_an_success_and_does_not_pollute_cache():
    cache = ResearchResultCache()
    coordinator = ResearchJobCoordinator(cache)
    key = _key()

    result = coordinator.submit(key, lambda token: (_ for _ in ()).throw(RuntimeError("bad research")))

    assert result.status is JobStatus.FAILED
    assert result.error == '本次操作失败。'
    assert result.failure['error_id']
    assert result.result is None
    assert cache.lookup(key) is None
    assert cache.stats().computations == 0
