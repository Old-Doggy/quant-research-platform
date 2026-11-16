import copy

import pandas as pd
import pytest


def payload():
    return {'result': {'data': {'report_count': 1,
        'report_date': [dict(date_value='20250331')],
        'report_list': {'20250331': dict(rType='合并期末',rCurrency='CNY',data_source='定期报告',
            is_audit='未审计',publish_date='20250421',update_time=1745211600,
            data=[dict(item_field='BIZINCO',item_title='营业收入',item_value='1000000'),
                dict(item_field='NETPROFIT',item_title='净利润',item_value='100000'),
                dict(item_field='NETPARECOMPPROF',item_title='归属于母公司的净利润',item_value='90000'),
                dict(item_field='BASICEPS',item_title='基本每股收益',item_value=None)])}}}}


def batch(data=None):
    from portfolio_app.providers.sina_financial import SinaFinancial
    return SinaFinancial(transport=lambda **kw:copy.deepcopy(payload() if data is None else data)).reports(
        'income','600000.SH',periods=['2025-03-31'],fetched_at='2025-04-21T23:00:00+08:00')


def test_sina_statement_preserves_missing_raw_and_explicit_source_identity():
    result=batch()
    assert result.completeness=='complete'
    row=result.frame.iloc[0]
    assert row.revenue==1000000 and row.n_income_attr_p==90000
    assert pd.isna(row.basic_eps)
    assert row.ann_date=='2025-04-21' and row.report_type=='1'
    assert result.metadata['provider']=='sina'
    assert result.metadata['pit_coverage']=='forward_observation_only'
    assert result.metadata['field_units']['revenue']=='CNY'
    assert '1000000' in result.raw.iloc[0].payload_json


def test_industrial_and_bank_field_aliases_are_explicit_and_conflicts_rejected():
    data=payload(); items=data['result']['data']['report_list']['20250331']['data']
    items[2]['item_field']='PARENETP'
    assert batch(data).frame.iloc[0].n_income_attr_p==90000.
    items.append(dict(item_field='NETPARECOMPPROF',item_title='归母净利润',item_value='80000'))
    with pytest.raises(ValueError,match='冲突'): batch(data)


@pytest.mark.parametrize('change', ['duplicate_field','foreign_currency','unknown_type','future_announcement','overflow','nonfinite'])
def test_unknown_or_conflicting_statement_contract_is_rejected(change):
    data=payload(); row=data['result']['data']['report_list']['20250331']
    if change=='duplicate_field': row['data'].append(copy.deepcopy(row['data'][0]))
    elif change=='foreign_currency': row['rCurrency']='HKD'
    elif change=='unknown_type': row['rType']='母公司期末'
    elif change=='future_announcement': row['publish_date']='20260421'
    elif change=='overflow': data['result']['data']['report_count']=1000
    elif change=='nonfinite': row['data'][0]['item_value']='inf'
    with pytest.raises(ValueError): batch(data)


def test_free_and_paid_observations_never_mix_and_revisions_stay_forward_only(tmp_path):
    from portfolio_app.financial_store import FinancialStore
    from portfolio_app.financial_query import financial_asof
    from test_financial_store import calendar,batch as paid_batch
    from test_tushare_financial import statement
    store=FinancialStore(tmp_path)
    artifact=store.ingest(batch())
    store.ingest(paid_batch(statement(200.),'2025-04-21T23:00:00+08:00'))
    options=dict(endpoint='income',symbol='600000.SH',calendar=calendar(),provider='sina')
    assert financial_asof(store,as_of='2025-04-21',**options) is None
    assert financial_asof(store,as_of='2025-04-22',**options)['revenue']==1000000
    assert store.observations(endpoint='income',symbol='600000.SH')[0]['revenue']==200.
    assert store.updates.read_artifact(artifact).raw.iloc[0].payload_json
    changed=payload(); changed['result']['data']['report_list']['20250331']['data'][0]['item_value']='1200000'
    store.ingest(__import__('portfolio_app.providers.sina_financial',fromlist=['SinaFinancial']).SinaFinancial(
        transport=lambda **kw:changed).reports('income','600000.SH',periods=['2025-03-31'],
        fetched_at='2025-05-20T20:00:00+08:00'))
    # Same source announcement, conflicting values: no invented revision order.
    with pytest.raises(ValueError,match='不同财务版本'):
        financial_asof(store,as_of='2025-05-21',**options)


def test_saved_observations_page_uses_same_values_for_chart_table_and_download(tmp_path,monkeypatch):
    from portfolio_app.financial_store import FinancialStore
    from portfolio_app.financial_view import observed_statements
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    store=FinancialStore(tmp_path/'financial_service')
    store.ingest(batch())
    table=observed_statements(store,symbol='600000.SH',provider='sina')
    assert table.loc[table.field.eq('revenue'),'value'].iloc[0]==1000000.
    app=AppTest.from_string('from portfolio_app.financial_view import render_financial_data\nrender_financial_data()').run()
    assert not app.exception and app.get('plotly_chart')
    app.segmented_control(key='financial_display').set_value('表格').run()
    assert not app.exception
    shown=app.dataframe[0].value
    assert shown.loc[shown.field.eq('revenue'),'金额（元）'].iloc[0]==1000000.
    app.segmented_control(key='financial_report_range').set_value('仅年报').run()
    assert not app.exception and app.dataframe[0].value.empty


def test_observed_report_conversions_need_exact_periods_and_do_not_difference_assets():
    from portfolio_app.financial_view import statement_basis
    rows=[dict(period=period,field='revenue',value=value,endpoint='income',label='收入',
        ann_date='2026-04-01',fetched_at='2026-11-16T00:00:00+08:00',artifact_id=period,report_version=period)
        for period,value in [('2024-06-30',40.),('2024-12-31',100.),('2025-03-31',25.),('2025-06-30',60.)]]
    rows.append({**rows[-1],'field':'total_assets','value':1000.,'endpoint':'balancesheet'})
    table=pd.DataFrame(rows)
    quarter=statement_basis(table,'单季度')
    assert quarter.loc[quarter.period.eq('2025-06-30') & quarter.field.eq('revenue'),'value'].iloc[0]==35.
    assert quarter.loc[quarter.field.eq('total_assets'),'value'].iloc[0]==1000.
    ttm=statement_basis(table,'TTM')
    assert ttm.loc[ttm.period.eq('2025-06-30') & ttm.field.eq('revenue'),'value'].iloc[0]==120.
    assert pd.isna(ttm.loc[ttm.period.eq('2025-03-31'),'value'].iloc[0])
    assert ttm.loc[ttm.period.eq('2025-06-30') & ttm.field.eq('revenue'),'input_count'].iloc[0]==3
