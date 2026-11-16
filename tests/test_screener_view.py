import pytest


def test_scatter_points_preserve_ids_and_exclude_only_missing_coordinates():
    from portfolio_app.screener_view import screen_scatter,screen_table
    from portfolio_app.screener import screen_daily
    from test_screener import config,frame
    from test_market_overview import snapshot
    result=screen_daily(frame(),manifest=snapshot(),config=config())
    figure=screen_scatter(result,x='amount',y='price_change')
    assert figure.data[0].x==(100.,200.)
    assert [p[0] for p in figure.data[0].customdata]==['AAA','BBB']
    assert list(figure.data[0].y)==pytest.approx([.1,-.1])
    assert len(screen_table(result))==3
    assert '%{y:.2%}' in figure.data[0].hovertemplate


@pytest.mark.parametrize('conditions',[
    [dict(field='close',op='ge',value=0.,missing='exclude')],
    [dict(field='close',op='ge',value=1.,missing='keep'),dict(field='amount',op='ge',value=1.,missing='exclude')],
    [dict(field='close',op='ge',value=1.,missing='exclude'),dict(field='close',op='ge',value=2.,missing='exclude')],
    [dict(field='price_change',op='ge',value=-1.,missing='exclude')],
])
def test_restore_does_not_silently_rewrite_conditions(conditions):
    from portfolio_app.screener_view import control_values
    from test_screener import config
    with pytest.raises(ValueError):
        control_values(dict(config=config(conditions=conditions),view=dict(x='amount',y='price_change')))


def test_nondefault_form_roundtrip_preserves_conditions():
    from portfolio_app.screener_view import control_values,form_conditions
    from test_screener import config
    original=[dict(field='amount',op='ge',value=1.23e8,missing='keep'),
        dict(field='close',op='ge',value=8.5,missing='keep'),
        dict(field='price_change',op='ge',value=-.025,missing='keep')]
    values=control_values(dict(config=config(conditions=original),view=dict(x='close',y='volume')))
    assert form_conditions(values['screen_amount_floor'],values['screen_price_floor'],
        values['screen_rise_floor'],values['screen_missing'])==original


def test_screen_ui_filters_saves_restores_and_uses_same_table(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_snapshot_store import setup_store
    from test_market_watch import publish_free
    from portfolio_app.providers.base import ProviderBatch
    store,updates,ids,master,calendar=setup_store(tmp_path/'market_service')
    changed=[]
    for artifact in ids:
        batch=updates.read_artifact(artifact)
        batch.frame['symbol']=batch.frame.ts_code
        batch.frame['source_pre_close']=9.
        changed.append(updates.save_artifact(ProviderBatch(batch.frame,batch.raw,batch.metadata,batch.completeness)))
    manifest=publish_free(store,changed,master,calendar)
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    monkeypatch.setenv('SCREEN_TEST_ID',manifest['snapshot_id'])
    script='''
import os
from portfolio_app.snapshot_store import SnapshotStore
from portfolio_app.state_paths import state_root
from portfolio_app.screener_view import render_screener
store=SnapshotStore(state_root()/'market_service')
render_screener(store,store.open(os.environ['SCREEN_TEST_ID']))
'''
    app=AppTest.from_string(script,default_timeout=30).run()
    assert not app.exception and len(app.get('plotly_chart'))==2
    app.number_input(key='screen_amount_floor').set_value(.002).run()
    assert app.metric[0].value=='0 / 1'
    app.number_input(key='screen_amount_floor').set_value(0.).run()
    app.text_input(key='screen_save_name').set_value('我的筛选').run()
    app.button(key='screen_save').click().run()
    assert not app.exception and len(app.success)==1
    restored=AppTest.from_string(script,default_timeout=30).run()
    restored.selectbox(key='screen_saved_pick').select_index(1).run()
    restored.button(key='screen_restore').click().run()
    assert not restored.exception
    assert any('已核对' in s.value for s in restored.success)
    restored.button_group(key='screen_display').set_value('表格').run()
    assert restored.dataframe[0].value['证券'].tolist()==['600000.SH']
    assert not any(b.key=='screen_send_to_strategy' for b in restored.button)
    restored.button_group(key='screen_display').set_value('散点').run()
    restored.selectbox(key='screen_x').set_value('close').run()
    restored.selectbox(key='screen_y').set_value('volume').run()
    restored.button_group(key='screen_display').set_value('表格').run()
    restored.text_input(key='screen_save_name').set_value('表格保留坐标').run()
    restored.button(key='screen_save').click().run()
    from portfolio_app.screener_store import ScreenerStore
    receipts=ScreenerStore(tmp_path/'screening')
    entry=next(r for r in receipts.records() if r['name']=='表格保留坐标')
    assert receipts.open(entry['identifier'])['view']==dict(x='close',y='volume')
