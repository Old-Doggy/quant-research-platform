"""Small application adapter for the versioned workspace router."""
from __future__ import annotations

from typing import Any, Mapping

from portfolio_app.research_context import ContractViolation, ResearchContext
from portfolio_app.workspace_router import (
    DEFAULT_WORKSPACE,
    WorkspaceState,
    build_workspace_state,
    encode_route_query,
    parse_route_query,
)


WORKSPACE_VIEW_TARGETS = {
    "watch": "dashboard",
    "factors": "pending_factors",
    "strategy": "dashboard",
    "portfolio": "dashboard",
    "data": "data_analysis",
    "experiments": "pending_experiments",
    "showcase": "showcase",
}


def default_workspace_state() -> WorkspaceState:
    context = ResearchContext(
        dataset_id="seeded_demo",
        workspace=DEFAULT_WORKSPACE,
        symbol="600000.SH",
        as_of="2026-02-27",
        bar_period="1d",
    )
    return build_workspace_state(context)


def resolve_workspace_query(query: Mapping[str, Any]) -> tuple[WorkspaceState, str | None]:
    """Resolve a query into a safe state; invalid deep links fail closed."""
    if not query:
        return default_workspace_state(), None
    try:
        state = parse_route_query(query)
    except ContractViolation as exc:
        return default_workspace_state(), f"已忽略无效工作区链接：{exc}"
    return state, None


def view_target(workspace: str) -> str:
    try:
        return WORKSPACE_VIEW_TARGETS[workspace]
    except KeyError as exc:
        raise ContractViolation(f"workspace has no registered view: {workspace}") from exc


def navigation_query(state: WorkspaceState) -> dict[str, str]:
    return encode_route_query(state)
