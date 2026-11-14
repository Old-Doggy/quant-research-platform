from copy import deepcopy
import json

import pandas as pd
import pytest

from portfolio_app.research_manifest import (
    build_run_manifest, compare_run_manifests, export_run_manifest,
)


def bars():
    return pd.DataFrame(dict(trade_date=pd.date_range('2026-01-01', periods=5),
                             symbol='DEMO', close=[10., 11., 12., 11., 13.]))


def manifest(**changes):
    args = dict(frame=bars(), engine_id='research-proxy.v1', features={'window': 20},
                labels={'kind': 'none'}, execution={'fill': 'next_close'},
                parameters={'window': 20, 'source': 'D:/private/core.py'},
                cost={'turnover': .001}, evaluation='fixed_parameter', processing={'version': 1})
    args.update(changes)
    return build_run_manifest(**args)


def test_manifest_identifies_each_semantic_input_without_raw_private_fields():
    original = manifest()
    assert original == manifest()
    assert original['runtime']['python']
    assert {'pandas', 'numpy', 'streamlit', 'plotly'} <= original['runtime']['libraries'].keys()
    assert all(len(original['hashes'][name]) == 64 for name in
               ('data', 'feature', 'label', 'execution', 'parameters', 'engine', 'processing'))
    assert 'D:/private' not in json.dumps(original)
    for arg, field in [('features', 'feature'), ('labels', 'label'),
                       ('execution', 'execution'), ('parameters', 'parameters')]:
        assert manifest(**{arg: {'changed': True}})['hashes'][field] != original['hashes'][field]
    changed = bars()
    changed.loc[0, 'close'] += 1
    assert manifest(frame=changed)['hashes']['data'] != original['hashes']['data']


def test_public_projection_has_no_private_fingerprints_and_requires_local_permission():
    private = manifest()
    public = export_run_manifest(private, mode='public_redacted', local_access=False)
    assert set(public) == {'schema_version', 'disclosure', 'reproducibility'}
    assert 'hashes' not in json.dumps(public)
    with pytest.raises(PermissionError):
        export_run_manifest(private, mode='private_local', local_access=False)
    assert export_run_manifest(private, mode='private_local', local_access=True) == private


@pytest.mark.parametrize('change', [dict(cost={'turnover': .002}),
    dict(engine_id='different-engine'), dict(execution={'fill': 'next_open'}),
    dict(labels={'horizon': 20}), dict(frame=bars().iloc[1:]),
    dict(processing={'version': 2}), dict(evaluation='in_sample')])
def test_mixed_basis_has_differences_and_no_ranks(change):
    result = compare_run_manifests([manifest(), manifest(**change)])
    assert not result['ranking_allowed']
    assert result['differences']
    assert len(result['runs']) == 2
    assert all('rank' not in row for row in result['runs'])


def test_parameters_can_vary_but_missing_redacted_or_tampered_manifests_cannot_rank():
    assert compare_run_manifests([manifest(), manifest(parameters={'window': 25})])['ranking_allowed']
    for invalid in ({}, {'schema_version': 'run-manifest.v1'},
                    export_run_manifest(manifest(), mode='public_redacted', local_access=False)):
        assert not compare_run_manifests([manifest(), invalid])['ranking_allowed']
    damaged = deepcopy(manifest())
    damaged['basis']['period']['end'] = '2099-01-01'
    assert not compare_run_manifests([manifest(), damaged])['ranking_allowed']
