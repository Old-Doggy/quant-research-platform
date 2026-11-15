import pandas as pd
import pytest


def frame(*, symbol='600000.SH', close=10., volume=10000., amount=100000., provider='sina'):
    result=pd.DataFrame(dict(ts_code=[symbol],trade_date=pd.to_datetime(['2025-01-02']),
        open=[10.],high=[11.],low=[9.],close=[close],volume=[volume],amount=[amount]))
    result.attrs['field_units']=dict(price='CNY_per_share',volume='shares',amount='CNY')
    result.attrs['research_dataset']=dict(price_basis='raw')
    result.attrs['normalization']=dict(profile=provider+'.sdk.raw',version='1.0')
    return result


def test_observed_precision_difference_is_not_automatically_assumed_safe():
    from portfolio_app.data_reconcile import compare_daily_sources
    first=frame(volume=78907100,amount=803904000,provider='tencent')
    first.attrs['normalization']['profile']='tencent.raw.lots'
    other=frame(volume=78907129,amount=803904040)
    report=compare_daily_sources(first,other,primary_provider='tencent',secondary_provider='sina')
    assert report['status']=='conflict'
    assert report['counts']['within_source_precision']==1
    assert report['counts']['conflict']==1
    assert report['max_price_difference']==0
    assert first.volume.iloc[0]==78907100
    assert other.volume.iloc[0]==78907129


def test_wrong_units_adjusted_prices_unknown_precision_and_same_upstream_cannot_pass():
    from portfolio_app.data_reconcile import compare_daily_sources
    for key,value in [('field_units',dict(price='CNY_per_share',volume='lots',amount='CNY')),
                      ('research_dataset',dict(price_basis='qfq')),
                      ('normalization',dict(profile='unknown',version='1.0'))]:
        altered=frame()
        altered.attrs[key]=value
        with pytest.raises(ValueError):
            compare_daily_sources(frame(),altered,primary_provider='sina',secondary_provider='baostock')
    with pytest.raises(ValueError):
        compare_daily_sources(frame(),frame(),primary_provider='sina',secondary_provider='sina')


def test_one_tick_difference_and_hundredfold_volume_are_quarantined():
    from portfolio_app.data_reconcile import compare_daily_sources
    first=frame(provider='baostock')
    second=frame(close=10.01,volume=1000000.)
    report=compare_daily_sources(first,second,primary_provider='baostock',secondary_provider='sina')
    assert report['status']=='conflict'
    assert {r['field'] for r in report['differences'] if r['status']=='conflict'}=={'close','volume'}


def test_missing_rows_and_values_are_not_treated_as_equal_zero():
    from portfolio_app.data_reconcile import compare_daily_sources
    a=frame(provider='baostock')
    b=frame()
    b['volume']=float('nan')
    result=compare_daily_sources(a,b,primary_provider='baostock',secondary_provider='sina')
    assert result['status']=='incomplete'
    assert any(r['status']=='missing_value' for r in result['differences'])
    result=compare_daily_sources(a,b.iloc[:0],primary_provider='baostock',secondary_provider='sina')
    assert result['status']=='incomplete' and result['counts']['missing_row']==1


def test_coverage_classifies_only_verified_suspensions_and_unlisted_days():
    from portfolio_app.data_reconcile import check_daily_coverage
    from test_data_update_flow import inputs
    master,calendar=inputs()
    observed=frame()
    result=check_daily_coverage(observed,master=master,calendars={'SSE':calendar},
        start='2025-01-02',end='2025-01-03',symbols=['600000.SH','600001.SH'],
        verified_suspensions={('600000.SH','2025-01-03'):'verified-batch'})
    assert result['counts']==dict(observed=1,not_listed=1,suspended=1,unknown_gap=1)
    assert result['status']=='incomplete'
    assert result['unknown_gaps']==[dict(symbol='600001.SH',session='2025-01-03')]


def test_suspension_with_observed_bar_and_outside_calendar_are_conflicts():
    from portfolio_app.data_reconcile import check_daily_coverage
    from test_data_update_flow import inputs
    master,calendar=inputs()
    result=check_daily_coverage(frame(),master=master,calendars={'SSE':calendar},
        start='2025-01-02',end='2025-01-02',symbols=['600000.SH'],
        verified_suspensions={('600000.SH','2025-01-02'):'batch'})
    assert result['status']=='conflict'


def test_malformed_numeric_data_is_conflict_not_missing_and_cannot_pass_below_tick():
    from portfolio_app.data_reconcile import compare_daily_sources
    primary=frame(provider='baostock')
    for bad in [float('inf'),-1.]:
        other=frame(volume=bad)
        assert compare_daily_sources(primary,other,primary_provider='baostock',secondary_provider='sina')['status']=='conflict'


def test_extra_suspension_evidence_outside_checked_universe_is_rejected():
    from portfolio_app.data_reconcile import check_daily_coverage
    from test_data_update_flow import inputs
    master,calendar=inputs()
    with pytest.raises(ValueError):
        check_daily_coverage(frame(),master=master,calendars={'SSE':calendar},start='2025-01-02',
            end='2025-01-02',symbols=['600000.SH'],verified_suspensions={('000001.SZ','2025-01-02'):'batch'})
