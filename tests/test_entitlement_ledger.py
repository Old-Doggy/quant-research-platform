import pytest


def action(**changes):
    return dict(action_id='div-1', action_type='cash_dividend', symbol='AAA',
        record_date='2025-01-02', ex_date='2025-01-03', pay_date='2025-01-06',
        cash_per_share=.5, source='synthetic_truth', tax_basis='gross', **changes)


def test_dividend_receivable_preserves_equity_and_is_not_spendable_cash():
    from portfolio_app.entitlement_ledger import EntitlementBook
    book = EntitlementBook([action()])
    held = {'AAA': 100}
    lots = {'AAA': [dict(symbol='AAA', quantity=100, price=10.)]}
    book.record_close('2025-01-02', held, lots)
    assert book.open_session('2025-01-03', held, lots) == 0
    assert book.receivable == 50
    assert 100 + held['AAA'] * 9.5 + book.receivable == 1100
    # Selling after registration does not erase the receivable.
    held['AAA'] = 0
    assert book.open_session('2025-01-06', held, lots) == 50
    assert book.receivable == 0
    assert book.open_session('2025-01-06', held, lots) == 0
    assert book.income_by_symbol == {'AAA': 50.}


def test_sale_before_registration_and_purchase_on_ex_date_receive_nothing():
    from portfolio_app.entitlement_ledger import EntitlementBook
    book = EntitlementBook([action()])
    book.record_close('2025-01-02', {}, {})
    assert book.open_session('2025-01-03', {'AAA': 100}, {}) == 0
    assert book.receivable == 0
    assert book.open_session('2025-01-06', {'AAA': 100}, {}) == 0


def test_missing_record_holdings_and_unknown_tax_are_explicit():
    from portfolio_app.entitlement_ledger import EntitlementBook
    from portfolio_app.corporate_actions import CorporateActionError
    book = EntitlementBook([action()])
    with pytest.raises(CorporateActionError, match='登记日'):
        book.open_session('2025-01-03', {'AAA': 100}, {})
    with pytest.raises(CorporateActionError, match='tax_basis'):
        EntitlementBook([{**action(), 'tax_basis': 'estimated_precise'}])


def test_cash_dividend_reconciles_in_shared_accounting_with_delayed_payment():
    from portfolio_app.portfolio_accounting import build_portfolio_accounting
    dates = ['2025-01-02', '2025-01-03', '2025-01-06']
    result = build_portfolio_accounting(dates=dates, prices={'AAA': dict(zip(dates, [10., 9.5, 9.5]))},
        fills=[dict(fill_id='buy', fill_date=dates[0], symbol='AAA', side='BUY', quantity=100, price=10.)],
        initial_cash=1100., corporate_actions=[action()])
    assert result.ledger.nav.tolist() == [1100., 1100., 1100.]
    assert result.ledger.cash.tolist() == [100., 100., 150.]
    assert result.ledger.receivables.tolist() == [0., 50., 0.]
    assert result.diagnostics['contribution_status'] == 'reconciled'
    assert result.diagnostics['dividend_tax'] == 'gross_before_tax'


def test_workspace_uses_receivable_in_nav_without_spending_it_early():
    import pandas as pd
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    from portfolio_app.portfolio_recipe import PortfolioRecipe
    from portfolio_app.offline_execution import ExecutionSpec
    dates = ['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-06']
    frame = pd.DataFrame(dict(trade_date=pd.to_datetime(dates), symbol='AAA',
        open=[10., 10., 9.5, 9.5], high=[10., 10., 9.5, 9.5],
        low=[10., 10., 9.5, 9.5], close=[10., 10., 9.5, 9.5]))
    schedule = {day: {'AAA': 1.} for day in dates}
    result = run_portfolio_workspace({'AAA': frame}, strategy_key='trend', initial_cash=1100.,
        recipe=PortfolioRecipe.from_dict(dict(recipe_id='test', target_weights={'AAA': 1.}, cash_weight=0., lot_size=1)),
        spec=ExecutionSpec('close', 'close', 'next_close', 0, 0, 'us_stock'),
        target_schedule=schedule, corporate_actions=[action()])
    assert result.accounting.ledger.nav.tolist() == [1100.] * 4
    assert result.accounting.ledger.receivables.tolist() == [0., 0., 55., 0.]
    assert all(fill['fill_date'] != '2025-01-03' or fill['side'] != 'BUY' for fill in result.fills)
    assert result.config['corporate_actions'][0]['action_id'] == 'div-1'


