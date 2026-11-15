from dataclasses import asdict
import pytest


def dated_rule(**changes):
    return {**dict(rule_id='etf-stock-1', symbol='AAA', market='SSE', asset_type='etf',
        subtype='stock_etf', effective_from='2025-01-01', effective_to='2025-12-31',
        lot_size=100, t_plus_one=True, tick_size=.001, limit_ratio=.1,
        sell_tax_bps=0., source='synthetic_rule_evidence', status='supported'), **changes}


def test_dated_rules_resolve_unique_instrument_and_session_without_fallback():
    from portfolio_app.instrument_rules import InstrumentRuleTable
    old = dated_rule(effective_to='2025-06-30')
    new = dated_rule(rule_id='etf-stock-2', effective_from='2025-07-01', limit_ratio=.2)
    table = InstrumentRuleTable([old, new])
    assert table.resolve('AAA', '2025-06-30').rule_id == old['rule_id']
    assert table.resolve('AAA', '2025-07-01').limit_ratio == .2
    with pytest.raises(ValueError, match='规则'):
        table.resolve('AAA', '2024-12-31')
    with pytest.raises(ValueError, match='规则'):
        table.resolve('BBB', '2025-07-01')
    with pytest.raises(ValueError, match='重叠'):
        InstrumentRuleTable([old, dated_rule(rule_id='overlap')])


def test_etf_subtypes_have_verified_sellability_and_unknown_is_blocked():
    from portfolio_app.instrument_rules import InstrumentRuleTable
    from portfolio_app.offline_market_rules import validate_sellable_quantity
    stock = InstrumentRuleTable([dated_rule()]).resolve('AAA', '2025-01-02')
    bond = InstrumentRuleTable([dated_rule(rule_id='bond', subtype='bond_etf', t_plus_one=False)]).resolve('AAA', '2025-01-02')
    args = dict(total_quantity=100, acquired_today_quantity=100, requested_quantity=100)
    assert not validate_sellable_quantity(**args, rule=stock.asset_rule()).allowed
    assert validate_sellable_quantity(**args, rule=bond.asset_rule()).allowed
    with pytest.raises(ValueError, match='类别|ETF'):
        InstrumentRuleTable([dated_rule(subtype='unknown', t_plus_one=False)])
    with pytest.raises(ValueError, match=r'T\+1|ETF'):
        InstrumentRuleTable([dated_rule(t_plus_one=False)])
    with pytest.raises(ValueError, match='支持'):
        InstrumentRuleTable([dated_rule(status='unsupported')]).resolve('AAA', '2025-01-02')


def test_real_etf_requires_explicit_dated_rules_and_rules_enter_result_identity():
    from test_portfolio_workspace import inputs
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    from portfolio_app.offline_execution import ExecutionSpec
    frames, recipe, _ = inputs()
    spec = ExecutionSpec('next', 'close', 'next_close', 0, 0, 'etf')
    args = dict(recipe=recipe, spec=spec, strategy_key='trend', params={'fast_window': 5, 'slow_window': 30})
    with pytest.raises(ValueError, match='规则|ETF'):
        run_portfolio_workspace(frames, **args)
    # Explicit synthetic rules exercise resolution without asserting market coverage.
    rules = [dated_rule(symbol=s, rule_id=s, effective_from='2024-01-01', effective_to='2024-12-31',
        lot_size=1, market='SYNTHETIC') for s in frames]
    result = run_portfolio_workspace(frames, **args, instrument_rules=rules)
    assert result.inputs['instrument_rules']['status'] == 'explicit'
    from portfolio_app.instrument_rules import InstrumentRuleTable
    assert result.config['instrument_rules'] == [asdict(a) for a in InstrumentRuleTable(rules).rules]
    assert result.inputs['run_manifest']['hashes']['parameters']


def test_rule_metadata_change_invalidates_the_portfolio_draft():
    from test_portfolio_workspace import inputs
    from portfolio_app.portfolio_workspace import portfolio_data_fingerprint
    frames, _, _ = inputs()
    before = portfolio_data_fingerprint(frames)
    frames['AAA'].attrs['instrument_rules'] = [dated_rule(effective_from='2024-01-01', effective_to='2024-12-31')]
    assert portfolio_data_fingerprint(frames) != before


def test_unknown_stock_category_and_mismatching_market_are_rejected():
    from portfolio_app.instrument_rules import InstrumentRuleTable
    for changes in [dict(asset_type='cn_stock', subtype='unknown'), dict(market='US')]:
        with pytest.raises(ValueError, match='类别|市场'):
            InstrumentRuleTable([dated_rule(**changes)])


def test_dated_sell_tax_is_charged_by_planner_and_replayed_in_account():
    import pandas as pd
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    from portfolio_app.portfolio_recipe import PortfolioRecipe
    from portfolio_app.offline_execution import ExecutionSpec
    dates = ['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
    frame = pd.DataFrame(dict(trade_date=pd.to_datetime(dates), symbol='AAA', open=10., high=10., low=10., close=10.))
    schedule = {day: {'AAA': 1. if i == 0 else 0.} for i, day in enumerate(dates)}
    result = run_portfolio_workspace({'AAA': frame}, strategy_key='trend', initial_cash=1000.,
        recipe=PortfolioRecipe.from_dict(dict(recipe_id='tax', target_weights={'AAA': 1.}, cash_weight=0., lot_size=100)),
        spec=ExecutionSpec('next', 'close', 'next_close', 0, 0, 'cn_stock'), target_schedule=schedule,
        instrument_rules=[dated_rule(asset_type='cn_stock', subtype='main_a', tick_size=.01, sell_tax_bps=5.)])
    assert result.accounting.ledger.nav.tolist() == pytest.approx([1000., 1000., 999.5, 999.5])
    assert result.fills[-1]['fee'] == .5
    assert result.metrics['total_cost'] == .5
