import math

import pytest


def test_opening_deposit_withdrawal_are_capital_not_profit():
    from portfolio_app.portfolio_accounting import build_portfolio_accounting
    result=build_portfolio_accounting(dates=['2025-01-02','2025-01-03','2025-01-06'],
        prices={},fills=[],initial_cash=1000.,external_flows=[
            dict(flow_id='in',session='2025-01-03',amount=500.,timing='session_open'),
            dict(flow_id='out',session='2025-01-06',amount=-200.,timing='session_open')])
    ledger=result.ledger
    assert ledger.nav.tolist()==[1000.,1500.,1300.]
    assert ledger.daily_return.tolist()==[0.,0.,0.]
    assert ledger.external_flow.tolist()==[0.,500.,-200.]
    assert ledger.unit_nav.tolist()==[1.,1.,1.]
    assert ledger.daily_pnl.tolist()==[0.,0.,0.]


def test_time_and_money_weighted_return_conventions():
    from portfolio_app.cashflow_returns import account_returns
    # 10% earned before the second-session deposit, then no performance change.
    result=account_returns(dates=['2025-01-01','2026-01-01'],nav=[1100.,1600.],
        initial_cash=1000.,external_flows=[dict(flow_id='deposit',session='2026-01-01',
            amount=500.,timing='session_open')])
    assert result['time_weighted_return']==pytest.approx(.1)
    assert result['unit_nav']==pytest.approx([1.1,1.1])
    assert result['money_weighted_status']=='available'
    # First session opening initial cash, final-session opening deposit and close valuation.
    assert result['money_weighted_annual']==pytest.approx(.1,abs=1e-10)
    assert result['external_flow_total']==500.


def test_multiple_cashflow_sign_changes_have_no_unqualified_irr():
    from portfolio_app.cashflow_returns import account_returns
    result=account_returns(dates=['2025-01-01','2025-07-01','2025-12-01','2026-01-01'],nav=[1000.,100.,600.,600.],
        initial_cash=1000.,external_flows=[
            dict(flow_id='out',session='2025-07-01',amount=-900.,timing='session_open'),
            dict(flow_id='in',session='2025-12-01',amount=500.,timing='session_open')])
    assert result['time_weighted_return']==0.
    assert result['money_weighted_annual'] is None
    assert result['money_weighted_status']=='multiple_sign_changes'


@pytest.mark.parametrize('flow',[
    dict(flow_id='a',session='2025-01-02',amount=True,timing='session_open'),
    dict(flow_id='a',session='2025-01-02',amount=1.,timing='session_close'),
    dict(flow_id='a',session='2025-01-03',amount=1.,timing='session_open'),
    dict(flow_id='a',session='2025-01-02',amount=-1000.,timing='session_open'),
    dict(flow_id='a',session='2025-01-02',amount=float('inf'),timing='session_open')])
def test_invalid_capital_flows_rejected(flow):
    from portfolio_app.portfolio_accounting import build_portfolio_accounting
    with pytest.raises(ValueError):
        build_portfolio_accounting(dates=['2025-01-02'],prices={},fills=[],initial_cash=1000.,external_flows=[flow])


def test_deposit_funds_execution_without_becoming_pnl_or_attribution():
    from portfolio_app.portfolio_accounting import build_portfolio_accounting
    from portfolio_app.portfolio_contribution import contribution_period
    dates=['2025-01-02','2025-01-03']
    result=build_portfolio_accounting(dates=dates,prices={'AAA':dict(zip(dates,[10.,11.]))},
        fills=[dict(fill_id='buy',fill_date=dates[1],symbol='AAA',side='BUY',quantity=100,price=10.,fee=1.)],
        initial_cash=100.,external_flows=[dict(flow_id='in',session=dates[1],amount=1000.,timing='session_open')])
    assert result.ledger.nav.tolist()==[100.,1199.]
    assert result.ledger.daily_return.tolist()==pytest.approx([0.,99/1100])
    report=contribution_period(result.ledger,initial_cash=100.,start=dates[0],end=dates[1])
    assert report['total_return']==pytest.approx(99/1100)
    assert report['components'].contribution.sum()==pytest.approx(99/1100)
