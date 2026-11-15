import pandas as pd
import pytest

from portfolio_app.research import run_single_stock_research, run_portfolio_research
from portfolio_app.portfolio_workspace import run_portfolio_workspace
from portfolio_app.offline_execution import ExecutionSpec
from portfolio_app.portfolio_recipe import PortfolioRecipe
from portfolio_app.research_integrity import IntegrityViolation, audit_research_input


def bars():
    dates = pd.bdate_range('2025-01-02', periods=80)
    close = pd.Series(range(80), dtype=float) + 20
    return pd.DataFrame(dict(trade_date=dates, symbol='AAA', open=close, high=close + 1,
        low=close - 1, close=close, vol=1000, roe=12., pb=2.))


def run(kind, frame, strategy='quality_momentum'):
    if kind == 'single':
        return run_single_stock_research(frame, strategy_key=strategy)
    if kind == 'weighted':
        return run_portfolio_research({'AAA': frame}, strategy_key=strategy, target_weights={'AAA': 1.})
    return run_portfolio_workspace({'AAA': frame}, strategy_key=strategy,
        recipe=PortfolioRecipe.from_dict(dict(recipe_id='test', target_weights={'AAA': 1.}, cash_weight=0., lot_size=1)),
        spec=ExecutionSpec('next-close', 'close', 'next_close', 0, 0, 'us_stock'))


@pytest.mark.parametrize('kind', ['single', 'weighted', 'account'])
def test_actual_entrypoints_reject_missing_and_future_financial_times(kind):
    frame = bars()
    with pytest.raises(IntegrityViolation, match='可用时点'):
        run(kind, frame)
    frame['roe_available_at'] = frame.trade_date
    frame['pb_available_at'] = frame.trade_date + pd.Timedelta(days=1)
    with pytest.raises(IntegrityViolation, match='晚于决策.*pb_available_at'):
        run(kind, frame)
    frame['pb_available_at'] = frame.trade_date
    assert run(kind, frame) is not None


@pytest.mark.parametrize('kind', ['single', 'weighted', 'account'])
def test_price_only_research_does_not_require_unused_financial_fields(kind):
    assert run(kind, bars().drop(columns=['roe', 'pb']), strategy='trend') is not None


def test_per_field_missing_time_cannot_be_hidden_by_generic_time():
    frame = bars()
    frame['feature_available_at'] = frame.trade_date
    frame['roe_available_at'] = frame.trade_date
    frame.loc[3, 'roe_available_at'] = pd.NaT
    with pytest.raises(IntegrityViolation, match='缺失'):
        audit_research_input(frame, feature_fields=('roe', 'pb'))


def test_missing_required_financial_values_are_reported_before_computation():
    from portfolio_app.strategy_catalog import strategy_input_status
    frame = bars().drop(columns=['roe'])
    status = strategy_input_status(frame, 'quality_momentum')
    assert not status['can_run']
    assert 'roe' in status['message'] and '数据中心' in status['action']


def test_direct_signal_and_auxiliary_reports_cannot_bypass_timing_gate():
    from portfolio_app.strategies import generate_signal
    from portfolio_app.reports import build_strategy_comparison
    frame = bars()
    frame['return'] = frame.close.pct_change()
    with pytest.raises(IntegrityViolation, match='可用时点'):
        generate_signal(frame, 'quality_momentum')
    report = build_strategy_comparison(frame)
    row = report.set_index('strategy_key').loc['quality_momentum']
    assert row['status'] == 'data_blocked' and pd.isna(row['annual_return'])
    assert set(report.loc[report.strategy_key.ne('quality_momentum'), 'status']) == {'available'}


def test_valid_financial_timestamps_survive_experiment_export_and_replay():
    from portfolio_app.experiments import build_experiment, reproduce_experiment
    frame = bars()
    frame['roe_available_at'] = frame.trade_date
    frame['pb_available_at'] = frame.trade_date
    archive = build_experiment(frame, dict(mode='single', symbols=['AAA'],
        strategy_key='quality_momentum', transaction_cost=.001))
    assert not reproduce_experiment(archive).empty
