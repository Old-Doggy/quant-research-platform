from streamlit.testing.v1 import AppTest


def data_app():
    return AppTest.from_string('from portfolio_app.data_service_view import render_data_service\nrender_data_service()',default_timeout=30)


def test_hidden_coverage_and_sources_do_not_read_data(tmp_path, monkeypatch):
    import portfolio_app.data_coverage_view as coverage
    import portfolio_app.data_service_view as service
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    monkeypatch.setattr(coverage,'render_coverage',lambda store:(_ for _ in ()).throw(AssertionError('hidden query')))
    monkeypatch.setattr(service,'render_provider_status',lambda:(_ for _ in ()).throw(AssertionError('hidden source')))
    app=data_app().run()
    assert not app.exception
    assert len(app.get('plotly_chart'))==0


def test_coverage_query_matches_snapshot_and_corrupt_batch_is_explicit(tmp_path, monkeypatch):
    from test_snapshot_store import setup_store,publish
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    root=tmp_path/'market_service'
    store,updates,ids,master,calendar=setup_store(root)
    snapshot=publish(store,ids,master,calendar)
    app=data_app().run()
    app.session_state['data_service_tab']='覆盖与版本'
    app.run()
    assert not app.exception
    assert len(app.get('plotly_chart'))==2
    app.button_group(key='coverage_view_mode').set_value('表格').run()
    assert app.dataframe[0].value['状态'].tolist()==['已核对日线']
    assert app.selectbox(key='coverage_snapshot').value==snapshot['snapshot_id']
    (root/'batches'/ids[0]/'normalized.parquet').write_bytes(b'corrupt')
    app.run()
    assert not app.exception
    assert any('底层批次' in item.value for item in app.error)
    assert len(app.get('plotly_chart'))==0


def test_corrupt_current_pointer_and_manifest_never_crash_data_center(tmp_path,monkeypatch):
    from test_snapshot_store import setup_store,publish
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    store,updates,ids,master,calendar=setup_store(tmp_path/'market_service')
    published=publish(store,ids,master,calendar)
    pointer=store.directory/'free-a-daily'/'current.json'
    pointer.parent.mkdir()
    pointer.write_text('{')
    app=data_app().run()
    assert not app.exception
    assert any('索引校验失败' in item.value for item in app.error)
    (store.directory/(published['snapshot_id']+'.json')).write_text('{')
    app.session_state['data_service_tab']='覆盖与版本'
    app.run()
    assert not app.exception
    assert any('版本清单' in item.value for item in app.warning)


def test_coverage_chart_selection_carries_actual_security_and_session():
    import pandas as pd
    from portfolio_app.data_coverage_view import coverage_chart
    rows=pd.DataFrame([dict(symbol='600000.SH',session='2025-01-02',status='observed'),
        dict(symbol='000001.SZ',session='2025-01-02',status='unknown_gap')])
    chart=coverage_chart(rows,'snapshot-test')
    assert chart.data[0].customdata==(['600000.SH','2025-01-02'],)
    assert chart.data[1].customdata==(['000001.SZ','2025-01-02'],)
    assert chart.layout.clickmode=='event+select'
