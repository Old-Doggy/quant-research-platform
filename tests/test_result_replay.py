import copy

import numpy as np
import pandas as pd
import pytest

from portfolio_app.research import run_single_stock_research
from portfolio_app.research_result_cache import build_research_cache_key
from portfolio_app.result_replay import replay_saved, single_stock_replay_inputs
from portfolio_app.result_store import ResultStore


def fixture():
    close = 10 + np.sin(np.arange(100) / 5.) + np.arange(100) / 100.
    frame = pd.DataFrame(dict(symbol='FIXTURE', trade_date=pd.bdate_range('2025-01-02', periods=100),
        open=close, high=close, low=close, close=close, volume=10000))
    frame.attrs['return_contract'] = {'fixture': 'preserve'}
    params = {'fast_window': 5, 'slow_window': 30}
    result = run_single_stock_research(frame, strategy_key='trend', params=params, transaction_cost=.001)
    return frame, params, result


def save(store, value, name='replay'):
    key = build_research_cache_key(dataset_id='strategy', data_version='fixture', processing={}, engine_id='test')
    store.save(name, key, value)


def test_replay_saved_exact_input_curves_events_and_metrics(tmp_path):
    frame, params, research = fixture()
    frame['private_unrelated_note'] = 'exclude me'
    replay = single_stock_replay_inputs(frame, strategy_key='trend', params=params, transaction_cost=.001)
    assert 'private_unrelated_note' not in replay['frame']
    assert 'volume' in replay['frame']
    assert replay['frame'].attrs == frame.attrs
    value = {'single_stock_research': research, 'replay': replay}
    store = ResultStore(tmp_path)
    save(store, value)
    report = replay_saved(ResultStore(tmp_path), 'replay')
    assert report['status'] == 'matched'
    assert report['rows'] == 100 and report['curves'] >= 4
    assert report['trade_events'] == len(research.trade_events)
    pd.testing.assert_frame_equal(store.load('replay')['single_stock_research'].frame, research.frame)


def test_changed_engine_missing_input_or_modified_result_does_not_claim_replay(tmp_path, monkeypatch):
    frame, params, research = fixture()
    replay = single_stock_replay_inputs(frame, strategy_key='trend', params=params, transaction_cost=.001)
    store = ResultStore(tmp_path)
    save(store, {'single_stock_research': research}, 'no-input')
    with pytest.raises(ValueError, match='输入'):
        replay_saved(store, 'no-input')
    changed = copy.deepcopy(research)
    changed.frame.loc[50, 'equity'] += .01
    save(store, {'single_stock_research': changed, 'replay': replay}, 'wrong-point')
    with pytest.raises(ValueError, match='不一致'):
        replay_saved(store, 'wrong-point')
    save(store, {'single_stock_research': research, 'replay': replay})
    monkeypatch.setattr('portfolio_app.result_replay.computation_revision', lambda: 'changed-engine')
    with pytest.raises(ValueError, match='版本'):
        replay_saved(store, 'replay')


def test_unknown_replay_type_is_data_not_callable(tmp_path):
    store = ResultStore(tmp_path)
    save(store, {'replay': {'kind': 'os.system', 'command': 'do not execute'}})
    with pytest.raises(ValueError):
        replay_saved(store, 'replay')


def test_cash_account_replay_checks_ledger_positions_orders_and_fees(tmp_path):
    from portfolio_app.offline_execution import ExecutionSpec
    from portfolio_app.portfolio_recipe import PortfolioRecipe
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    from portfolio_app.result_replay import portfolio_replay_inputs
    frame, params, _ = fixture()
    frame['tradability'] = 'tradable'
    frame.loc[35, 'tradability'] = 'suspended'
    recipe = PortfolioRecipe.from_dict(dict(recipe_id='replay', target_weights={'FIXTURE': .8},
        cash_weight=.2, lot_size=1))
    spec = ExecutionSpec('next-close', 'close', 'next_close', 10, 0, 'us_stock')
    result = run_portfolio_workspace({'FIXTURE': frame}, recipe=recipe, spec=spec,
        strategy_key='trend', params=params, initial_cash=10000.)
    replay = portfolio_replay_inputs({'FIXTURE': frame}, recipe=recipe, spec=spec,
        strategy_key='trend', params=params, initial_cash=10000.)
    assert 'tradability' in replay['frames']['FIXTURE']
    store = ResultStore(tmp_path)
    save(store, {'baseline': result, 'replay': replay})
    report = replay_saved(store, 'replay')
    assert report['status'] == 'matched' and report['rows'] == 100
    assert report['trade_events'] == len(result.fills)
    changed = copy.deepcopy(result)
    changed.fills[0]['fee'] += 1.
    save(store, {'baseline': changed, 'replay': replay}, 'changed-fee')
    with pytest.raises(ValueError, match='不一致'):
        replay_saved(store, 'changed-fee')


def test_factor_replay_checks_ic_group_returns_turnover_and_cross_sections(tmp_path):
    from portfolio_app.factor_compute import BASIC_FACTOR_SPECS
    from portfolio_app.factor_workspace import FactorResearchConfig
    from portfolio_app.factor_research_job import FactorResearchJobService
    from portfolio_app.result_replay import factor_replay_inputs
    frame, _, _ = fixture()
    frame['vol'] = frame.volume
    all_frames = [frame.assign(symbol=s, close=frame.close * (1 + i * .01)) for i, s in enumerate(('AAA', 'BBB', 'CCC'))]
    data = pd.concat(all_frames, ignore_index=True)
    # Use valid OHLC for each synthetic security.
    for field in ('open', 'high', 'low'): data[field] = data.close
    config = FactorResearchConfig('basic.return_20d', 'fixture', str(data.trade_date.min().date()),
        str(data.trade_date.max().date()), min_assets_per_date=3, quantiles=3, max_missing_ratio=.6)
    job = FactorResearchJobService(specs=BASIC_FACTOR_SPECS).submit(data, config)
    assert job.result is not None
    value = {**job.result, 'replay': factor_replay_inputs(data, config=config)}
    store = ResultStore(tmp_path)
    save(store, value)
    report = replay_saved(store, 'replay')
    assert report['status'] == 'matched' and report['rows'] == len(job.result['detail'])
    changed = copy.deepcopy(value)
    changed['analysis']['ic_series'][0]['ic'] = .9999
    save(store, changed, 'changed-ic')
    with pytest.raises(ValueError, match='不一致'):
        replay_saved(store, 'changed-ic')


def test_factor_zip_export_excludes_internal_replay_dataframe():
    from portfolio_app.factor_research_view import factor_export_result
    from portfolio_app.factor_research_archive import save_factor_archive, open_factor_archive
    result = {'config': {'disclosure_mode': 'private_local'}, 'analysis': {'ic_series': []},
        'replay': {'frame': pd.DataFrame({'close': [1.]})}, 'data_mode': 'synthetic'}
    exported = factor_export_result(result)
    assert 'replay' not in exported
    archive = save_factor_archive(result['config'], exported)
    assert open_factor_archive(archive)[2]['analysis'] == result['analysis']
    assert 'replay' in result
