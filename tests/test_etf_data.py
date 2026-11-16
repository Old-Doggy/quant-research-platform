import pandas as pd
import pytest


def source():
    return pd.DataFrame(dict(date=['2025-01-02','2025-01-03'],open=[4.,4.1],high=[4.,4.1],
        low=[4.,4.1],close=[4.,4.1],volume=[1000,2000],amount=[4000,8200]))


def test_etf_uses_units_not_akshare_document_lots_and_retains_raw():
    from portfolio_app.providers.etf import SinaETF
    raw=source()
    batch=SinaETF(transport=lambda **kw:raw).daily('510300.SH',start='2025-01-02',end='2025-01-03')
    assert batch.frame.volume.tolist()==[1000,2000]
    assert batch.frame.amount.tolist()==[4000,8200]
    assert batch.metadata['volume_unit']=='fund_units'
    assert batch.metadata['coverage']=='observed_rows_only'
    assert batch.metadata['research_ready'] is False
    assert batch.raw.equals(raw)


def test_etf_invalid_scope_duplicate_days_and_missing_amount_are_not_guessed():
    from portfolio_app.providers.etf import SinaETF
    adapter=SinaETF(transport=lambda **kw:pytest.fail('invalid scope reached source'))
    for symbol in ['600000.SH','113052.SH','../510300.SH']:
        with pytest.raises(ValueError): adapter.daily(symbol,start='2025-01-02',end='2025-01-03')
    with pytest.raises(ValueError):
        SinaETF(transport=lambda **kw:pd.concat([source()]*2)).daily('510300.SH',start='2025-01-02',end='2025-01-03')
    missing=SinaETF(transport=lambda **kw:source().drop(columns='amount')).daily('510300.SH',start='2025-01-02',end='2025-01-03')
    assert missing.frame.amount.isna().all()
    assert missing.metadata['missing_amount_rows']==2
    wrong=source().assign(volume=lambda x:x.volume*100)
    with pytest.raises(ValueError,match='单位'):
        SinaETF(transport=lambda **kw:wrong).daily('510300.SH',start='2025-01-02',end='2025-01-03')


def test_etf_browse_comparison_keeps_dates_missing_gaps_and_price_return_label():
    from portfolio_app.etf_research import compare_etf_prices
    a=source().rename(columns={'date':'trade_date'})
    b=a.assign(close=[10.,9.])
    result=compare_etf_prices({'510300.SH':a,'511010.SH':b})
    stats=result['summary'].set_index('symbol')
    assert stats.loc['510300.SH','price_return']==pytest.approx(.025)
    assert stats.loc['511010.SH','price_return']==pytest.approx(-.1)
    assert stats.loc['511010.SH','max_price_drawdown']==pytest.approx(-.1)
    assert result['basis']=='unadjusted_price_change_excluding_distributions'
    assert result['curves']['510300.SH'].price_index.tolist()==pytest.approx([1.,1.025])


def test_etf_artifact_index_reopens_and_detects_corruption(tmp_path):
    from portfolio_app.providers.etf import SinaETF
    from portfolio_app.etf_research import ETFStore
    store=ETFStore(tmp_path)
    artifact=store.ingest(SinaETF(transport=lambda **kw:source()).daily('510300.SH',start='2025-01-02',end='2025-01-03'))
    restored=ETFStore(tmp_path)
    assert restored.records()[0]['artifact_id']==artifact
    assert restored.load(artifact).frame.volume.tolist()==[1000,2000]
    (tmp_path/'batches'/artifact/'normalized.parquet').write_bytes(b'broken')
    with pytest.raises(ValueError): restored.load(artifact)


def test_etf_page_opens_saved_batches_and_table_without_network(tmp_path,monkeypatch):
    from portfolio_app.providers.etf import SinaETF
    from portfolio_app.etf_research import ETFStore
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    ETFStore(tmp_path/'etf_service').ingest(SinaETF(transport=lambda **kw:source()).daily(
        '510300.SH',start='2025-01-02',end='2025-01-03'))
    monkeypatch.setattr('portfolio_app.providers.etf.sdk_daily',lambda *a,**k:pytest.fail('browse fetched data'))
    app=AppTest.from_string('from portfolio_app.etf_view import render_etf_data\nrender_etf_data()').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    app.segmented_control(key='etf_display').set_value('表格').run()
    assert not app.exception and len(app.dataframe)==2
    assert app.dataframe[0].value.volume.tolist()==[1000,2000]
