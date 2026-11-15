from pathlib import Path
from streamlit.testing.v1 import AppTest


def app():
    return AppTest.from_file(str(Path(__file__).resolve().parents[1]/'portfolio_app'/'local_app.py'),default_timeout=60)


def publish_free(store,ids,master,calendar):
    return store.publish_daily(dataset_id='free-a-daily',batch_ids=[ids[0]],comparison_ids=[ids[1]],
        master=master,calendars={'SSE':calendar},start='2025-01-02',end='2025-01-02',symbols=['600000.SH'])


def test_live_browsing_tracks_generation_while_pinned_link_and_research_result_stay_fixed(tmp_path,monkeypatch):
    from test_snapshot_store import setup_store
    from portfolio_app.providers.base import ProviderBatch
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    monkeypatch.setenv('PORTFOLIO_MODE','local')
    store,updates,ids,master,calendar=setup_store(tmp_path/'market_service')
    first=publish_free(store,ids,master,calendar)
    # The production adapters include these aliases. Add them to this synthetic fixture.
    changed=[]
    for artifact in ids:
        batch=updates.read_artifact(artifact)
        batch.frame['symbol']=batch.frame.ts_code
        batch.frame['vol']=batch.frame.volume
        batch.frame['pre_close']=10.
        changed.append(updates.save_artifact(ProviderBatch(batch.frame,batch.raw,batch.metadata,batch.completeness)))
    first=publish_free(store,changed,master,calendar)
    view=app().run()
    old_result={'identity':'keep-this-research'}
    view.session_state['dashboard_research_submission']=old_result
    view.button_group(key='watch_view').set_value('更新行情').run()
    assert not view.exception
    assert view.session_state['_actual_context_watch']['snapshot_id']==first['snapshot_id']
    assert view.session_state['dashboard_research_submission']==old_result
    second=publish_free(store,changed,master,calendar)
    view.run()
    assert not view.exception
    assert view.session_state['_actual_context_watch']['snapshot_id']==second['snapshot_id']
    view.checkbox(key='market_watch_follow').uncheck().run()
    view.selectbox(key='market_watch_version').select(first['snapshot_id']).run()
    assert not view.exception
    assert view.session_state['_actual_context_watch']['snapshot_id']==first['snapshot_id']
    assert view.query_params['snapshot_id']==first['snapshot_id']
    assert view.session_state['dashboard_research_submission']==old_result
    restored=app()
    restored.query_params.update(dict(view.query_params))
    restored.run()
    assert not restored.exception
    assert not restored.checkbox(key='market_watch_follow').value
    assert restored.session_state['_actual_context_watch']['snapshot_id']==first['snapshot_id']


def test_browsing_context_does_not_reuse_strategy_or_change_previous_context():
    from test_context_v2 import context
    from portfolio_app.market_watch import browsing_context
    original=context(strategy_id='trend')
    manifest=dict(dataset_id='free-a-daily',snapshot_id='snapshot-new',generation=2,
        range=dict(start='2025-01-02',end='2025-01-03',symbols=['600000.SH']))
    selected=browsing_context(original,manifest,'600000.SH')
    assert selected.strategy_id is None
    assert original.strategy_id=='trend'
    assert selected.dataset_generation==2
    assert selected.context_id!=original.context_id
