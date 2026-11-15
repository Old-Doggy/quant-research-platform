from dataclasses import replace

import pytest

from portfolio_app.research_context import ContractViolation, ResearchContext


def context(**changes):
    values = dict(dataset_id='seeded_demo', workspace='watch', symbol='600000.SH',
                  as_of='2026-02-27', date_start='2025-01-01', snapshot_id='snapshot-a',
                  dataset_generation=1, price_basis='raw', return_definition='total_return_v1')
    return ResearchContext(**{**values, **changes})


@pytest.mark.parametrize('changes', [dict(snapshot_id='snapshot-b'), dict(dataset_generation=2),
    dict(price_basis='qfq'), dict(return_definition='price_return_v1'), dict(date_start='2025-02-01'),
    dict(factor_id='roe', factor_version='v2'), dict(universe_id='csi300', universe_version='v1')])
def test_research_inputs_change_identity(changes):
    assert context().context_id != context(**changes).context_id


def test_display_indicators_and_workspace_do_not_change_new_research_identity():
    original = context()
    assert replace(original, indicator_ids=('MA', 'RSI')).context_id == original.context_id
    assert replace(original, workspace='showcase').context_id == original.context_id


def test_browsing_and_result_reference_are_separate_from_research_inputs():
    from portfolio_app.research_context import BrowsingState, ResultReference
    original = context()
    browsing = BrowsingState(selected_date='2026-02-26', visible_start='2026-01-01', visible_end='2026-02-27')
    result = ResultReference(run_id='run-0123456789abcdef', context_id=original.context_id,
                             snapshot_id='snapshot-a')
    assert replace(browsing, selected_date='2026-02-25') != browsing
    assert result.context_id == original.context_id
    assert original.context_id == context().context_id


def test_legacy_context_identity_can_be_read_but_upgrade_requires_provenance():
    from portfolio_app.context_migration import load_context, upgrade_context
    legacy = ResearchContext(dataset_id='seeded_demo', workspace='watch', symbol='600000.SH',
                             as_of='2026-02-27', schema_version='1.0')
    assert load_context(legacy.to_dict()) == legacy
    with pytest.raises(ContractViolation, match='snapshot_id.*dataset_generation.*price_basis.*return_definition'):
        upgrade_context(legacy.to_dict())
    upgraded = upgrade_context(legacy.to_dict(), snapshot_id='snapshot-a', dataset_generation=1,
                               price_basis='raw', return_definition='total_return_v1')
    assert upgraded.schema_version == '2.0'
    assert upgraded.snapshot_id == 'snapshot-a'
    assert upgraded.context_id != legacy.context_id


@pytest.mark.parametrize('changes', [dict(dataset_generation=True), dict(dataset_generation=-1),
    dict(snapshot_id='../private'), dict(price_basis='guess'), dict(schema_version='99.0')])
def test_invalid_provenance_is_rejected(changes):
    with pytest.raises(ContractViolation):
        context(**changes)


def test_semantic_factor_versions_and_corrupt_serialized_identity():
    from portfolio_app.context_migration import load_context
    original = context(factor_version='1.0.0', universe_version='2026.11')
    assert load_context(original.to_dict()) == original
    with pytest.raises(ContractViolation, match='context_id'):
        load_context({**original.to_dict(), 'date_start': '2024-01-01'})
    with pytest.raises(ContractViolation, match='missing.*as_of'):
        load_context({'dataset_id': 'seeded_demo', 'workspace': 'watch'})
