"""Browse durable行情 versions without changing any research submission."""
from dataclasses import replace

import streamlit as st

from .market_query import query_daily
from .snapshot_store import SnapshotStore
from .state_paths import state_root
from .workspace_router import build_workspace_state, encode_route_query


def browsing_context(context, manifest, symbol):
    scope=manifest['range']
    if symbol not in scope['symbols']:
        raise ValueError('证券不在该行情版本中')
    return replace(context,dataset_id=manifest['dataset_id'],workspace='watch',symbol=symbol,symbols=(),
        as_of=scope['end'],date_start=scope['start'],date_end=scope['end'],
        snapshot_id=manifest['snapshot_id'],dataset_generation=manifest['generation'],
        price_basis='raw',return_definition='price_return_v1',strategy_id=None,factor_id=None,
        factor_version=None,universe_id=None,universe_version=None)


def render_market_watch(route, dependencies):
    if dependencies['PUBLIC_MODE']:
        return False
    store=SnapshotStore(state_root()/'market_service')
    explicit=route.context.snapshot_id is not None and (store.directory/(route.context.snapshot_id+'.json')).exists()
    available=any(store.directory.glob('snapshot-*.json'))
    if not available and not explicit:
        return False
    marker=(route.context.dataset_id,route.context.snapshot_id)
    if explicit and st.session_state.get('_market_watch_route')!=marker:
        st.session_state['_watch_view_preference']='更新行情'
        st.session_state['watch_view']='更新行情'
        st.session_state['market_watch_follow']=False
        st.session_state['market_watch_version']=route.context.snapshot_id
        st.session_state['market_watch_dataset']=route.context.dataset_id
        st.session_state['_market_watch_route']=marker
    if 'watch_view' not in st.session_state:
        st.session_state['watch_view']=st.session_state.get('_watch_view_preference','现有数据')
    mode=st.segmented_control('行情视图',['现有数据','更新行情'],key='watch_view',default='现有数据')
    st.session_state['_watch_view_preference']=mode
    if mode!='更新行情':
        return False
    manifests=[]
    for path in store.directory.glob('snapshot-*.json'):
        try:
            manifests.append(store.open(path.stem))
        except (ValueError,OSError,KeyError):
            continue
    if not manifests:
        st.error('行情版本校验失败，请在数据中心检查保留批次。')
        return True
    manifests.sort(key=lambda m:(m['dataset_id'],m['generation']),reverse=True)
    datasets=sorted({m['dataset_id'] for m in manifests})
    if route.context.dataset_id in datasets and 'market_watch_dataset' not in st.session_state:
        st.session_state['market_watch_dataset']=route.context.dataset_id
    dataset=st.selectbox('行情数据集',datasets,key='market_watch_dataset',filter_mode=None)
    versions={m['snapshot_id']:m for m in manifests if m['dataset_id']==dataset}
    left,right=st.columns([2,1])
    follow=right.checkbox('跟随当前行情版本',value=not explicit,key='market_watch_follow')
    try:
        current=store.current(dataset)
    except (ValueError,OSError,KeyError):
        st.error('当前行情索引校验失败，请到数据中心恢复。')
        return True
    if follow:
        if current is None:
            st.info('该数据集还没有当前版本。')
            return True
        st.session_state['market_watch_version']=current['snapshot_id']
    elif st.session_state.get('market_watch_version') not in versions:
        st.session_state['market_watch_version']=next(iter(versions))
    chosen=left.selectbox('行情版本',list(versions),key='market_watch_version',disabled=follow,
        format_func=lambda key:f"v{versions[key]['generation']} · {versions[key]['range']['start']}—{versions[key]['range']['end']}",filter_mode=None)
    manifest=versions[chosen]
    if current and current['snapshot_id']!=chosen:
        st.info(f"当前行情已更新至v{current['generation']}；这里保留所选v{manifest['generation']}。")
    if st.button('刷新行情版本',key='market_watch_refresh'):
        st.rerun()
    scope=manifest['range']
    key='market_watch_symbol_'+chosen
    if key not in st.session_state and route.context.symbol in scope['symbols']:
        st.session_state[key]=route.context.symbol
    names={r['symbol']:r['name'] for r in manifest['instrument_master']['records']}
    symbol=st.selectbox('证券',scope['symbols'],key=key,filter_mode=None,
        format_func=lambda code:f'{code} · {names.get(code, "")}')
    try:
        frame=query_daily(store,chosen,symbols=[symbol],start=scope['start'],end=scope['end'],
            columns=['symbol','ts_code','trade_date','open','high','low','close','vol','volume','amount','pre_close'])
    except (ValueError,OSError,KeyError):
        st.error('该版行情批次缺失或校验失败，请在数据中心检查。')
        return True
    from .research_dataset import record_context
    frame.attrs['research_dataset'].update(source_kind='provider_snapshot',version=f"v{manifest['generation']}",
        snapshot_id=chosen,dataset_generation=manifest['generation'])
    record_context(st.session_state,'watch',frame,symbol=symbol)
    context=browsing_context(route.context,manifest,symbol)
    query=encode_route_query(build_workspace_state(context,'watch'))
    if dict(st.query_params)!=query:
        st.query_params.from_dict(query)
    # A URL created by this view must not turn follow mode into pinned mode next rerun.
    st.session_state['_market_watch_route']=(context.dataset_id,chosen)
    st.caption('已核对原始日线 · 成交量：股 · 成交额：元 · 公司行为核验完成后开放研究')
    with st.popover('指标与图层'):
        config,_,panels=dependencies['build_indicator_config_controls']()
    dependencies['_render_pure_stock_view'](frame,symbol=symbol,name=names.get(symbol,''),
        source_label=f"{manifest['provider']} / {manifest['comparison_provider']} 核对 · v{manifest['generation']}",
        price_mode='raw',price_unit='元/股',volume_unit='股',indicator_config=config,panel_count=len(panels))
    return True
