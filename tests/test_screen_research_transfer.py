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
