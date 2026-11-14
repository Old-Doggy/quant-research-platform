from __future__ import annotations

from portfolio_app.workspace_navigation import (
    WORKSPACE_VIEW_TARGETS,
    default_workspace_state,
    navigation_query,
    resolve_workspace_query,
    view_target,
)
from portfolio_app.local_app import build_workspace_selector_kwargs
from portfolio_app.workspace_router import ContractViolation, switch_workspace


def test_empty_query_starts_at_watch_dashboard():
    state, error = resolve_workspace_query({})
    assert error is None
    assert state.active_workspace == "watch"
    assert view_target(state.active_workspace) == "dashboard"


def test_safe_deep_link_selects_showcase_without_becoming_default():
    source = switch_workspace(default_workspace_state(), "showcase")
    state, error = resolve_workspace_query(navigation_query(source))
    assert error is None
    assert state.active_workspace == "showcase"
    assert view_target(state.active_workspace) == "showcase"
    assert default_workspace_state().active_workspace == "watch"


def test_invalid_deep_link_fails_closed_to_watch_and_exposes_message():
    state, error = resolve_workspace_query({"workspace": "D:/private/page"})
    assert state.active_workspace == "watch"
    assert view_target(state.active_workspace) == "dashboard"
    assert error and "无效工作区链接" in error


def test_all_seven_workspaces_have_explicit_view_targets():
    assert tuple(WORKSPACE_VIEW_TARGETS) == ("watch", "factors", "strategy", "portfolio", "data", "experiments", "showcase")
    for workspace in WORKSPACE_VIEW_TARGETS:
        assert view_target(workspace)


def test_unknown_view_target_is_rejected():
    try:
        view_target("unknown")
    except ContractViolation:
        pass
    else:
        raise AssertionError("unknown workspace must be rejected")


def test_workspace_selector_does_not_mix_session_state_and_default_index():
    first_render = build_workspace_selector_kwargs("watch", synced=False)
    restored_render = build_workspace_selector_kwargs("strategy", synced=True)

    assert first_render["index"] == 0
    assert restored_render["key"] == "workspace_route_selector"
    assert "index" not in restored_render
