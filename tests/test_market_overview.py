import pandas as pd
import pytest

from portfolio_app.market_overview import market_overview


def snapshot():
    from test_data_update_flow import inputs
    _, calendar = inputs()
    return dict(snapshot_id='fixture-version', dataset_id='fixture', generation=2,
        calendars={'SSE': calendar.to_dict()},
        range=dict(start='2025-01-02', end='2025-01-06', symbols=['AAA', 'BBB', 'CCC', 'NEW']),
        instrument_master=dict(records=[dict(symbol=s, name=s, market='SSE', listed_on='2020-01-01',
            delisted_on=None) for s in ('AAA', 'BBB', 'CCC')]
            + [dict(symbol='NEW', name='new', market='SSE', listed_on='2025-01-06', delisted_on=None)]))


def daily_frame(*args, **kwargs):
    frame = pd.DataFrame(*args, **kwargs)
    frame.attrs.update(field_units=dict(price='CNY_per_share', volume='shares', amount='CNY'),
        research_dataset=dict(price_basis='raw'))
    return frame


def test_breadth_denominators_keep_missing_bases_and_pool_gaps_explicit():
    frame = daily_frame({'symbol': ['AAA', 'BBB', 'CCC', 'NEW'],
        'trade_date': pd.to_datetime(['2025-01-03'] * 4),
        'close': [11., 9., 10., 12.], 'pre_close': [10., 10., None, 10.],
        'amount': [100., 200., None, 50.], 'volume': [10, 20, 0, 5]})
    report = market_overview(frame, manifest=snapshot(), session='2025-01-03')
    assert report['scope'] == 'snapshot_universe'
    assert report['expected'] == 3 and report['observed'] == 3
    assert report['valid_return'] == 2 and report['missing_base'] == ['CCC']
    assert report['breadth'] == {'上涨': 1, '平盘': 0, '下跌': 1, '涨跌未知': 1, '行情缺失': 0}
    assert report['amount_cny'] == 300. and report['amount_coverage'] == pytest.approx(2/3)
    assert report['equal_weight_price_change'] == pytest.approx(0.)
    assert report['details'].symbol.tolist() == ['AAA', 'BBB', 'CCC']
    assert pd.isna(report['details'].loc[2, 'price_change'])
    assert report['industry'] is None
    assert report['snapshot_id'] == 'fixture-version'


def test_only_selected_session_and_universe_can_enter_aggregates():
    frame = daily_frame({'symbol': ['AAA', 'AAA', 'BBB'],
        'trade_date': pd.to_datetime(['2025-01-02', '2025-01-03', '2025-01-03']),
        'close': [99., 10., 9.], 'pre_close': [1., 10., 10.],
        'volume': [100, 10, 20], 'amount': [1000., 100., 200.]})
    report = market_overview(frame, manifest=snapshot(), session='2025-01-03')
    assert report['breadth'] == {'上涨': 0, '平盘': 1, '下跌': 1, '涨跌未知': 0, '行情缺失': 1}
    assert report['missing_symbols'] == ['CCC']
    assert report['return_coverage'] == pytest.approx(2/3)
    assert len(report['details']) == 3
    frame.loc[2, 'symbol'] = 'OUTSIDE'
    with pytest.raises(ValueError): market_overview(frame, manifest=snapshot(), session='2025-01-03')


def test_duplicate_invalid_numeric_and_uncovered_dates_are_rejected():
    frame = daily_frame(dict(symbol=['AAA'], trade_date=pd.to_datetime(['2025-01-03']),
        close=[10.], pre_close=[10.], volume=[10], amount=[100.]))
    with pytest.raises(ValueError):
        market_overview(pd.concat([frame, frame]), manifest=snapshot(), session='2025-01-03')
    for field, value in [('close', 0), ('pre_close', -1), ('amount', -1), ('volume', -1)]:
        bad = frame.copy()
        bad[field] = value
        with pytest.raises(ValueError): market_overview(bad, manifest=snapshot(), session='2025-01-03')
    with pytest.raises(ValueError): market_overview(frame, manifest=snapshot(), session='2024-12-31')


def test_industry_aggregation_uses_explicit_same_day_memberships_and_coverage():
    frame = daily_frame(dict(symbol=['AAA', 'BBB', 'CCC'], trade_date=pd.to_datetime(['2025-01-03']*3),
        close=[11., 9., 12.], pre_close=[10., 10., 10.], amount=[100., 200., 300.], volume=[10, 20, 30]))
    membership = dict(session='2025-01-03', assignments={'AAA': 'bank', 'BBB': 'bank'},
        missing_symbols=['CCC'], status='partial', classification_version='fixture-industry', membership_id='fixture-membership')
    report = market_overview(frame, manifest=snapshot(), session='2025-01-03', industry=membership)
    group = report['industry']['rows'].iloc[0]
    assert group['group'] == 'bank' and group['members'] == 2
    assert group['equal_weight_price_change'] == pytest.approx(0.)
    assert report['industry']['missing_symbols'] == ['CCC']
    assert report['industry']['classification_version'] == 'fixture-industry'
    membership['session'] = '2025-01-06'
    with pytest.raises(ValueError): market_overview(frame, manifest=snapshot(), session='2025-01-03', industry=membership)


def test_closed_day_units_unknown_calendar_and_non_daily_data_are_rejected():
    frame = daily_frame(dict(symbol=['AAA'], trade_date=pd.to_datetime(['2025-01-03']),
        close=[10.], pre_close=[10.], volume=[10], amount=[100.]))
    with pytest.raises(ValueError, match='交易日'):
        market_overview(frame, manifest=snapshot(), session='2025-01-04')
    manifest = snapshot()
    manifest['calendars'] = {}
    with pytest.raises(ValueError, match='日历'):
        market_overview(frame, manifest=manifest, session='2025-01-03')
    for attrs in ({}, dict(field_units=dict(price='CNY_per_share',volume='lots',amount='CNY'),
                          research_dataset=dict(price_basis='raw'))):
        bad = frame.copy()
        bad.attrs = attrs
        with pytest.raises(ValueError, match='单位'):
            market_overview(bad, manifest=snapshot(), session='2025-01-03')
    bad = frame.copy()
    bad.attrs['research_dataset'] = dict(price_basis='qfq')
    with pytest.raises(ValueError, match='原始'):
        market_overview(bad, manifest=snapshot(), session='2025-01-03')
    for day in ['2025-01-03 10:00:00', '2025-01-03T00:00:00+08:00', None]:
        bad = frame.copy()
        bad['trade_date'] = pd.to_datetime([day])
        with pytest.raises(ValueError, match='日期'):
            market_overview(bad, manifest=snapshot(), session='2025-01-03')
    bad = frame.copy()
    bad['amount'] = True
    with pytest.raises(ValueError): market_overview(bad, manifest=snapshot(), session='2025-01-03')


def test_empty_day_and_delisted_members_keep_explicit_denominators():
    frame = daily_frame(columns=['symbol','trade_date','close','pre_close','volume','amount'])
    report = market_overview(frame, manifest=snapshot(), session='2025-01-03')
    assert report['observed'] == 0 and report['breadth']['行情缺失'] == 3
    assert report['amount_cny'] is None and report['equal_weight_price_change'] is None
    manifest = snapshot()
    for row in manifest['instrument_master']['records']:
        row['delisted_on'] = '2025-01-03'
    report = market_overview(frame, manifest=manifest, session='2025-01-03')
    assert report['expected'] == 0 and report['return_coverage'] is None
    assert report['details'].empty
