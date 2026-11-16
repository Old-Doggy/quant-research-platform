import pandas as pd
import pytest


def profile():
    return pd.DataFrame({'item':['债券代码','债券简称','债券类型','债券面值（元）','上市日期','到期日','摘牌日','信用等级'],
        'value':['sh113052','兴业转债','可转换企业债','100','2022-01-14','2027-12-27','--','AAA']})


def history():
    return pd.DataFrame(dict(date=['2025-01-02','2025-01-03'],open=[110.,111.],high=[110.,111.],
        low=[110.,111.],close=[110.,111.],volume=[1000,2000]))


HTML='''<html><a href="http://finance.sina.com.cn/realstock/company/sh601166/nc.shtml">兴业银行</a>
<table><tr><td>公告日期</td><td>转股价格生效日期</td><td>转股价格（元）</td></tr>
<tr><td>2025-01-02</td><td>2025-01-06</td><td>20</td></tr>
<tr><td>2024-01-02</td><td>2024-01-06</td><td>25</td></tr></table></html>'''


def test_cb_profile_keeps_expired_instruments_and_distinct_dates():
    from portfolio_app.providers.convertible import normalize_profile
    master=normalize_profile(profile(),'113052.SH')
    assert master['face_value']==100 and master['stock_symbol']=='unknown'
    assert master['maturity_date']=='2027-12-27' and master['delist_date'] is None
    expired=profile();expired.loc[expired['item'].eq('摘牌日'),'value']='2025-07-18'
    assert normalize_profile(expired,'113052.SH')['delist_date']=='2025-07-18'


def test_cb_price_change_dates_require_both_announcement_and_effective_time():
    from portfolio_app.providers.convertible import parse_conversion_page
    from portfolio_app.convertible_events import conversion_price_asof,conversion_premium
    parsed=parse_conversion_page(HTML,'113052.SH',fetched_at='2025-01-03T08:00:00+08:00')
    assert parsed['stock_symbol']=='601166.SH'
    assert conversion_price_asof(parsed['events'],session='2025-01-03',as_of='2025-01-03') is None
    assert conversion_price_asof(parsed['events'],session='2025-01-06',as_of='2025-01-06')['price']==20.
    assert conversion_premium(bond_price=110,stock_price=10,conversion_price=20,face_value=100)==pytest.approx(1.2)
    late=parse_conversion_page(HTML,'113052.SH',fetched_at='2026-01-01T08:00:00+08:00')
    assert conversion_price_asof(late['events'],session='2025-01-06',as_of='2025-01-06') is None


def test_cb_daily_preserves_unknown_amount_not_closing_price_times_volume():
    from portfolio_app.providers.convertible import SinaConvertible
    batch=SinaConvertible(transport=lambda operation,symbol:history()).daily('113052.SH',start='2025-01-02',end='2025-01-03')
    assert batch.frame.volume.tolist()==[1000,2000]
    assert batch.frame.amount.isna().all()
    assert batch.metadata['volume_unit']=='bonds'
    assert batch.metadata['research_ready'] is False
    with pytest.raises(ValueError): SinaConvertible().daily('510300.SH',start='2025-01-02',end='2025-01-03')


def test_cb_events_reject_conflicting_effective_prices_and_nonfinite_premium():
    from portfolio_app.providers.convertible import parse_conversion_page
    from portfolio_app.convertible_events import conversion_price_asof,conversion_premium
    result=parse_conversion_page(HTML.replace('</table>','<tr><td>2025-01-02</td><td>2025-01-06</td><td>21</td></tr></table>'),
        '113052.SH',fetched_at='2025-01-03T08:00:00+08:00')
    with pytest.raises(ValueError,match='冲突'):
        conversion_price_asof(result['events'],session='2025-01-06',as_of='2025-01-06')
    with pytest.raises(ValueError): conversion_premium(bond_price=110,stock_price=10,conversion_price=0,face_value=100)


def reference_batch():
    from portfolio_app.providers.convertible import SinaConvertible
    def transport(operation,symbol):
        if operation=='profile': return profile()
        return pd.DataFrame([dict(html=HTML if operation=='quotes' else HTML[HTML.index('<table>'):])])
    return SinaConvertible(transport=transport).reference('113052.SH')


