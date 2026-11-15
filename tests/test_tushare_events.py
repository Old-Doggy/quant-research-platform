import pytest

from portfolio_app.providers.base import ProviderError
from portfolio_app.providers.tushare import TushareProvider


def dividend_row(**changes):
    return dict(ts_code='600000.SH', end_date='20241231', ann_date='20250401', div_proc='实施',
        stk_div=.2, stk_bo_rate=.1, stk_co_rate=.1, cash_div=.4, cash_div_tax=.5,
        record_date='20250603', ex_date='20250604', pay_date='20250606', div_listdate='20250605',
        imp_ann_date='20250530', **changes)


def events(rows, *, limit=6000):
    from portfolio_app.providers.tushare_events import TushareEvents
    calls = []
    def transport(endpoint, params, *, fields):
        calls.append((endpoint, params))
        names = fields.split(',')
        return dict(code=0, data=dict(fields=names, items=[[r.get(f) for f in names] for r in rows]))
    return TushareEvents(TushareProvider(token='test', transport=transport, min_interval=0, row_limit=limit)), calls


def test_gross_dividend_and_bonus_actions_feed_existing_entitlement_book():
    from portfolio_app.entitlement_ledger import EntitlementBook
    ref, calls = events([dividend_row()])
    batch = ref.dividends('600000.SH')
    actions = batch.metadata['corporate_actions']
    assert len(actions) == 2
    cash = next(a for a in actions if a['action_type'] == 'cash_dividend')
    assert cash['cash_per_share'] == .5 and cash['tax_basis'] == 'gross'
    book = EntitlementBook(actions)
    held = {'600000.SH': 100}
    lots = {'600000.SH': [dict(symbol='600000.SH', quantity=100, price=10.)]}
    book.record_close('2025-06-03', held, lots)
    assert book.open_session('2025-06-04', held, lots) == 0
    assert book.receivable == 50 and held['600000.SH'] == 120
    assert book.open_session('2025-06-06', held, lots) == 50
    assert batch.raw.cash_div.iloc[0] == .4
    assert batch.metadata['event_coverage'] == 'unverified'
    assert calls[0][1] == dict(ts_code='600000.SH')


def test_planned_dividend_is_preserved_but_does_not_enter_ledger():
    row = {**dividend_row(), 'div_proc': '预案', 'record_date': None, 'ex_date': None}
    ref, _ = events([row])
    batch = ref.dividends('600000.SH')
    assert len(batch.raw) == 1 and batch.frame.empty
    assert batch.metadata['corporate_actions'] == []


@pytest.mark.parametrize('changes', [dict(cash_div_tax=None), dict(pay_date=None), dict(div_listdate=None),
    dict(stk_div=-.1), dict(stk_co_rate=.2), dict(imp_ann_date='20250605')])
def test_incomplete_or_conflicting_dividend_does_not_silently_become_no_event(changes):
    ref, _ = events([{**dividend_row(), **changes}])
    with pytest.raises(ProviderError):
        ref.dividends('600000.SH')


def test_dividend_cap_and_duplicate_implemented_event_block():
    for rows, limit in [([dividend_row()], 1), ([dividend_row()] * 2, 6000)]:
        ref, _ = events(rows, limit=limit)
        with pytest.raises(ProviderError):
            ref.dividends('600000.SH')


def test_two_cash_revisions_on_same_ex_date_are_not_both_paid():
    first = {**dividend_row(), 'stk_div': 0., 'stk_bo_rate': 0., 'stk_co_rate': 0.}
    second = {**first, 'cash_div_tax': .6}
    ref, _ = events([first, second])
    with pytest.raises(ProviderError) as failure:
        ref.dividends('600000.SH')
    assert failure.value.code == 'conflicting_events'


def test_full_day_suspension_conflicts_with_resumption_and_capped_shards_fail():
    first = dict(ts_code='600000.SH', trade_date='20250102', suspend_type='S', suspend_timing=None)
    for rows, limit in [([first, {**first, 'suspend_type': 'R'}], 6000), ([first], 1)]:
        ref, _ = events(rows, limit=limit)
        with pytest.raises(ProviderError):
            ref.suspensions('2025-01-02', expected_symbols=['600000.SH'])


def test_intraday_suspension_and_resumption_are_not_full_day_suspension():
    rows = [dict(ts_code='600000.SH', trade_date='20250102', suspend_type='S', suspend_timing=None),
            dict(ts_code='000001.SZ', trade_date='20250102', suspend_type='S', suspend_timing='09:30-10:00'),
            dict(ts_code='300001.SZ', trade_date='20250102', suspend_type='R', suspend_timing=None)]
    ref, _ = events(rows)
    batch = ref.suspensions('2025-01-02', expected_symbols=['600000.SH','000001.SZ','300001.SZ'])
    assert batch.metadata['suspended_symbols'] == ['600000.SH']
    assert batch.metadata['intraday_symbols'] == ['000001.SZ']
    assert batch.metadata['resumed_symbols'] == ['300001.SZ']
    assert batch.metadata['status_coverage'] == 'unverified'
    assert batch.completeness == 'unverified'


def test_wrong_date_and_unknown_suspension_state_fail():
    for changes in [dict(trade_date='20250103'), dict(suspend_type='X')]:
        row = dict(ts_code='600000.SH', trade_date='20250102', suspend_type='S', suspend_timing=None)
        ref, _ = events([{**row, **changes}])
        with pytest.raises(ProviderError):
            ref.suspensions('2025-01-02', expected_symbols=['600000.SH'])
