import pandas as pd
import pytest

from portfolio_app.financial_store import FinancialStore
from portfolio_app.financial_query import financial_asof
from portfolio_app.providers.tushare_financial import TushareFinancial
from portfolio_app.calendar_service import MarketCalendar
from test_tushare_financial import statement


def batch(row,fetched):
    class Provider:
        def query(self,*a,**kw):return pd.DataFrame([row])
    return TushareFinancial(Provider()).reports('income','600000.SH',periods=['2025-03-31'],fetched_at=fetched)


def calendar():
    return MarketCalendar('SSE','Asia/Shanghai','synthetic-test-calendar',1,
        tuple((d.strftime('%Y-%m-%d'),d.dayofweek<5) for d in pd.date_range('2025-04-01','2025-06-01')))


def test_reports_remain_immutable_and_revisions_only_appear_after_observation(tmp_path):
    store=FinancialStore(tmp_path)
    first=batch(statement(),'2025-04-21T23:00:00+08:00')
    artifact=store.ingest(first)
    assert store.ingest(first)==artifact
    options=dict(endpoint='income',symbol='600000.SH',calendar=calendar())
    assert financial_asof(store,as_of='2025-04-21',**options) is None
    assert financial_asof(store,as_of='2025-04-22',**options)['revenue']==100.
    revised=statement(120.);revised.update(ann_date='20250520',f_ann_date='20250520',update_flag='1')
    store.ingest(batch(revised,'2025-05-20T20:00:00+08:00'))
    assert financial_asof(store,as_of='2025-05-20',**options)['revenue']==100.
    assert financial_asof(store,as_of='2025-05-21',**options)['revenue']==120.
    assert len(store.observations(endpoint='income',symbol='600000.SH'))==2
    assert store.updates.read_artifact(artifact).raw.revenue.tolist()==[100.]


def test_late_historical_download_cannot_be_backdated_to_original_announcement(tmp_path):
    store=FinancialStore(tmp_path)
    store.ingest(batch(statement(),'2025-05-20T10:00:00+08:00'))
    options=dict(endpoint='income',symbol='600000.SH',calendar=calendar())
    assert financial_asof(store,as_of='2025-04-22',**options) is None
    assert financial_asof(store,as_of='2025-05-20',**options) is None
    assert financial_asof(store,as_of='2025-05-21',**options)['pit_coverage']=='forward_observation_only'


def test_ambiguous_versions_bad_batches_and_calendar_gaps_are_not_silenced(tmp_path):
    store=FinancialStore(tmp_path)
    artifact=store.ingest(batch(statement(),'2025-04-21T23:00:00+08:00'))
    store.ingest(batch(statement(110.),'2025-04-21T23:00:00+08:00'))
    options=dict(endpoint='income',symbol='600000.SH',calendar=calendar())
    with pytest.raises(ValueError,match='不同财务版本'):
        financial_asof(store,as_of='2025-04-22',**options)
    with pytest.raises(ValueError):
        financial_asof(store,as_of='2025-06-02',**options)
    (tmp_path/'batches'/artifact/'raw.parquet').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='校验'):
        store.observations(endpoint='income',symbol='600000.SH')


def test_missing_financial_value_remains_missing_without_becoming_zero(tmp_path):
    store=FinancialStore(tmp_path)
    row=statement();row['revenue']=None
    store.ingest(batch(row,'2025-04-21T23:00:00+08:00'))
    assert store.observations(endpoint='income',symbol='600000.SH')[0]['revenue'] is None
