"""Explicit, version-bound replay of stored research inputs; no dynamic execution."""
import copy
from dataclasses import asdict
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


def _source_frame(frame, fields=()):
    allowed = set(REQUIRED_PRICE_COLUMNS) | set(OPTIONAL_COLUMNS) | set(fields) | {'symbol', 'return', 'volume',
        'decision_at', 'available_at', 'feature_available_at', 'group_available_at', 'adjustment_available_at',
        'valuation_status', 'tradability', 'price_status'}
    allowed |= {field + '_available_at' for field in OPTIONAL_COLUMNS}
    return frame[[c for c in frame if c in allowed]].copy(deep=True)


def single_stock_replay_inputs(frame, *, strategy_key, params, transaction_cost,
                             start_date=None, end_date=None):
    source = _source_frame(frame, strategy_input_fields(strategy_key))
    return dict(schema='research-replay.v1', kind='single_stock', revision=computation_revision(),
        frame=source, input_identity=_input_identity(source),
        config=dict(strategy_key=strategy_key, params=copy.deepcopy(params),
            transaction_cost=float(transaction_cost),
            start_date=pd.Timestamp(start_date).isoformat() if start_date is not None else None,
            end_date=pd.Timestamp(end_date).isoformat() if end_date is not None else None))


def portfolio_replay_inputs(frames, *, recipe, spec, strategy_key, params, initial_cash):
    sources = {s: _source_frame(f, strategy_input_fields(strategy_key)) for s, f in frames.items()}
    return dict(schema='research-replay.v1', kind='cash_portfolio', revision=computation_revision(),
        frames=sources, input_identity={s: _input_identity(f) for s, f in sources.items()},
        config=dict(recipe=recipe.to_dict(), spec=asdict(spec), strategy_key=strategy_key,
            params=copy.deepcopy(params), initial_cash=float(initial_cash)))


def factor_replay_inputs(frame, *, config):
    source = _source_frame(frame)
    return dict(schema='research-replay.v1', kind='factor', revision=computation_revision(),
        frame=source, input_identity=_input_identity(source), config=config.to_dict())


def comparison_replay_inputs(frame, *, config):
    source=_source_frame(frame)
    return dict(schema='research-replay.v1',kind='factor_comparison',revision=computation_revision(),
        frame=source,input_identity=_input_identity(source),config=copy.deepcopy(config))


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
    if replay.get('kind') not in ('single_stock', 'cash_portfolio', 'factor','factor_comparison'):
        raise ValueError('此研究类型尚未接入复算')
    if replay.get('revision') != computation_revision():
        raise ValueError('计算或依赖版本已变化，不能按原版本复算')
    if replay['kind']=='factor_comparison':
        from .factor_comparison import research_factor_comparison
        frame=replay.get('frame')
        if not isinstance(frame,pd.DataFrame) or _input_identity(frame)!=replay.get('input_identity'):
            raise ValueError('比较输入身份不一致')
        actual=research_factor_comparison(frame.copy(deep=True),**replay['config'])
        expected=value.get('comparison',{})
        try:
            for key in ('values','daily','cross_section','ic_correlation','ic_series'):
                pd.testing.assert_frame_equal(actual[key],expected[key],rtol=1e-10,atol=1e-10)
            for key in ('factor_ids','factors','horizon','start','end','method','aggregation','min_assets','min_ic_dates'):
                if actual[key]!=expected[key]: raise AssertionError(key)
        except (AssertionError,KeyError):
            raise ValueError('多因子比较复算不一致') from None
        return dict(status='matched',kind='factor_comparison',sessions=actual['values'].trade_date.nunique(),
            rows=len(actual['values']),curves=len(actual['factors']),trade_events=0)
    if replay['kind'] == 'cash_portfolio':
        return _replay_portfolio(value, replay)
    if replay['kind'] == 'factor':
        return _replay_factor(value, replay)
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
    return dict(status='matched', rows=len(actual.frame), sessions=len(actual.frame), kind='single_stock', curves=len(selected) - 1,
        trade_events=len(actual.trade_events), rtol=1e-10, atol=1e-10)


def _execution_spec(payload):
    from .offline_execution import ExecutionSpec, MarketRuleProfile
    payload = copy.deepcopy(payload)
    if payload.get('market_rule_profile'):
        payload['market_rule_profile'] = MarketRuleProfile(**payload['market_rule_profile'])
    return ExecutionSpec(**payload)


def _replay_portfolio(value, replay):
    from .portfolio_recipe import PortfolioRecipe
    from .portfolio_workspace import run_portfolio_workspace
    frames, expected = replay.get('frames'), value.get('baseline')
    if not isinstance(frames, dict) or expected is None:
        raise ValueError('缺少组合原始输入或结果')
    if {s: _input_identity(f) for s, f in frames.items()} != replay.get('input_identity'):
        raise ValueError('组合原始输入与保存身份不一致')
    config = copy.deepcopy(replay['config'])
    config['recipe'] = PortfolioRecipe.from_dict(config['recipe'])
    config['spec'] = _execution_spec(config['spec'])
    actual = run_portfolio_workspace(frames, **config)
    try:
        for before, after in ((expected.accounting.ledger, actual.accounting.ledger),
                (expected.positions, actual.positions),
                (expected.accounting.symbol_contribution, actual.accounting.symbol_contribution),
                (expected.accounting.leg_contribution, actual.accounting.leg_contribution)):
            pd.testing.assert_frame_equal(before, after, check_exact=False, rtol=1e-10, atol=1e-10)
        for before, after in ((expected.metrics, actual.metrics), (expected.fills, actual.fills),
                (expected.orders, actual.orders), (expected.config, actual.config)):
            if not _equal_values(before, after): raise AssertionError('portfolio')
    except AssertionError as exc:
        raise ValueError('组合复算与保存账本、持仓、成交或指标不一致') from exc
    return dict(status='matched', rows=len(actual.accounting.ledger), sessions=len(actual.accounting.ledger), kind='cash_portfolio', curves=4,
        trade_events=len(actual.fills), rtol=1e-10, atol=1e-10)


def _replay_factor(value, replay):
    from .factor_compute import BASIC_FACTOR_SPECS
    from .factor_research_job import FactorResearchJobService
    from .factor_workspace import FactorResearchConfig
    frame = replay.get('frame')
    if not isinstance(frame, pd.DataFrame) or _input_identity(frame) != replay.get('input_identity'):
        raise ValueError('因子原始输入缺失或与保存身份不一致')
    job = FactorResearchJobService(specs=BASIC_FACTOR_SPECS).submit(frame,
        FactorResearchConfig.from_dict(replay['config']))
    if job.result is None: raise ValueError('因子输入未通过复算检查')
    for field in ('overview', 'analysis', 'detail', 'integrity'):
        if not _equal_values(value.get(field), job.result.get(field)):
            raise ValueError('因子复算与保存IC、分组收益、换手或截面不一致')
    return dict(status='matched', rows=len(job.result['detail']),
        sessions=len({r['trade_date'] for r in job.result['detail']}), kind='factor', curves=2,
        trade_events=0, rtol=1e-10, atol=1e-10)
