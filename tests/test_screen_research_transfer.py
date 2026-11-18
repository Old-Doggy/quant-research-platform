import copy

import pandas as pd
import pytest


def screen_inputs(tmp_path):
    from test_snapshot_store import setup_store
    from test_market_watch import publish_free
    from portfolio_app.providers.base import ProviderBatch
    from portfolio_app.market_query import query_daily
    from portfolio_app.screener import screen_daily
    store,updates,ids,master,calendar=setup_store(tmp_path/'market_service')
    aliases=[]
    for identifier in ids:
        batch=updates.read_artifact(identifier)
        batch.frame['symbol']=batch.frame.ts_code
        batch.frame['vol']=batch.frame.volume
        aliases.append(updates.save_artifact(ProviderBatch(batch.frame,batch.raw,batch.metadata,batch.completeness)))
    manifest=publish_free(store,aliases,master,calendar)
    frame=query_daily(store,manifest['snapshot_id'],symbols=['600000.SH'],start='2025-01-02',
        end='2025-01-02',columns=['symbol','ts_code','trade_date','open','high','low','close','volume','vol','amount','pre_close'])
    config=dict(schema='daily-screener.v1',snapshot_id=manifest['snapshot_id'],session='2025-01-02',
        universe_policy='snapshot_listed_on_session',conditions=[])
    return store,manifest,frame,screen_daily(frame,manifest=manifest,config=config)


def test_browsing_receipt_cannot_change_research_selection_even_if_flag_is_forged(tmp_path):
    from portfolio_app.screen_research_transfer import prepare_screen_research
    store,manifest,frame,result=screen_inputs(tmp_path)
    result['research_ready']=True
    session={'_registered_research_dataset':pd.DataFrame({'keep':[1]})}
    with pytest.raises(ValueError,match='浏览|核验'):
        prepare_screen_research(store,result,session,target='factors')
    assert session['_registered_research_dataset'].to_dict()=={'keep':{0:1}}


def test_transfer_keeps_every_selected_symbol_and_selection_time_without_future_rows(monkeypatch):
    from portfolio_app.screen_research_transfer import prepare_screen_research
    from portfolio_app.workspace_router import parse_route_query
    from portfolio_app.screener import screen_daily
    from test_market_overview import snapshot
    from test_screener import frame,config
    manifest=snapshot()
    manifest['range']['symbols']=['600000.SH','000001.SZ','688001.SH']
    manifest['instrument_master']['records']=[dict(symbol=s,name=s,market='SSE' if s.endswith('SH') else 'SZSE',
        listed_on='2020-01-01',delisted_on=None) for s in manifest['range']['symbols']]
    manifest['research_capabilities']={'corporate_action_backtest':True}
    manifest['calendars']['SZSE']={**manifest['calendars']['SSE'],'market':'SZSE'}
    data=frame().replace({'AAA':'600000.SH','BBB':'000001.SZ','CCC':'688001.SH'})
    for field in ['open','high','low']:data[field]=data.close
    data['ts_code']=data.symbol
    data['vol']=data.volume
    result=screen_daily(data,manifest=manifest,config=config())
    class Store:
        def open(self,identifier):
            assert identifier==manifest['snapshot_id'];return copy.deepcopy(manifest)
    calls=[]
    def query(store,identifier,**options):
        calls.append(options)
        owned=data.copy(deep=True)
        owned.attrs['snapshot']={'snapshot_id':identifier}
        owned.attrs['research_dataset']=dict(dataset_id=manifest['dataset_id'],version=identifier,
            snapshot_id=identifier,dataset_generation=manifest['generation'],price_basis='raw',source_kind='provider_snapshot')
        owned.attrs['research_capabilities']=manifest['research_capabilities'].copy()
        return owned
    monkeypatch.setattr('portfolio_app.screen_research_transfer.query_daily',query)
    session={}
    route=prepare_screen_research(Store(),result,session,target='factors')
    owned=session['_registered_research_dataset']
    assert sorted(owned.symbol.unique())==result['symbols']
    assert calls[0]['end']==result['session']
    assert calls[0]['start']==manifest['range']['start']
    assert owned.attrs['research_dataset']['snapshot_id']==result['snapshot_id']
    assert owned.attrs['screen_selection']['selected_on']==result['session']
    pd.testing.assert_series_equal(owned['vol'],owned['volume'],check_names=False)
    assert session['_use_registered_research_dataset'] is True
    context=parse_route_query(route).context
    assert sorted(context.symbols)==result['symbols']
    assert context.as_of==result['session'] and context.workspace=='factors'
    assert context.universe_id==result['screen_id']
    assert context.date_start==manifest['range']['start']
    altered=copy.deepcopy(result)
    altered['symbols']=altered['symbols'][:1]
    untouched={'_use_registered_research_dataset':False}
    with pytest.raises(ValueError,match='不一致'):
        prepare_screen_research(Store(),altered,untouched,target='strategy')
    assert untouched=={'_use_registered_research_dataset':False}


