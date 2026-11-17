import pytest


def snapshot(tmp_path):
    from test_snapshot_store import setup_store,publish
    store,updates,ids,master,calendar=setup_store(tmp_path)
    result=publish(store,ids,master,calendar)
    return store,result


def test_query_filters_columns_and_rows_and_records_snapshot_without_full_frame_reader(tmp_path,monkeypatch):
    from portfolio_app.market_query import query_daily
    store,manifest=snapshot(tmp_path)
    monkeypatch.setattr(store,'read_frame',lambda *a:(_ for _ in ()).throw(AssertionError('full read')))
    result=query_daily(store,manifest['snapshot_id'],symbols=['600000.SH'],start='2025-01-02',
        end='2025-01-02',columns=['trade_date','ts_code','close'])
    assert result.columns.tolist()==['trade_date','ts_code','close']
    assert result.close.tolist()==[10.]
    assert result.attrs['snapshot']['snapshot_id']==manifest['snapshot_id']
    assert result.attrs['research_capabilities']['corporate_action_backtest'] is False
    from portfolio_app.research_dataset import record_context
    session={}
    record_context(session,'watch',result)
    assert session['_actual_context_watch']['snapshot_id']==manifest['snapshot_id']
    assert session['_actual_context_watch']['dataset_generation']==manifest['generation']


def test_query_budgets_and_unknown_scope_fail_before_unbounded_result(tmp_path):
    from portfolio_app.market_query import query_daily
    store,manifest=snapshot(tmp_path)
    common=dict(symbols=['600000.SH'],start='2025-01-02',end='2025-01-02',columns=['trade_date','ts_code','close'])
    for changes in [dict(symbols=[]),dict(symbols=['000001.SZ']),dict(start='2024-01-01'),
                    dict(columns=['missing']),dict(max_rows=0),dict(max_bytes=1)]:
        with pytest.raises(ValueError):
            query_daily(store,manifest['snapshot_id'],**{**common,**changes})


def test_bad_artifact_is_never_queried_even_when_column_not_requested(tmp_path):
    from portfolio_app.market_query import query_daily
    store,manifest=snapshot(tmp_path)
    artifact=manifest['batch_ids'][0]
    (tmp_path/'batches'/artifact/'raw.parquet').write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        query_daily(store,manifest['snapshot_id'],symbols=['600000.SH'],start='2025-01-02',
            end='2025-01-02',columns=['close'])
