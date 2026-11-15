from dataclasses import replace
from urllib.parse import urlencode

import pytest

from portfolio_app.research_context import ContractViolation, ResearchContext
from portfolio_app.workspace_router import build_workspace_state, encode_route_query, parse_route_query, switch_workspace


def test_nondefault_context_round_trips_through_all_seven_pages():
    context = ResearchContext(dataset_id='seeded_demo', workspace='portfolio',
        symbols=('600000.SH', '000001.SZ'), as_of='2026-02-27', date_start='2025-02-01',
        date_end='2026-01-31', indicator_ids=('MA', 'RSI'), strategy_id='trend', factor_id='basic.return_20d',
        factor_version='v2', snapshot_id='snapshot-a', dataset_generation=7, price_basis='raw',
        return_definition='total_return_v1', universe_id='historical-pool', universe_version='v3',
        disclosure_mode='public_redacted')
    for page in ('watch', 'factors', 'strategy', 'portfolio', 'data', 'experiments', 'showcase'):
        state = switch_workspace(build_workspace_state(context), page)
        assert parse_route_query(encode_route_query(state)) == state


def test_old_schema_link_preserves_old_context_hash():
    context = ResearchContext(dataset_id='seeded_demo', workspace='watch', symbol='600000.SH',
                              as_of='2026-02-27', schema_version='1.0')
    query = dict(workspace='watch', dataset_id='seeded_demo', symbol='600000.SH',
                 as_of='2026-02-27', context_id=context.context_id)
    assert parse_route_query(query).context == context


def test_long_universe_link_uses_persistent_local_reference(monkeypatch, tmp_path):
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path / 'machine-a'))
    context = ResearchContext(dataset_id='seeded_demo', workspace='portfolio',
        symbols=tuple(f'{i:06d}.SH' for i in range(1000)), as_of='2026-02-27')
    state = build_workspace_state(context)
    query = encode_route_query(state)
    assert 'context_ref' in query and 'symbols' not in query
    assert len(urlencode(query)) < 1800
    assert parse_route_query(query) == state
    assert parse_route_query({**query, 'workspace': 'experiments'}).context == context
    with pytest.raises(ContractViolation):
        parse_route_query({**query, 'symbols': '600000.SH'})
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path / 'machine-b'))
    with pytest.raises(ContractViolation, match='本机.*不存在'):
        parse_route_query(query)


def test_hash_does_not_allow_tampered_display_or_provenance():
    context = ResearchContext(dataset_id='seeded_demo', workspace='watch', symbol='600000.SH', as_of='2026-02-27')
    query = encode_route_query(build_workspace_state(context))
    with pytest.raises(ContractViolation, match='context_id'):
        parse_route_query({**query, 'snapshot_id': 'different-snapshot'})
    # Display-only changes remain valid and leave the calculation identity alone.
    restored = parse_route_query({**query, 'indicator_ids': 'MACD'})
    assert restored.context == replace(context, indicator_ids=('MACD',))
