import pandas as pd
import pytest


def account():
    from portfolio_app.portfolio_accounting import build_portfolio_accounting
    from test_entitlement_ledger import action
    dates=['2025-01-02','2025-01-03','2025-01-06']
    return build_portfolio_accounting(dates=dates,prices={'AAA':dict(zip(dates,[10.,9.5,10.]))},
        fills=[dict(fill_id='buy',fill_date=dates[0],symbol='AAA',side='BUY',quantity=100,price=10.,fee=1.)],
        initial_cash=1100.,corporate_actions=[action()])


def test_price_dividend_fees_cash_and_residual_reconcile_ex_date_and_payment():
    result=account()
    ledger=result.ledger
    assert ledger.price_pnl.tolist()==pytest.approx([0.,-50.,50.])
    assert ledger.dividend_pnl.tolist()==pytest.approx([0.,50.,0.])
    assert ledger.contribution_residual_pnl.tolist()==pytest.approx([0.,0.,0.],abs=1e-10)
    columns=['price_contribution','dividend_contribution','cash_contribution','cost_contribution','contribution_residual']
    assert ledger[columns].sum(axis=1).tolist()==pytest.approx(ledger.daily_return)
    assert result.symbol_contribution.price_pnl.tolist()==pytest.approx([-50.,50.])


def test_linked_period_includes_day_one_fee_and_uses_previous_equity():
    from portfolio_app.portfolio_contribution import contribution_period
    ledger=account().ledger
    report=contribution_period(ledger,initial_cash=1100.,start='2025-01-02',end='2025-01-06')
    assert report['total_return']==pytest.approx(49/1100)
    assert report['components'].contribution.sum()==pytest.approx(49/1100)
    values=report['components'].set_index('kind')
    assert values.loc['dividend','contribution']==pytest.approx(50/1100)
    assert values.loc['fees','contribution']==pytest.approx(-1/1100)
    subset=contribution_period(ledger,initial_cash=1100.,start='2025-01-03',end='2025-01-03')
    assert subset['base_equity']==1099.
    assert subset['components'].set_index('kind').loc['price','contribution']==pytest.approx(-50/1099)
    assert subset['total_return']==0.


def test_inconsistent_ledger_is_not_declared_reconciled():
    from portfolio_app.portfolio_contribution import contribution_period
    ledger=account().ledger.copy()
    ledger.loc[1,'price_pnl']=20.
    with pytest.raises(ValueError):
        contribution_period(ledger,initial_cash=1100.,start='2025-01-02',end='2025-01-06')
