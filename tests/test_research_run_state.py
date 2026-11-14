from __future__ import annotations

import pytest

from portfolio_app.research_run_state import (
    RunStatus,
    ResearchRunState,
    begin_run,
    build_draft_state,
    complete_run,
    fail_run,
    mark_draft,
)


def test_new_context_starts_as_draft_and_never_claims_a_result():
    state = build_draft_state("ctx-alpha", {"strategy": "trend", "symbol": "600000.SH"})

    assert isinstance(state, ResearchRunState)
    assert state.status is RunStatus.DRAFT
    assert state.result is None
    assert state.last_success is None
    assert state.run_count == 0


def test_only_explicit_begin_then_complete_creates_a_result():
    draft = build_draft_state("ctx-alpha", {"strategy": "trend"})
    running = begin_run(draft)

    assert running.status is RunStatus.RUNNING
    assert running.run_count == 1
    assert running.run_id.startswith("run-")
    with pytest.raises(ValueError, match="running"):
        begin_run(running)

    result = complete_run(running, {"ending_nav": 101.0})
    assert result.status is RunStatus.RESULT
    assert result.result == {"ending_nav": 101.0}
    assert result.last_success == {"ending_nav": 101.0}
    assert result.result_fingerprint == result.draft_fingerprint


def test_editing_draft_marks_previous_result_stale_without_deleting_it():
    result = complete_run(begin_run(build_draft_state("ctx-alpha", {"strategy": "trend"})), {"nav": 101})
    stale = mark_draft(result, {"strategy": "reversal"})

    assert stale.status is RunStatus.STALE
    assert stale.result is None
    assert stale.last_success == {"nav": 101}
    assert stale.last_success_run_id == result.run_id
    assert stale.draft_fingerprint != result.draft_fingerprint
    assert stale.run_count == 1


def test_failed_run_preserves_last_success_and_reports_current_error():
    result = complete_run(begin_run(build_draft_state("ctx-alpha", {"strategy": "trend"})), {"nav": 101})
    changed = mark_draft(result, {"strategy": "reversal"})
    failed = fail_run(begin_run(changed), "data quality failed")

    assert failed.status is RunStatus.FAILED
    assert failed.result is None
    assert failed.error == "data quality failed"
    assert failed.last_success == {"nav": 101}
    assert failed.last_success_run_id == result.run_id


def test_context_change_cannot_reuse_old_result_or_run_id():
    old = complete_run(begin_run(build_draft_state("ctx-alpha", {"strategy": "trend"})), {"nav": 101})
    new = build_draft_state("ctx-beta", {"strategy": "trend"})

    assert new.status is RunStatus.DRAFT
    assert new.result is None
    assert new.last_success is None
    assert new.run_id is None
    assert new.context_id != old.context_id
