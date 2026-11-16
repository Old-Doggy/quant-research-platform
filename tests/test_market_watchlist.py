import pandas as pd
import pytest

from test_market_overview import daily_frame, snapshot


def test_watchlist_trends_keep_gaps_and_anchor_only_at_first_known_close():
    from portfolio_app.market_watchlist import watchlist_trends
    frame = daily_frame(dict(symbol=['AAA','AAA','BBB'],
        trade_date=pd.to_datetime(['2025-01-02','2025-01-06','2025-01-06']),
        close=[10.,11.,20.],pre_close=[9.,10.,19.],amount=[100.,200.,300.],volume=[10,20,30]))
    rows = watchlist_trends(frame,manifest=snapshot(),session='2025-01-06',
        symbols=['AAA','BBB','CCC','OUTSIDE'])
    assert rows.symbol.tolist() == ['AAA','BBB','CCC','OUTSIDE']
    aaa,bbb,ccc,outside = [rows.iloc[i] for i in range(4)]
    assert aaa.trend == [0.,None,pytest.approx(.1)]
    assert aaa.observed_sessions == 2 and aaa.expected_sessions == 3
    assert aaa.price_change == pytest.approx(.1)
    assert bbb.trend == [None,None,0.]
    assert ccc.trend == [None,None,None] and pd.isna(ccc.close)
    assert outside.status == '不在此版本' and outside.trend == []


def test_watchlist_series_never_include_future_or_unlisted_observations():
    from portfolio_app.market_watchlist import watchlist_trends
    frame = daily_frame(dict(symbol=['AAA','AAA','NEW','NEW'],
        trade_date=pd.to_datetime(['2025-01-02','2025-01-06','2025-01-03','2025-01-06']),
        close=[10.,99.,9.,11.],pre_close=[9.,10.,8.,10.],amount=[1.,2.,3.,4.],volume=[1,2,3,4]))
    rows = watchlist_trends(frame,manifest=snapshot(),session='2025-01-03',symbols=['AAA','NEW'])
    assert rows.iloc[0].trend == [0.,None]
    assert pd.isna(rows.iloc[0].close)
    assert rows.iloc[1].status == '当日不在上市范围'
    assert rows.iloc[1].trend == [None,None]
    bad = frame.copy()
    bad.loc[0,'close'] = float('inf')
    with pytest.raises(ValueError):
        watchlist_trends(bad,manifest=snapshot(),session='2025-01-03',symbols=['AAA'])