def test_cb_reference_keeps_raw_announcements_and_quote_stock_evidence():
    batch=reference_batch()
    assert batch.metadata['master']['stock_symbol']=='601166.SH'
    assert batch.metadata['events'][0]['ann_date']=='2025-01-02'
    assert batch.metadata['events'][0]['effective_date']=='2025-01-06'
    assert len(batch.metadata['events'])==2
    assert batch.raw.conversion_html.str.contains('公告日期').all()
    assert batch.raw.quotes_html.str.contains('601166').all()
    assert batch.metadata['research_ready'] is False


def test_cb_event_boundary_rejects_naive_observation_and_invalid_events():
    from portfolio_app.convertible_events import conversion_price_asof
    valid=dict(symbol='113052.SH',ann_date='2025-01-02',effective_date='2025-01-06',
        price=20.,fetched_at='2025-01-03T08:00:00+08:00')
    for patch in [dict(fetched_at='2025-01-03T08:00:00'),dict(price=-1.),dict(ann_date='2025-02-01'),
                  dict(effective_date='bad'),dict(symbol='600000.SH')]:
        with pytest.raises(ValueError):
            conversion_price_asof([{**valid,**patch}],session='2025-01-06',as_of='2025-01-06')
    with pytest.raises(ValueError,match='证券'):
        conversion_price_asof([valid,{**valid,'symbol':'113050.SH'}],session='2025-01-06',as_of='2025-01-06')


def test_cb_store_reopen_preserves_events_and_rejects_corruption(tmp_path):
    from portfolio_app.convertible_store import ConvertibleStore
    store=ConvertibleStore(tmp_path)
    artifact=store.ingest(reference_batch())
    reopened=ConvertibleStore(tmp_path)
    assert reopened.records()[0]['artifact_id']==artifact
    assert reopened.load(artifact).metadata['events'][0]['price']==20.
    with store.connect() as db:
        db.execute('UPDATE cb_batches SET symbol=? WHERE artifact=?',('113050.SH',artifact))
    with pytest.raises(ValueError,match='索引'): reopened.load(artifact)
    with store.connect() as db:
        db.execute('UPDATE cb_batches SET symbol=? WHERE artifact=?',('113052.SH',artifact))
    (tmp_path/'batches'/artifact/'normalized.parquet').write_bytes(b'broken')
    with pytest.raises(ValueError): reopened.load(artifact)


def test_cb_reference_rejects_conflicting_stock_links():
    from portfolio_app.providers.convertible import SinaConvertible
    def transport(operation,symbol):
        if operation=='profile': return profile()
        html=HTML if operation=='conversion' else HTML.replace('sh601166','sh600000')
        return pd.DataFrame([dict(html=html)])
    with pytest.raises(ValueError,match='正股'):
        SinaConvertible(transport=transport).reference('113052.SH')


def test_cb_charts_keep_actual_rows_units_and_announcement_dates():
    from portfolio_app.convertible_view import price_chart,conversion_chart
    from portfolio_app.providers.convertible import SinaConvertible
    batch=SinaConvertible(transport=lambda *a:history()).daily('113052.SH',start='2025-01-02',end='2025-01-03')
    price=price_chart(batch)
    assert list(price.data[0].y)==[110.,111.]
    assert list(price.data[1].y)==[1000,2000]
    assert len(price.data[0].x)==2
    events=reference_batch().metadata['events']
    chart=conversion_chart(events,'113052.SH')
    assert list(chart.data[0].y)==[25.,20.]
    assert list(chart.data[0].customdata)==['2024-01-02','2025-01-02']
    assert chart.data[0].line.shape=='hv'


def test_cb_page_reopens_saved_data_without_network_and_handles_missing_reference(tmp_path,monkeypatch):
    from portfolio_app.providers.convertible import SinaConvertible
    from portfolio_app.convertible_store import ConvertibleStore
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    store=ConvertibleStore(tmp_path/'convertible_service')
    store.ingest(SinaConvertible(transport=lambda *a:history()).daily('113052.SH',start='2025-01-02',end='2025-01-03'))
    monkeypatch.setattr('portfolio_app.providers.convertible.sdk_fetch',lambda *a:pytest.fail('browse fetched data'))
    app=AppTest.from_string('from portfolio_app.convertible_view import render_convertible_data\nrender_convertible_data()').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    store.ingest(reference_batch())
    app.run()
    assert not app.exception and len(app.get('plotly_chart'))==2
    assert app.selectbox(key='cb_symbol').value=='113052.SH'
    app.segmented_control(key='cb_display').set_value('表格').run()
    assert not app.exception and len(app.get('plotly_chart'))==0
    assert app.dataframe[0].value['成交量（张）'].tolist()==[1000,2000]
    assert app.dataframe[0].value['成交额（元）'].isna().all()
