"""Explicit draft/run/result lifecycle for offline research workspaces."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping


class RunStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    RESULT = "result"
    STALE = "stale"
    FAILED = "failed"


def _fingerprint(context_id: str, draft: Mapping[str, Any]) -> str:
    encoded = json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(f"{context_id}|{encoded}".encode("utf-8")).hexdigest()[:16]


def _run_id(context_id: str, draft_fingerprint: str, run_count: int) -> str:
    return f"run-{hashlib.sha256(f'{context_id}|{draft_fingerprint}|{run_count}'.encode()).hexdigest()[:16]}"


@dataclass(frozen=True)
class ResearchRunState:
    context_id: str
    draft: Mapping[str, Any]
    draft_fingerprint: str
    status: RunStatus = RunStatus.DRAFT
    run_id: str | None = None
    run_count: int = 0
    result: Mapping[str, Any] | None = None
    result_fingerprint: str | None = None
    last_success: Mapping[str, Any] | None = None
    last_success_run_id: str | None = None
    error: str | None = None
    history: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.context_id, str) or not self.context_id:
            raise ValueError("context_id is required")
        if not isinstance(self.draft, Mapping):
            raise ValueError("draft must be a mapping")
        if self.run_count < 0:
            raise ValueError("run_count cannot be negative")
        if self.status is RunStatus.RESULT and (self.result is None or self.run_id is None):
            raise ValueError("result state requires a current result and run_id")
        if self.status is RunStatus.RUNNING and self.run_id is None:
            raise ValueError("running state requires run_id")
        if self.status is RunStatus.FAILED and not self.error:
            raise ValueError("failed state requires error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "draft": dict(self.draft),
            "draft_fingerprint": self.draft_fingerprint,
            "status": self.status.value,
            "run_id": self.run_id,
            "run_count": self.run_count,
            "result": dict(self.result) if self.result is not None else None,
            "result_fingerprint": self.result_fingerprint,
            "last_success": dict(self.last_success) if self.last_success is not None else None,
            "last_success_run_id": self.last_success_run_id,
            "error": self.error,
            "history": [dict(item) for item in self.history],
        }


def build_draft_state(context_id: str, draft: Mapping[str, Any]) -> ResearchRunState:
    normalized = dict(draft)
    return ResearchRunState(
        context_id=context_id,
        draft=normalized,
        draft_fingerprint=_fingerprint(context_id, normalized),
    )


def mark_draft(state: ResearchRunState, draft: Mapping[str, Any]) -> ResearchRunState:
    normalized = dict(draft)
    fingerprint = _fingerprint(state.context_id, normalized)
    if fingerprint == state.draft_fingerprint:
        return state
    history = (*state.history[-49:], {"status": state.status.value, "run_id": state.run_id, "draft_fingerprint": state.draft_fingerprint})
    return ResearchRunState(
        context_id=state.context_id,
        draft=normalized,
        draft_fingerprint=fingerprint,
        status=RunStatus.STALE if state.last_success is not None else RunStatus.DRAFT,
        run_count=state.run_count,
        last_success=state.last_success,
        last_success_run_id=state.last_success_run_id,
        history=history,
    )


def begin_run(state: ResearchRunState) -> ResearchRunState:
    if state.status is RunStatus.RUNNING:
        raise ValueError("a research run is already running")
    run_id = _run_id(state.context_id, state.draft_fingerprint, state.run_count + 1)
    return ResearchRunState(
        context_id=state.context_id,
        draft=dict(state.draft),
        draft_fingerprint=state.draft_fingerprint,
        status=RunStatus.RUNNING,
        run_id=run_id,
        run_count=state.run_count + 1,
        last_success=state.last_success,
        last_success_run_id=state.last_success_run_id,
        history=state.history,
    )


def complete_run(state: ResearchRunState, result: Mapping[str, Any]) -> ResearchRunState:
    if state.status is not RunStatus.RUNNING or state.run_id is None:
        raise ValueError("a running state is required to complete a run")
    normalized = dict(result)
    return ResearchRunState(
        context_id=state.context_id,
        draft=dict(state.draft),
        draft_fingerprint=state.draft_fingerprint,
        status=RunStatus.RESULT,
        run_id=state.run_id,
        run_count=state.run_count,
        result=normalized,
        result_fingerprint=state.draft_fingerprint,
        last_success=normalized,
        last_success_run_id=state.run_id,
        history=state.history,
    )


def fail_run(state: ResearchRunState, error: str) -> ResearchRunState:
    if state.status is not RunStatus.RUNNING or state.run_id is None:
        raise ValueError("a running state is required to fail a run")
    message = str(error).strip()
    if not message:
        raise ValueError("run failure requires an error message")
    return ResearchRunState(
        context_id=state.context_id,
        draft=dict(state.draft),
        draft_fingerprint=state.draft_fingerprint,
        status=RunStatus.FAILED,
        run_id=state.run_id,
        run_count=state.run_count,
        last_success=state.last_success,
        last_success_run_id=state.last_success_run_id,
        error=message,
        history=state.history,
    )
