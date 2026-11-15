from __future__ import annotations

import pytest

from portfolio_app.research_context import ContractViolation, ResearchContext
from portfolio_app.workspace_router import (
    DEFAULT_WORKSPACE,
    WORKSPACE_ROUTES,
    WorkspaceState,
    build_workspace_state,
    encode_route_query,
    parse_route_query,
    switch_workspace,
)


def _context() -> ResearchContext:
    return ResearchContext(
        dataset_id="seeded_demo",
        workspace="watch",
        symbol="600000.SH",
        as_of="2026-02-27",
        bar_period="1d",
    )


def test_router_exposes_seven_safe_workspaces_and_watch_is_default():
    assert tuple(route.id for route in WORKSPACE_ROUTES) == (
        "watch", "factors", "strategy", "portfolio", "data", "experiments", "showcase"
    )
    assert DEFAULT_WORKSPACE == "watch"
    assert build_workspace_state(_context()).active_workspace == "watch"
    assert build_workspace_state(_context()).context.context_id.startswith("ctx-")
    assert next(route for route in WORKSPACE_ROUTES if route.id == "showcase").is_default is False


@pytest.mark.parametrize("workspace", [route.id for route in WORKSPACE_ROUTES])
def test_switching_workspace_preserves_research_context(workspace: str):
    original = build_workspace_state(_context())
    switched = switch_workspace(original, workspace)

    assert switched.active_workspace == workspace
    assert switched.context.dataset_id == original.context.dataset_id
    assert switched.context.symbol == original.context.symbol
    assert switched.context.as_of == original.context.as_of
    assert switched.context.bar_period == original.context.bar_period
    assert switched.context.context_id == original.context.context_id


def test_switch_rejects_unknown_workspace_without_mutating_previous_state():
    original = build_workspace_state(_context())
    with pytest.raises(ContractViolation, match="workspace"):
        switch_workspace(original, "D:/private/page")
    assert original.active_workspace == "watch"


def test_route_query_contains_only_safe_ids_and_round_trips_context():
    state = switch_workspace(build_workspace_state(_context()), "showcase")
    query = encode_route_query(state)

    assert query == {
        "workspace": "showcase",
        "context_workspace": "watch",
        "dataset_id": "seeded_demo",
        "symbol": "600000.SH",
        "as_of": "2026-02-27",
        "bar_period": "1d",
        "context_id": state.context.context_id,
        'schema_version': '2.0',
        'date_end': '2026-02-27',
        'disclosure_mode': 'public_demo',
    }
    restored = parse_route_query(query)
    assert restored == state
    assert "private" not in str(query).lower()


def test_route_query_preserves_multiple_symbols_without_path_values():
    context = ResearchContext(
        dataset_id="seeded_demo",
        workspace="portfolio",
        symbols=("600000.SH", "000001.SZ"),
        as_of="2026-02-27",
    )
    state = switch_workspace(build_workspace_state(context), "portfolio")
    restored = parse_route_query(encode_route_query(state))
    assert restored.context.symbols == ("600000.SH", "000001.SZ")
    assert restored.context.symbol is None


def test_switching_from_watch_context_to_portfolio_round_trips_context_id():
    state = switch_workspace(build_workspace_state(_context()), "portfolio")

    query = encode_route_query(state)
    assert query["workspace"] == "portfolio"
    assert query["context_workspace"] == "watch"

    restored = parse_route_query(query)
    assert restored.active_workspace == "portfolio"
    assert restored.context.workspace == "watch"
    assert restored.context.context_id == state.context.context_id


def test_switching_from_watch_context_to_strategy_does_not_invent_strategy_context():
    state = switch_workspace(build_workspace_state(_context()), "strategy")

    restored = parse_route_query(encode_route_query(state))
    assert restored.active_workspace == "strategy"
    assert restored.context.workspace == "watch"
    assert restored.context.strategy_id is None
    assert restored.context.context_id == state.context.context_id


def test_context_workspace_is_validated_and_context_id_cannot_be_rebound():
    query = encode_route_query(switch_workspace(build_workspace_state(_context()), "portfolio"))

    with pytest.raises(ContractViolation, match="context_workspace"):
        parse_route_query({**query, "context_workspace": "D:/private"})
    with pytest.raises(ContractViolation, match="context_id"):
        parse_route_query({**query, "context_id": "ctx-0000000000000000"})


@pytest.mark.parametrize(
    "query",
    [
        {"workspace": "unknown"},
        {"workspace": "watch", "data_path": "D:/private/data"},
        {"workspace": "watch", "dataset_id": "../private-data"},
        {"workspace": "watch", "symbol": "D:/private/positions.csv"},
        {"workspace": "watch", "context_id": "ctx-not-a-real-id"},
    ],
)
def test_route_parser_rejects_unknown_or_unsafe_deep_links(query):
    with pytest.raises(ContractViolation):
        parse_route_query(query)


def test_route_parser_defaults_to_watch_but_requires_context_fields():
    restored = parse_route_query({
        "dataset_id": "seeded_demo",
        "symbol": "600000.SH",
        "as_of": "2026-02-27",
    })
    assert isinstance(restored, WorkspaceState)
    assert restored.active_workspace == "watch"
    with pytest.raises(ContractViolation):
        parse_route_query({"workspace": "showcase"})
