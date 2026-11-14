from __future__ import annotations

from portfolio_app.research_run_adapter import draft_payload, run_explicit, sync_draft
from portfolio_app.research_run_state import RunStatus


def _draft(strategy: str = "trend"):
    return draft_payload(
        context_id="ctx-alpha",
        workspace="strategy",
        dataset_id="seeded_demo",
        symbols=("600000.SH",),
        as_of="2026-02-27",
        strategy_key=strategy,
        strategy_params={"window": 20},
        analysis_mode="single",
        transaction_cost=0.001,
        start_date="2025-01-01",
        end_date="2026-02-27",
    )


def test_syncing_same_draft_does_not_run_or_change_state():
    state = sync_draft(None, _draft())
    same = sync_draft(state, _draft())

    assert state.status is RunStatus.DRAFT
    assert same.status is RunStatus.DRAFT
    assert same.run_count == 0
    assert same.draft_fingerprint == state.draft_fingerprint


def test_syncing_changed_draft_marks_result_stale_without_running():
    state = sync_draft(None, _draft())
    result = run_explicit(state, lambda: {"nav": 101})
    changed = sync_draft(result, _draft("reversal"))

    assert changed.status is RunStatus.STALE
    assert changed.last_success == {"nav": 101}
    assert changed.run_count == 1


def test_explicit_run_calls_compute_once_and_stores_result():
    state = sync_draft(None, _draft())
    calls = []
    result = run_explicit(state, lambda: calls.append("called") or {"nav": 102})

    assert calls == ["called"]
    assert result.status is RunStatus.RESULT
    assert result.result == {"nav": 102}


def test_compute_failure_keeps_previous_success_and_marks_failed():
    state = sync_draft(None, _draft())
    previous = run_explicit(state, lambda: {"nav": 101})
    changed = sync_draft(previous, _draft("reversal"))
    failed = run_explicit(changed, lambda: (_ for _ in ()).throw(RuntimeError("bad input")))

    assert failed.status is RunStatus.FAILED
    assert failed.error == '本次操作失败。'
    assert failed.last_success == {"nav": 101}
