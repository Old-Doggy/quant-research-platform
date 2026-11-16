"""Explicit, version-bound replay of stored research inputs; no dynamic execution."""
import copy
import math

import numpy as np
import pandas as pd

from .data import REQUIRED_PRICE_COLUMNS, OPTIONAL_COLUMNS
from .research import run_single_stock_research
from .research_manifest import computation_revision, frame_hash
from .snapshot_contracts import identity_hash, frame_provenance
from .strategy_catalog import strategy_input_fields


def _input_identity(frame):
    return identity_hash(dict(values=frame_hash(frame), provenance=frame_provenance(frame)))


def single_stock_replay_inputs(frame, *, strategy_key, params, transaction_cost,
                             start_date=None, end_date=None):
    allowed = set(REQUIRED_PRICE_COLUMNS) | set(OPTIONAL_COLUMNS) | set(strategy_input_fields(strategy_key)) | {'symbol', 'return', 'volume',
        'decision_at', 'available_at', 'feature_available_at', 'group_available_at', 'adjustment_available_at'}
    allowed |= {field + '_available_at' for field in OPTIONAL_COLUMNS}
    source = frame[[c for c in frame if c in allowed]].copy(deep=True)
    return dict(schema='research-replay.v1', kind='single_stock', revision=computation_revision(),
        frame=source, input_identity=_input_identity(source),
        config=dict(strategy_key=strategy_key, params=copy.deepcopy(params),
            transaction_cost=float(transaction_cost),
            start_date=pd.Timestamp(start_date).isoformat() if start_date is not None else None,
            end_date=pd.Timestamp(end_date).isoformat() if end_date is not None else None))


def _equal_values(expected, actual):
    """Numerics tolerate roundoff; missing observations never compare as zero."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(_equal_values(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, (tuple, list)) and isinstance(actual, type(expected)):
        return len(expected) == len(actual) and all(_equal_values(a, b) for a, b in zip(expected, actual))
    if isinstance(expected, (float, int, np.number)) and not isinstance(expected, (bool, np.bool_)):
        if not isinstance(actual, (float, int, np.number)) or isinstance(actual, (bool, np.bool_)):
            return False
        return (pd.isna(expected) and pd.isna(actual)) or math.isclose(float(expected), float(actual), rel_tol=1e-10, abs_tol=1e-10)
    return expected == actual


def replay_saved(store, task_id):
    """Recompute a supported saved run without modifying it or creating another run."""
    value = store.load(task_id)
    replay = value.get('replay')
    if not isinstance(replay, dict) or replay.get('schema') != 'research-replay.v1':
        raise ValueError('此结果未保存完整复算输入')
    if replay.get('kind') != 'single_stock':
        raise ValueError('此研究类型尚未接入复算')
    if replay.get('revision') != computation_revision():
        raise ValueError('计算或依赖版本已变化，不能按原版本复算')
    frame = replay.get('frame')
    expected = value.get('single_stock_research')
    if not isinstance(frame, pd.DataFrame) or expected is None:
        raise ValueError('缺少原始输入或完整预期结果')
    if _input_identity(frame) != replay.get('input_identity'):
        raise ValueError('原始输入与保存身份不一致')
    actual = run_single_stock_research(frame.copy(deep=True), **replay['config'])
    columns = ('trade_date', 'equity', 'benchmark_equity', 'drawdown', 'strategy_return', 'position')
    selected = [c for c in columns if c in expected.frame]
    try:
        pd.testing.assert_frame_equal(expected.frame[selected].reset_index(drop=True),
            actual.frame[selected].reset_index(drop=True), check_exact=False, rtol=1e-10, atol=1e-10)
        if not _equal_values(expected.metrics, actual.metrics): raise AssertionError('metrics')
        if not _equal_values(expected.trade_events, actual.trade_events): raise AssertionError('events')
        if not _equal_values(expected.strategy_config, actual.strategy_config): raise AssertionError('config')
    except (AssertionError, KeyError) as exc:
        raise ValueError('复算与已保存曲线、指标或交易记录不一致') from exc
    return dict(status='matched', rows=len(actual.frame), curves=len(selected) - 1,
        trade_events=len(actual.trade_events), rtol=1e-10, atol=1e-10)
