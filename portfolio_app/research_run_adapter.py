"""Streamlit-neutral adapter connecting a draft to the run state machine."""
from __future__ import annotations

from typing import Any, Callable, Mapping
from .research_diagnostics import ErrorReports

from portfolio_app.research_run_state import (
    ResearchRunState,
    begin_run,
    build_draft_state,
    complete_run,
    fail_run,
    mark_draft,
)

_ERROR_REPORTS = ErrorReports()


def draft_payload(
    *,
    context_id: str,
    workspace: str,
    dataset_id: str,
    symbols: list[str] | tuple[str, ...],
    as_of: str,
    strategy_key: str,
    strategy_params: Mapping[str, Any],
    analysis_mode: str,
    transaction_cost: float,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    return {
        "workspace": workspace,
        "dataset_id": dataset_id,
        "symbols": tuple(str(symbol) for symbol in symbols),
        "as_of": as_of,
        "strategy_key": strategy_key,
        "strategy_params": dict(strategy_params),
        "analysis_mode": analysis_mode,
        "transaction_cost": float(transaction_cost),
        "start_date": start_date,
        "end_date": end_date,
        "context_id": context_id,
    }


def sync_draft(state: ResearchRunState | None, draft: Mapping[str, Any]) -> ResearchRunState:
    if state is None or state.context_id != str(draft["context_id"]):
        return build_draft_state(str(draft["context_id"]), draft)
    return mark_draft(state, draft)


def run_explicit(
    state: ResearchRunState,
    compute: Callable[[], Mapping[str, Any]],
) -> ResearchRunState:
    running = begin_run(state)
    try:
        result = compute()
    except Exception as exc:
        return fail_run(running, _ERROR_REPORTS.capture(exc)['message'])
    return complete_run(running, result)
