import pandas as pd
import pytest

from portfolio_app.factor_rank_strategy import factor_target_schedule, run_factor_strategy
from portfolio_app.factor_strategy_draft import build_factor_strategy_draft
from portfolio_app.research_result_cache import build_data_fingerprint
from portfolio_app.offline_execution import ExecutionSpec
from test_self_audit_regressions import bars


def source_frame():
    return pd.concat([bars('AAA'), bars('BBB').assign(close=lambda f: f.close[::-1].to_numpy(),
        open=lambda f: f.close, high=lambda f: f.close+1, low=lambda f: f.close-1)], ignore_index=True)


def draft_for(frame):
    return build_factor_strategy_draft(dict(status='succeeded', run_id='factor-source',
        config=dict(factor_id='basic.return_1d', dataset_id='source',
                    data_version=build_data_fingerprint(frame), label_id='forward-5d'),
        result_contract=dict(result_id='result-source')), top_k=1, rebalance_frequency='daily')


def test_factor_selection_is_causal_and_leaves_warmup_cash():
    frame = source_frame()
    draft = draft_for(frame)
    schedule = factor_target_schedule(frame, draft, cash_weight=.1)
    first = min(schedule)
    assert sum(schedule[first].values()) == 0
    assert schedule[sorted(schedule)[2]]['AAA'] == pytest.approx(.9)
    changed = frame.copy()
    cutoff = frame.trade_date.unique()[40]
    changed.loc[changed.trade_date > cutoff, 'close'] *= 2
    other = factor_target_schedule(changed, draft_for(changed), cash_weight=.1)
    assert {d:w for d,w in schedule.items() if d <= str(pd.Timestamp(cutoff).date())} == {
        d:w for d,w in other.items() if d <= str(pd.Timestamp(cutoff).date())}


def test_factor_strategy_has_next_session_fills_reconciled_ledger_and_lineage():
    frame = source_frame()
    draft = draft_for(frame)
    spec = ExecutionSpec('factor-next-close', 'close', 'next_close', 10, 2, 'cn_stock')
    result = run_factor_strategy(frame, draft, spec=spec)
    assert result.fills
    assert all(fill['decision_date'] < fill['fill_date'] for fill in result.fills)
    assert result.accounting.ledger.reconciliation_delta.abs().max() < 1e-6
    assert result.config['factor_source']['factor_run_id'] == 'factor-source'
    altered = frame.copy()
    altered.loc[0, 'close'] += .01
    with pytest.raises(ValueError, match='version'):
        run_factor_strategy(altered, draft, spec=spec)


def test_weekly_factor_orders_only_on_first_observed_session_of_week():
    frame = source_frame()
    draft = draft_for(frame)
    draft['selection']['rebalance_frequency'] = 'weekly'
    result = run_factor_strategy(frame, draft,
        spec=ExecutionSpec('next', 'close', 'next_close', 10, 0, 'cn_stock'))
    first_sessions = set(frame.groupby(frame.trade_date.dt.to_period('W')).trade_date.min().dt.strftime('%Y-%m-%d'))
    assert result.orders
    assert {order['decision_date'] for order in result.orders} <= first_sessions