def test_research_buttons_are_available_only_after_manifest_gate(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    import portfolio_app.screener_view as view
    store,manifest,frame,result=screen_inputs(tmp_path)
    manifest['research_capabilities']['corporate_action_backtest']=True
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    monkeypatch.setattr(view,'_query',lambda *args:frame.copy(deep=True))
    monkeypatch.setattr('portfolio_app.snapshot_store.SnapshotStore.open',lambda *args:copy.deepcopy(manifest))
    script='''
from portfolio_app.screener_view import render_screener
from portfolio_app.snapshot_store import SnapshotStore
from portfolio_app.state_paths import state_root
store=SnapshotStore(state_root()/'market_service')
render_screener(store,store.open('test-only-verified-manifest'))
'''
    app=AppTest.from_string(script,default_timeout=30).run()
    assert not app.exception
    assert app.button(key='screen_send_to_factors').label=='送入因子研究'
    assert app.button(key='screen_send_to_strategy').label=='送入策略研究'
    assert app.query_params=={}


def test_changed_receipt_or_empty_pool_never_activates(monkeypatch):
    from portfolio_app.screen_research_transfer import prepare_screen_research
    from test_market_overview import snapshot
    manifest=snapshot();manifest['research_capabilities']={'corporate_action_backtest':True}
    class Store:
        def open(self,identifier):return manifest
    monkeypatch.setattr('portfolio_app.screen_research_transfer.query_daily',
        lambda *a,**k:pytest.fail('invalid receipt reached query'))
    with pytest.raises(ValueError):prepare_screen_research(Store(),{'symbols':[]}, {},target='factors')


@pytest.mark.parametrize('target,flat',[('factors',False),('strategy',False),('strategy',True)])
def test_click_transfer_opens_real_workspace_with_complete_synthetic_pool(tmp_path,monkeypatch,target,flat):
    """Only the data boundary is simulated; navigation and workspace rendering are real."""
    import numpy as np
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from portfolio_app.calendar_service import MarketCalendar
    from test_market_overview import snapshot
    manifest=snapshot()
    dates=pd.bdate_range('2025-01-02',periods=100)
    symbols=['600000.SH','688001.SH','600519.SH']
    manifest['range']=dict(start=dates[0].date().isoformat(),end=dates[-1].date().isoformat(),symbols=symbols)
    manifest['instrument_master']['records']=[dict(symbol=s,name=s,market='SSE',listed_on='2020-01-01',delisted_on=None) for s in symbols]
    manifest['research_capabilities']={'corporate_action_backtest':True}
    manifest['calendars']={'SSE':MarketCalendar('SSE','Asia/Shanghai','synthetic-test-only',1,
        tuple((d.date().isoformat(),d in dates) for d in pd.date_range(dates[0],dates[-1]))).to_dict()}
    rows=[]
    for i,symbol in enumerate(symbols):
        close=10+i+np.arange(100)/100+np.sin(np.arange(100)/(5+i))
        if flat:
            close=np.full(100,10.+i)
        rows.append(pd.DataFrame(dict(symbol=symbol,ts_code=symbol,trade_date=dates,open=close,high=close,
            low=close,close=close,volume=10000+np.arange(100),amount=close*10000,pre_close=close)))
    source=pd.concat(rows,ignore_index=True)
    source.attrs=dict(field_units=dict(price='CNY_per_share',volume='shares',amount='CNY'),
        research_capabilities=manifest['research_capabilities'].copy(),
        research_dataset=dict(dataset_id='fixture',version=manifest['snapshot_id'],source_kind='synthetic',
            price_basis='raw',snapshot_id=manifest['snapshot_id'],dataset_generation=manifest['generation']))
    def query(*args,**kw):
        result=source.loc[source.trade_date.between(kw['start'],kw['end'])].copy(deep=True)
        return result
    monkeypatch.setenv('PORTFOLIO_MODE','local')
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    monkeypatch.setattr('portfolio_app.snapshot_store.SnapshotStore.open',lambda *args:copy.deepcopy(manifest))
    monkeypatch.setattr('portfolio_app.screener_view._query',lambda store,m,session:query(start=session,end=session))
    monkeypatch.setattr('portfolio_app.screen_research_transfer.query_daily',query)
    entry=str(Path('portfolio_app/local_app.py').resolve())
    script=f'''
import streamlit as st
if st.query_params.get('workspace'):
    import runpy
    runpy.run_path({entry!r},run_name='__main__')
else:
    from portfolio_app.screener_view import render_screener
    from portfolio_app.snapshot_store import SnapshotStore
    from portfolio_app.state_paths import state_root
    store=SnapshotStore(state_root()/'market_service')
    render_screener(store,store.open('synthetic-test-only'))
'''
    app=AppTest.from_string(script,default_timeout=30).run()
    assert not app.exception
    app.button(key='screen_send_to_'+target).click().run()
    assert not app.exception and not app.error
    assert app.radio(key='workspace_route_selector').value==target
    assert app.query_params['snapshot_id']==manifest['snapshot_id']
    actual=app.session_state['_actual_context_'+target]
    assert actual['dataset_id']=='fixture'
    assert actual['selected_on']==manifest['range']['end']
    selected=app.session_state['_registered_research_dataset']
    assert sorted(selected.symbol.unique())==sorted(symbols)
    pd.testing.assert_series_equal(selected.vol,selected.volume,check_names=False)
    app.radio(key='workspace_route_selector').set_value('experiments').run()
    app.radio(key='workspace_route_selector').set_value(target).run()
    assert not app.exception and not app.error
    assert app.session_state['_use_registered_research_dataset'] is True
    # Exercise the real asynchronous UI submission and durable input package.
    import time
    from portfolio_app.result_store import ResultStore
    from portfolio_app.result_replay import replay_saved
    run_key='factor_research_run' if target=='factors' else 'run_explicit_strategy'
    if target=='factors':
        app.selectbox(key='factor_research_id').select('basic.volume_ratio_20d').run()
    app.button(key=run_key).click().run()
    runner=app.session_state['_research_runner']
    deadline=time.monotonic()+20
    while runner.snapshot()['status']=='running' and time.monotonic()<deadline:
        time.sleep(.02)
    task=runner.snapshot()
    assert task['status']=='succeeded',runner.reports.internal_detail(task.get('failure',{}).get('error_id'))
    app.run()
    assert not app.exception and not app.error
    task_id=runner.snapshot()['task_id']
    store=ResultStore(tmp_path/'research_results')
    value=store.load(task_id)
    replay_frame=value['replay']['frame']
    if target=='strategy':
        assert all(row['status']!='invalid_data' for row in value['result_payload']['sensitivity'])
        if flat:
            assert all(row['sharpe'] is None for row in value['result_payload']['sensitivity'])
    expected_pool=sorted(symbols) if target=='factors' else [app.selectbox(key='explicit_strategy_symbol').value]
    assert sorted(replay_frame.symbol.unique())==expected_pool
    assert replay_frame.attrs['screen_selection']['selected_on']==manifest['range']['end']
    assert replay_saved(ResultStore(tmp_path/'research_results'),task_id)['status']=='matched'
    restarted=AppTest.from_file(entry,default_timeout=30)
    restarted.query_params.update(dict(app.query_params))
    restarted.query_params['workspace']='experiments'
    restarted.run()
    assert not restarted.exception and not restarted.error
    assert restarted.selectbox(key='saved_result_selected').value==task_id


def test_reopened_screen_route_without_registered_pool_never_uses_demo(tmp_path,monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from portfolio_app.research_context import ResearchContext
    from portfolio_app.workspace_router import build_workspace_state,encode_route_query
    monkeypatch.setenv('PORTFOLIO_MODE','local')
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    context=ResearchContext(dataset_id='missing-screen-dataset',workspace='factors',
        symbols=('600000.SH','688001.SH'),as_of='2025-01-03',universe_id='screen-missing',
        universe_version='1.0',factor_id='basic.return_20d')
    app=AppTest.from_file(str(Path('portfolio_app/local_app.py').resolve()),default_timeout=30)
    app.query_params.update(encode_route_query(build_workspace_state(context)))
    app.run()
    assert not app.exception
    assert any('筛选名单' in e.value for e in app.error)
    assert 'factor_research_id' not in app.session_state