def test_receivable_cannot_finance_a_purchase_before_payment():
    from portfolio_app.portfolio_accounting import build_portfolio_accounting
    dates = ['2025-01-02', '2025-01-03', '2025-01-06']
    with pytest.raises(ValueError, match='insufficient cash'):
        build_portfolio_accounting(dates=dates, prices={'AAA': dict(zip(dates, [10., 9.5, 9.5]))},
            fills=[dict(fill_id='buy', fill_date=dates[0], symbol='AAA', side='BUY', quantity=100, price=10.),
                   dict(fill_id='early', fill_date=dates[1], symbol='AAA', side='BUY', quantity=11, price=9.5)],
            initial_cash=1100., corporate_actions=[action()])


def test_events_duplicate_and_unsupported_type_are_rejected_before_booking():
    from portfolio_app.entitlement_ledger import EntitlementBook
    with pytest.raises(ValueError, match='ID重复'):
        EntitlementBook([action(), action()])
    with pytest.raises(ValueError, match='未支持'):
        EntitlementBook([{**action(), 'action_type': 'rights_issue'}])


@pytest.mark.parametrize('changes', [dict(cash_per_share='0.5'), dict(cash_per_share=True),
    dict(source=['unusable']), dict(symbol=' '), dict(record_date='20250102')])
def test_malformed_actions_raise_a_domain_error(changes):
    from portfolio_app.corporate_actions import CorporateActionError, normalize_actions
    with pytest.raises(CorporateActionError):
        normalize_actions([{**action(), **changes}])


def test_entitlements_reject_reversing_the_session_clock():
    from portfolio_app.entitlement_ledger import EntitlementBook
    book = EntitlementBook([action()])
    book.record_close('2025-01-02', {}, {})
    book.open_session('2025-01-06', {}, {})
    with pytest.raises(ValueError, match='倒退'):
        book.open_session('2025-01-03', {}, {})


def test_declared_events_reach_baseline_and_every_scenario():
    from test_portfolio_workspace import inputs
    from portfolio_app.portfolio_workspace import run_portfolio_workspace, portfolio_scenarios
    frames, recipe, spec = inputs()
    dates = frames['AAA'].trade_date.dt.strftime('%Y-%m-%d').tolist()
    event = {**action(), 'record_date': dates[31], 'ex_date': dates[32], 'pay_date': dates[34]}
    frames['AAA'].attrs['corporate_actions'] = [event]
    result = run_portfolio_workspace(frames, recipe=recipe, spec=spec, strategy_key='trend',
        params={'fast_window': 5, 'slow_window': 30}, initial_cash=10000)
    from dataclasses import asdict
    from portfolio_app.corporate_actions import normalize_actions
    normalized = [asdict(a) for a in normalize_actions([event])]
    assert result.config['corporate_actions'] == normalized
    report = portfolio_scenarios(frames, recipe=recipe, spec=spec, strategy_key='trend',
        params={'fast_window': 5, 'slow_window': 30}, initial_cash=10000,
        variants=[('cost', 'cost', 20)])
    assert report.status.eq('available').all()
    assert all(config['corporate_actions'] == normalized for config in report.config)
    assert report.iloc[0].total_return == result.metrics['total_return']


def test_explicit_events_cannot_hide_other_known_events():
    from test_portfolio_workspace import inputs
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    frames, recipe, spec = inputs()
    dates = frames['AAA'].trade_date.dt.strftime('%Y-%m-%d').tolist()
    event = {**action(), 'record_date': dates[31], 'ex_date': dates[32], 'pay_date': dates[34]}
    frames['BBB']['cash_dividend_per_share'] = 0.
    frames['BBB'].loc[33, 'cash_dividend_per_share'] = .25
    with pytest.raises(ValueError, match='事件|公司行为'):
        run_portfolio_workspace(frames, recipe=recipe, spec=spec, strategy_key='trend',
            params={'fast_window': 5, 'slow_window': 30}, corporate_actions=[event])
    frames['BBB'].drop(columns=['cash_dividend_per_share'], inplace=True)
    frames['AAA'].attrs['corporate_actions'] = [{**event, 'cash_per_share': .7}]
    with pytest.raises(ValueError, match='冲突|不一致'):
        run_portfolio_workspace(frames, recipe=recipe, spec=spec, strategy_key='trend',
            params={'fast_window': 5, 'slow_window': 30}, corporate_actions=[event])
