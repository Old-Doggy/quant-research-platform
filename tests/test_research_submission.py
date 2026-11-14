from __future__ import annotations

from portfolio_app.research_result_cache import ResearchResultCache, build_research_cache_key
from portfolio_app.research_submission import current_submission, submit_research


def _key(strategy: str = "trend"):
    return build_research_cache_key(
        dataset_id="seeded_demo",
        data_version="data-a",
        processing={"strategy": strategy, "cost": 0.001},
        engine_id="offline_research-v1",
    )


def test_unsubmitted_or_changed_configuration_has_no_current_result():
    cache = ResearchResultCache()
    state = submit_research(cache, _key(), lambda: {"metrics": {"nav": 1.01}})

    assert current_submission(None, _key()) is None
    assert current_submission(state, _key("mean_reversion")) is None
    assert current_submission(state, _key()) == state


def test_submission_is_the_only_path_that_calls_compute_and_records_cache_hit():
    cache = ResearchResultCache()
    calls: list[int] = []
    key = _key()

    first = submit_research(cache, key, lambda: calls.append(1) or {"metrics": {"nav": 1.01}})
    second = submit_research(cache, key, lambda: calls.append(2) or {"metrics": {"nav": 9.99}})

    assert calls == [1]
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert current_submission(second, key).result["metrics"] == {"nav": 1.01}
