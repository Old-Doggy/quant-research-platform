import pytest


def bonus(**changes):
    return {**dict(action_id='bonus-1', action_type='bonus_share', symbol='AAA',
        record_date='2025-01-02', ex_date='2025-01-03', listing_date='2025-01-07',
        share_multiplier=1.2, source='synthetic_truth'), **changes}


def test_bonus_preserves_total_basis_and_locks_only_new_shares():
    from portfolio_app.entitlement_ledger import EntitlementBook
    book = EntitlementBook([bonus()])
    held = {'AAA': 100}
    lots = {'leg': [dict(symbol='AAA', quantity=100, price=12.)]}
    book.record_close('2025-01-02', held, lots)
    book.open_session('2025-01-03', held, lots)
    assert held == {'AAA': 120}
    assert sum(lot['quantity'] * lot['price'] for lot in lots['leg']) == pytest.approx(1200.)
    assert all(lot['price'] == pytest.approx(10.) for lot in lots['leg'])
    assert book.locked_quantities('2025-01-03') == {'AAA': 20}
    assert book.locked_quantities('2025-01-07') == {}
    book.open_session('2025-01-03', held, lots)
    assert held == {'AAA': 120}


def test_shared_ledger_bonus_reconciles_and_cannot_be_sold_before_listing():
    from portfolio_app.portfolio_accounting import build_portfolio_accounting
    dates = ['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
    kwargs = dict(dates=dates, prices={'AAA': dict(zip(dates, [12., 10., 10., 10.]))},
        initial_cash=1200., corporate_actions=[bonus()])
    buy = dict(fill_id='buy', fill_date=dates[0], symbol='AAA', side='BUY', quantity=100, price=12.)
    sell = dict(fill_id='sell', fill_date=dates[1], symbol='AAA', side='SELL', quantity=120, price=10.)
    with pytest.raises(ValueError, match='可卖|上市'):
        build_portfolio_accounting(**kwargs, fills=[buy, sell])
    result = build_portfolio_accounting(**kwargs, fills=[buy, {**sell, 'fill_date': dates[-1]}])
    assert result.ledger.nav.tolist() == pytest.approx([1200.] * 4)
    assert result.diagnostics['contribution_status'] == 'reconciled'
    assert result.diagnostics['corporate_action_events'][0]['kind'] == 'share_adjustment'
    # The original 100 shares remain sellable; their new cost is 10 each.
    sold_original = build_portfolio_accounting(**kwargs, fills=[buy, {**sell, 'quantity': 100}])
    assert sold_original.ledger.nav.tolist() == pytest.approx([1200.] * 4)


@pytest.mark.parametrize('multiplier,quantity,expected', [(2., 100, 200), (.5, 100, 50)])
def test_split_and_consolidation_keep_cost_without_rounding(multiplier, quantity, expected):
    from portfolio_app.entitlement_ledger import EntitlementBook
    book = EntitlementBook([bonus(action_type='split', share_multiplier=multiplier, listing_date='2025-01-03')])
    held = {'AAA': quantity}
    lots = {'leg': [dict(symbol='AAA', quantity=quantity, price=12.)]}
    book.record_close('2025-01-02', held, lots)
    book.open_session('2025-01-03', held, lots)
    assert held['AAA'] == expected
    assert sum(lot['quantity'] * lot['price'] for lot in lots['leg']) == pytest.approx(quantity * 12.)
    assert book.locked_quantities('2025-01-03') == {}


def test_fractional_entitlements_are_rejected_without_partially_mutating_holdings():
    from portfolio_app.entitlement_ledger import EntitlementBook
    book = EntitlementBook([bonus(share_multiplier=1.1)])
    held = {'AAA': 11}
    lots = {'leg': [dict(symbol='AAA', quantity=11, price=12.)]}
    book.record_close('2025-01-02', held, lots)
    with pytest.raises(ValueError, match='零碎股'):
        book.open_session('2025-01-03', held, lots)
    assert held['AAA'] == 11
    assert lots['leg'][0]['price'] == 12.


def test_bonus_corrections_record_lineage_and_reject_mixing_old_and_new():
    from portfolio_app.corporate_actions import normalize_actions
    revised = bonus(action_id='bonus-2', supersedes='bonus-1', share_multiplier=1.3)
    assert normalize_actions([revised])[0].supersedes == 'bonus-1'
    with pytest.raises(ValueError, match='更正'):
        normalize_actions([bonus(), revised])


def test_share_ledger_and_workspace_use_same_holdings_and_locked_orders():
    import pandas as pd
    from portfolio_app.portfolio_workspace import run_portfolio_workspace
    from portfolio_app.portfolio_recipe import PortfolioRecipe
    from portfolio_app.offline_execution import ExecutionSpec
    dates = ['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
    prices = [12., 12., 10., 10., 10.]
    frame = pd.DataFrame(dict(trade_date=pd.to_datetime(dates), symbol='AAA',
        open=prices, high=prices, low=prices, close=prices))
    schedule = {day: {'AAA': 1. if i < 2 else 0.} for i, day in enumerate(dates)}
    result = run_portfolio_workspace({'AAA': frame}, strategy_key='trend', initial_cash=1200.,
        recipe=PortfolioRecipe.from_dict(dict(recipe_id='test', target_weights={'AAA': 1.}, cash_weight=0., lot_size=1)),
        spec=ExecutionSpec('close', 'close', 'next_close', 0, 0, 'us_stock'),
        target_schedule=schedule, corporate_actions=[bonus()])
    assert result.accounting.ledger.nav.tolist() == pytest.approx([1200.] * 5)
    assert result.positions.loc[result.positions.trade_date.eq(dates[2]), 'quantity'].tolist() == [120]
    assert result.positions.loc[result.positions.trade_date.eq(dates[2]), 'sellable_quantity'].tolist() == [100]
    assert any(o['reason_code'] == 'corporate_action_locked' for o in result.orders)
    assert result.fills[-1]['fill_date'] == dates[-1]
    assert result.fills[-1]['quantity'] == 120


def test_overlapping_unlisted_share_reorganizations_are_not_silently_combined():
    from portfolio_app.entitlement_ledger import EntitlementBook
    events = [bonus(), bonus(action_id='split-2', action_type='split', record_date='2025-01-03',
        ex_date='2025-01-06', listing_date='2025-01-07', share_multiplier=.5)]
    held = {'AAA': 100}
    lots = {'leg': [dict(symbol='AAA', quantity=100, price=12.)]}
    book = EntitlementBook(events)
    book.record_close('2025-01-02', held, lots)
    book.open_session('2025-01-03', held, lots)
    book.record_close('2025-01-03', held, lots)
    with pytest.raises(ValueError, match='重叠|未上市'):
        book.open_session('2025-01-06', held, lots)
    assert held['AAA'] == 120


def test_registration_requires_leg_and_position_quantities_to_reconcile():
    from portfolio_app.entitlement_ledger import EntitlementBook
    book = EntitlementBook([bonus()])
    with pytest.raises(ValueError, match='持仓|数量'):
        book.record_close('2025-01-02', {'AAA': 100}, {})


def test_dividend_tax_basis_cannot_be_assumed_when_omitted():
    from portfolio_app.corporate_actions import normalize_actions
    from test_entitlement_ledger import action
    missing = action()
    missing.pop('tax_basis')
    with pytest.raises(ValueError, match='tax_basis'):
        normalize_actions([missing])
