import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from test_market_overview import daily_frame, snapshot


def report():
    from portfolio_app.market_overview import market_overview
    return market_overview(daily_frame(dict(symbol=['AAA','BBB'],
        trade_date=pd.to_datetime(['2025-01-03']*2),close=[11.,9.],pre_close=[10.,10.],
        amount=[100.,200.],volume=[10,20])), manifest=snapshot(), session='2025-01-03')


def test_breadth_and_ranking_share_same_report_and_stable_security_ids():
    from portfolio_app.market_overview_view import breadth_chart, ranking_chart, overview_table
    value = report()
    breadth = breadth_chart(value)
    assert sum(breadth.data[0].x) == value['expected']
    assert list(breadth.data[0].y) == list(value['breadth'])
    ranking = ranking_chart(value, metric='price_change')
    assert list(ranking.data[0].x) == pytest.approx([-.1,.1])
    assert [r[0] for r in ranking.data[0].customdata] == ['BBB','AAA']
    assert ranking.layout.clickmode == 'event+select'
    table = overview_table(value)
    assert table['证券'].tolist() == ['AAA','BBB','CCC']
    assert table['状态'].tolist() == ['已记录','已记录','行情缺失']
    assert table['价格涨跌幅'].tolist()[:2] == pytest.approx([.1,-.1])
    assert pd.isna(table.loc[2,'价格涨跌幅'])
    assert table['成交额（元）'].sum() == value['amount_cny']
    assert len(ranking_chart(value,metric='amount').data[0].x) == 2


def test_chart_selection_accepts_only_explicit_security_ids():
    from portfolio_app.market_overview_view import selected_symbol
    assert selected_symbol([dict(customdata=['AAA','name'])], ['AAA']) == 'AAA'
    for points in ([],[{}],[dict(customdata='AAA')],[dict(customdata=['OUTSIDE'])]):
        assert selected_symbol(points,['AAA']) is None


def test_overview_graph_table_switch_uses_verified_query_and_stops_on_corruption(tmp_path, monkeypatch):
    from test_snapshot_store import setup_store
    from test_market_watch import publish_free
    from portfolio_app.providers.base import ProviderBatch
    store, updates, ids, master, calendar = setup_store(tmp_path/'market_service')
    changed = []
    for artifact in ids:
        batch = updates.read_artifact(artifact)
        batch.frame['symbol'] = batch.frame.ts_code
        batch.frame['pre_close'] = 9.
        changed.append(updates.save_artifact(ProviderBatch(batch.frame,batch.raw,batch.metadata,batch.completeness)))
    manifest = publish_free(store,changed,master,calendar)
    monkeypatch.setenv('OVERVIEW_TEST_ROOT', str(store.root))
    monkeypatch.setenv('OVERVIEW_TEST_ID', manifest['snapshot_id'])
    app = AppTest.from_string('''
import os
from portfolio_app.snapshot_store import SnapshotStore
from portfolio_app.market_overview_view import render_market_overview
store = SnapshotStore(os.environ['OVERVIEW_TEST_ROOT'])
render_market_overview(store, store.open(os.environ['OVERVIEW_TEST_ID']))
''', default_timeout=30).run()
    assert not app.exception
    assert len(app.get('plotly_chart')) == 2
    app.button_group(key='market_overview_display').set_value('表格').run()
    assert not app.exception
    assert app.dataframe[0].value.loc[0,'价格涨跌幅'] == pytest.approx(10/9-1)
    assert app.metric[0].value == '+11.11%'
    (store.root/'batches'/changed[1]/'normalized.parquet').write_bytes(b'corrupt')
    app.run()
    assert not app.exception and len(app.get('plotly_chart')) == 0
    assert any('校验失败' in e.value for e in app.error)
