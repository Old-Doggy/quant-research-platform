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
