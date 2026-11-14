"""Explicit submission state for the local dashboard research view."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from portfolio_app.research_result_cache import (
    ResearchCacheKey,
    ResearchCacheResult,
    ResearchResultCache,
)


@dataclass(frozen=True)
class ResearchSubmission:
    key_id: str
    result: Mapping[str, Any]
    cache_hit: bool


def current_submission(
    state: ResearchSubmission | None,
    key: ResearchCacheKey,
) -> ResearchSubmission | None:
    if state is None or state.key_id != key.key_id:
        return None
    return state


def submit_research(
    cache: ResearchResultCache,
    key: ResearchCacheKey,
    compute: Callable[[], Mapping[str, Any]],
) -> ResearchSubmission:
    result: ResearchCacheResult = cache.submit(key, compute)
    return ResearchSubmission(key_id=result.key_id, result=dict(result.value), cache_hit=result.cache_hit)
