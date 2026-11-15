from dataclasses import asdict
import pytest


def test_action_rule_calendar_and_snapshot_metadata_all_change_input_identity():
    from test_portfolio_workspace import inputs
    from portfolio_app.research_result_cache import build_data_fingerprint
    from portfolio_app.temporal_contracts import build_session_calendar
    from test_entitlement_ledger import action
    from test_instrument_rules import dated_rule
    frame = inputs()[0]['AAA']
    original = build_data_fingerprint(frame)
    calendar = build_session_calendar(frame.trade_date.tolist(), calendar_id='test', market='US', timezone='UTC')
    for key, value in [('corporate_actions', [action()]), ('instrument_rules', [dated_rule()]),
                       ('session_calendar', calendar), ('snapshot', {'snapshot_id': 'one', 'generation': 1}),
                       ('return_contract', {'definition': 'total_return_v1'}),
                       ('field_units', {'volume': 'shares'}),
                       ('research_capabilities', {'corporate_action_backtest': False}),
                       ('normalization', {'profile': 'tushare_a_daily', 'version': '1.0'})]:
        changed = frame.copy(deep=True)
        changed.attrs[key] = value
        assert build_data_fingerprint(changed) != original, key
    browsed = frame.copy(deep=True)
    browsed.attrs['browsing_state'] = {'date': '2025-01-02', 'zoom': 20}
    assert build_data_fingerprint(browsed) == original


def test_snapshot_reference_is_content_addressed_and_generation_is_explicit():
    from portfolio_app.snapshot_contracts import build_frame_snapshot, SnapshotReference
    from test_portfolio_workspace import inputs
    frame = inputs()[0]['AAA']
    first = build_frame_snapshot(frame, dataset_id='test', generation=1, price_basis='raw')
    assert SnapshotReference.from_dict(asdict(first)) == first
    assert first.snapshot_id.startswith('snapshot-') and len(first.content_sha256) == 64
    assert first.completeness == 'unverified'
    assert build_frame_snapshot(frame, dataset_id='test', generation=2, price_basis='raw').snapshot_id != first.snapshot_id
    changed = frame.copy()
    changed.loc[0, 'close'] = 11
    assert build_frame_snapshot(changed, dataset_id='test', generation=1, price_basis='raw').snapshot_id != first.snapshot_id
    with pytest.raises(ValueError):
        SnapshotReference.from_dict({**asdict(first), 'snapshot_id': 'snapshot-forged'})


def test_local_file_cache_reloads_same_path_even_when_size_and_mtime_match(tmp_path):
    import os
    import pandas as pd
    from portfolio_app.market_file_cache import cached_local_symbol
    directory = tmp_path / 'daily_raw_merged'
    directory.mkdir()
    path = directory / 'AAA.parquet'
    dates = pd.to_datetime(['2025-01-02', '2025-01-03'])
    frame = pd.DataFrame(dict(trade_date=dates, ts_code='AAA', open=10., high=11., low=9., close=10., vol=1000.))
    frame.to_parquet(path)
    stamp = path.stat()
    first = cached_local_symbol(str(tmp_path), 'AAA', 'raw')
    frame['close'] = 11.
    frame.to_parquet(path)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    second = cached_local_symbol(str(tmp_path), 'AAA', 'raw')
    assert first.close.tolist() == [10., 10.]
    assert second.close.tolist() == [11., 11.]
    assert first.attrs['snapshot']['snapshot_id'] != second.attrs['snapshot']['snapshot_id']
    assert second.attrs['research_dataset']['price_basis'] == 'raw'


def test_registry_record_contains_stable_snapshot_and_monotonic_generation(tmp_path):
    from portfolio_app.dataset_registry import register_dataset, load_dataset_registry
    from test_dataset_registry import _manifest, _write_source
    from portfolio_app.data_catalog import generate_seeded_baseline
    source = tmp_path / 'input.csv'
    registry = tmp_path / 'registry'
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()
    _write_source(source, '10')
    register_dataset(registry, _manifest(frame), source, confirm=True)
    first = load_dataset_registry(registry)['datasets'][0]
    _write_source(source, '11')
    register_dataset(registry, _manifest(frame), source, confirm=True)
    rows = load_dataset_registry(registry)['datasets']
    assert [r['snapshot']['generation'] for r in rows] == [1, 2]
    assert rows[0] == first
    assert rows[0]['snapshot']['snapshot_id'] != rows[1]['snapshot']['snapshot_id']
