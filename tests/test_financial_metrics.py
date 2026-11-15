import pandas as pd
import pytest

from portfolio_app.financial_metrics import cumulative_flow_metric
from portfolio_app.financial_store import FinancialStore
from portfolio_app.providers.tushare_financial import TushareFinancial
from portfolio_app.calendar_service import MarketCalendar
from test_tushare_financial import statement


def add(store,period,value,observed):
    row=statement(value)
    row.update(end_date=period.replace('-',''),ann_date=observed[:10].replace('-',''),f_ann_date=observed[:10].replace('-',''))
    class Provider:
        def query(self,*a,**kw):return pd.DataFrame([row])
    store.ingest(TushareFinancial(Provider()).reports('income','600000.SH',periods=[period],fetched_at=observed))


def options(store):
    calendar=MarketCalendar('SSE','Asia/Shanghai','synthetic-test-calendar',1,
        tuple((d.strftime('%Y-%m-%d'),d.dayofweek<5) for d in pd.date_range('2024-01-01','2025-12-31')))
    return dict(store=store,endpoint='income',symbol='600000.SH',field='revenue',as_of='2025-08-21',calendar=calendar,unit='CNY')


def test_ttm_and_quarter_match_independent_arithmetic_and_revision_cutoff(tmp_path):
    store=FinancialStore(tmp_path)
    add(store,'2024-06-30',40.,'2024-08-20T21:00:00+08:00')
    add(store,'2024-12-31',100.,'2025-03-20T21:00:00+08:00')
    add(store,'2025-03-31',25.,'2025-04-20T21:00:00+08:00')
    add(store,'2025-06-30',60.,'2025-08-20T21:00:00+08:00')
    opts=options(store)
    ttm=cumulative_flow_metric(**opts)
    assert ttm['value']==60+100-40
    assert len(ttm['inputs'])==3
    assert cumulative_flow_metric(**opts,mode='single_quarter')['value']==60-25
    # A later correction to the prior year must not enter the previous as-of.
    add(store,'2024-12-31',110.,'2025-09-20T21:00:00+08:00')
    assert cumulative_flow_metric(**opts)['value']==120.
    assert cumulative_flow_metric(**{**opts,'as_of':'2025-09-22'})['value']==130.


def test_missing_annual_or_value_cannot_be_zero_filled(tmp_path):
    store=FinancialStore(tmp_path)
    add(store,'2025-06-30',60.,'2025-08-20T21:00:00+08:00')
    result=cumulative_flow_metric(**options(store))
    assert result['status']=='unavailable' and result['value'] is None
    assert result['missing_period']=='2024-12-31'
    add(store,'2024-12-31',100.,'2025-03-20T21:00:00+08:00')
    add(store,'2024-06-30',None,'2024-08-20T21:00:00+08:00')
    assert cumulative_flow_metric(**options(store))['reason']=='missing_required_value'


def test_annual_ttm_is_annual_total_and_eps_or_unknown_units_are_rejected(tmp_path):
    store=FinancialStore(tmp_path)
    add(store,'2024-12-31',100.,'2025-03-20T21:00:00+08:00')
    opts=options(store)
    assert cumulative_flow_metric(**opts)['value']==100.
    for changes in [dict(field='basic_eps'),dict(endpoint='balancesheet'),dict(unit='unknown')]:
        with pytest.raises(ValueError):cumulative_flow_metric(**{**opts,**changes})
