import numpy as np
import pandas as pd
import pytest

from portfolio_app.research_result_cache import build_research_cache_key
from portfolio_app.result_store import ResultStore


def key(version='one'):
    return build_research_cache_key(dataset_id='strategy', data_version=version,
        processing={'revision': 'test'}, engine_id='session-task.v1')


def test_restart_restores_exact_arrays_types_missing_values_and_provenance(tmp_path):
    from portfolio_app.research import SingleStockResearchResult
    from portfolio_app.temporal_contracts import SessionCalendar
    frame = pd.DataFrame({'trade_date': pd.date_range('2025-01-02', periods=3),
        'equity': [1., 1.125, np.nan], 'count': pd.Series([1, None, 3], dtype='Int64')})
    frame.attrs['session_calendar'] = SessionCalendar('fixture', 'cn_stock', 'Asia/Shanghai',
        ('2025-01-02', '2025-01-03'), 'verified')
    result = {'result': SingleStockResearchResult(frame, {'total_return': .125},
        {'missing': None}, [{'date': pd.Timestamp('2025-01-03'), 'quantity': np.int64(100)}], {}),
        'symbols': ('600000.SH',), 'nan': float('nan'), 'literal': {'type': 'frame', 'file': '../x'}}
    store = ResultStore(tmp_path)
    store.save('task-one', key(), result)
    restored = ResultStore(tmp_path).load('task-one')
    assert type(restored['result']) is SingleStockResearchResult
    pd.testing.assert_frame_equal(restored['result'].frame, frame, check_exact=True)
    assert restored['result'].frame.attrs == frame.attrs
    assert restored['symbols'] == ('600000.SH',)
    assert np.isnan(restored['nan'])
    assert restored['literal'] == result['literal']
    assert restored['result'].trade_events[0]['date'] == pd.Timestamp('2025-01-03')
    restored['result'].frame.loc[0, 'equity'] = 999
    assert store.load('task-one')['result'].frame.equity.iloc[0] == 1.


def test_task_idempotence_conflicting_reuse_and_key_binding(tmp_path):
    store = ResultStore(tmp_path)
    store.save('task-one', key(), {'curve': [1., 1.2]})
    store.save('task-one', key(), {'curve': [1., 1.2]})
    assert len(store.records()) == 1
    with pytest.raises(ValueError):
        store.save('task-one', key(), {'curve': [1., 9.]})
    with pytest.raises(ValueError):
        store.load('task-one', expected_key=key('different'))
    assert store.load('task-one')['curve'] == [1., 1.2]


def test_corrupt_or_missing_arrays_and_manifests_never_restore(tmp_path):
    store = ResultStore(tmp_path)
    store.save('array', key(), {'frame': pd.DataFrame({'x': [1., 2.]})})
    array = next((tmp_path / 'runs' / 'array').glob('*.parquet'))
    array.write_bytes(b'broken')
    with pytest.raises(ValueError, match='校验'):
        store.load('array')
    array.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        store.load('array')
    store.save('meta', key(), {'x': 2})
    manifest = tmp_path / 'runs' / 'meta' / 'manifest.json'
    manifest.write_text('{}', encoding='utf8')
    with pytest.raises(ValueError):
        store.load('meta')


def test_partial_files_index_failure_and_unsupported_objects_do_not_publish(tmp_path, monkeypatch):
    store = ResultStore(tmp_path)
    original = store._publish
    monkeypatch.setattr(store, '_publish', lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        store.save('partial', key(), {'frame': pd.DataFrame({'x': [1]})})
    assert store.records() == []
    with pytest.raises(FileNotFoundError):
        store.load('partial')
    monkeypatch.setattr(store, '_publish', original)
    store.save('partial', key(), {'frame': pd.DataFrame({'x': [1]})})
    with pytest.raises(TypeError):
        store.save('unsupported', key(), {'unsafe': object()})
    assert [r['task_id'] for r in store.records()] == ['partial']
    for identifier in ('../escape', 'x/y', ''):
        with pytest.raises(ValueError):
            store.load(identifier)


def test_index_failure_can_resume_same_complete_bundle_without_exposing_partial(tmp_path, monkeypatch):
    store = ResultStore(tmp_path)
    original = store._index
    monkeypatch.setattr(store, '_index', lambda *a: (_ for _ in ()).throw(OSError('index failed')))
    value = {'frame': pd.DataFrame({'nav': [1., 1.25]})}
    with pytest.raises(OSError):
        store.save('index-failure', key(), value)
    assert store.records() == []
    with pytest.raises(FileNotFoundError):
        store.load('index-failure')
    monkeypatch.setattr(store, '_index', original)
    store.save('index-failure', key(), value)
    pd.testing.assert_frame_equal(store.load('index-failure')['frame'], value['frame'])


def test_fresh_python_process_reads_exact_saved_array(tmp_path):
    import subprocess
    import sys
    store = ResultStore(tmp_path)
    store.save('restart', key(), {'frame': pd.DataFrame({'nav': [1., 1.25, 1.125]})})
    script = ('from portfolio_app.result_store import ResultStore; import sys; '
        'v=ResultStore(sys.argv[1]).load("restart"); '
        'assert v["frame"].nav.tolist()==[1.,1.25,1.125]; print("restored")')
    run = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == 'restored'


def test_actual_cash_account_result_restores_ledger_fills_and_drilldown(tmp_path):
    from portfolio_app.offline_execution import ExecutionSpec
    from portfolio_app.portfolio_recipe import PortfolioRecipe
    from portfolio_app.portfolio_workspace import run_portfolio_workspace, portfolio_drilldown
    close = np.arange(40, dtype=float) + 10
    frame = pd.DataFrame(dict(trade_date=pd.bdate_range('2025-01-02', periods=40),
        symbol='AAA', open=close, high=close, low=close, close=close, volume=10000))
    result = run_portfolio_workspace({'AAA': frame},
        recipe=PortfolioRecipe.from_dict(dict(recipe_id='fixture', target_weights={'AAA': .8},
            cash_weight=.2, lot_size=1)),
        spec=ExecutionSpec('next', 'close', 'next_close', 10, 0, 'us_stock'),
        strategy_key='trend', params={'fast_window': 5, 'slow_window': 30}, initial_cash=10000)
    store = ResultStore(tmp_path)
    store.save('account', key(), {'baseline': result})
    restored = ResultStore(tmp_path).load('account')['baseline']
    pd.testing.assert_frame_equal(restored.accounting.ledger, result.accounting.ledger, check_exact=True)
    pd.testing.assert_frame_equal(restored.positions, result.positions, check_exact=True)
    assert restored.fills == result.fills and restored.metrics == result.metrics
    date = result.fills[0]['fill_date']
    pd.testing.assert_frame_equal(portfolio_drilldown(restored, date=date)['ledger'],
        portfolio_drilldown(result, date=date)['ledger'])
