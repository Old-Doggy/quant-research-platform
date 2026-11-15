import pandas as pd
import pytest

from portfolio_app.providers.tushare_financial import TushareFinancial
from portfolio_app.providers.base import ProviderError


def statement(value=100.,**changes):
    return dict(ts_code='600000.SH',ann_date='20250420',f_ann_date='20250421',end_date='20250331',
        report_type='1',comp_type='2',end_type='1',update_flag='0',total_revenue=value,revenue=value,
        n_income=10.,n_income_attr_p=8.,basic_eps=.1,**changes)


def test_period_shards_keep_original_and_revised_reports_and_missing_periods():
    calls=[]
    class Provider:
        def query(self,endpoint,params,fields):
            calls.append(params)
            if params['period']=='20250630':return pd.DataFrame()
            revised=statement(120.)
            revised.update(ann_date='20250520',f_ann_date='20250520',update_flag='1')
            return pd.DataFrame([statement(),revised])
    batch=TushareFinancial(Provider()).reports('income','600000.SH',periods=['2025-03-31','2025-06-30'],
        fetched_at='2026-11-15T20:00:00+08:00')
    assert len(calls)==2 and all('start_date' not in p for p in calls)
    assert batch.completeness=='partial'
    assert batch.frame.revenue.tolist()==[100.,120.]
    assert batch.frame.report_version.nunique()==2
    assert batch.raw.revenue.tolist()==[100.,120.]
    assert batch.metadata['pit_coverage']=='unverified'
    assert batch.metadata['missing_periods']==['2025-06-30']


def test_one_period_cap_is_rejected_instead_of_silently_truncated():
    class Provider:
        def query(self,*a,**kw):return pd.DataFrame([statement(),statement()])
    with pytest.raises(ProviderError,match='上限'):
        TushareFinancial(Provider(),row_limit=2).reports('income','600000.SH',periods=['2025-03-31'])


@pytest.mark.parametrize('changes',[dict(ts_code='000001.SZ'),dict(end_date='20241231'),dict(ann_date='20250101',f_ann_date='20250101'),
    dict(revenue=float('inf')),dict(report_type='99')])
def test_invalid_financial_response_is_not_registered(changes):
    class Provider:
        def query(self,*a,**kw):
            row=statement();row.update(changes)
            return pd.DataFrame([row])
    with pytest.raises(ProviderError):
        TushareFinancial(Provider()).reports('income','600000.SH',periods=['2025-03-31'])
