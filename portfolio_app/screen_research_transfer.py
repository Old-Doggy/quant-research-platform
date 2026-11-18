"""Move a dated, rechecked fixed pool into research without weakening input gates."""
from .market_query import query_daily
from .research_context import ResearchContext
from .research_integrity import audit_research_input
from .screener import screen_daily
from .snapshot_contracts import identity_hash
from .workspace_router import build_workspace_state, encode_route_query


def prepare_screen_research(store, result, session, *, target):
    if target not in {'factors','strategy'} or not result.get('symbols'):
        raise ValueError('请选择非空名单及研究工作区')
    manifest=store.open(result['snapshot_id'])
    if manifest.get('research_capabilities',{}).get('corporate_action_backtest') is not True:
        raise ValueError('此快照仅供浏览，公司行为、交易状态与制度尚未核验')
    scope=manifest['range']
    # Recompute the receipt from its fixed snapshot. Never trust a UI flag or list.
    fields=['symbol','ts_code','trade_date','open','high','low','close','volume','amount','pre_close']
    frame=query_daily(store,result['snapshot_id'],symbols=scope['symbols'],start=scope['start'],
        end=result['session'],columns=fields)
    checked=screen_daily(frame,manifest=manifest,config=result['config'])
    if (checked['screen_id']!=result['screen_id'] or checked['symbols']!=result['symbols']
            or checked['session']!=result['session']):
        raise ValueError('筛选名单与固定行情版本不一致，请重新筛选')
    owned=frame.loc[frame.symbol.isin(checked['symbols'])].copy(deep=True)
    # Provider volume is already normalized to shares; factor inputs use vol.
    owned['vol']=owned['volume'].copy()
    audit_research_input(owned)
    context=ResearchContext(dataset_id=manifest['dataset_id'],workspace=target,
        symbol=checked['symbols'][0] if len(checked['symbols'])==1 else None,
        symbols=tuple(checked['symbols']) if len(checked['symbols'])>1 else (),
        as_of=checked['session'],date_start=scope['start'],date_end=checked['session'],
        snapshot_id=result['snapshot_id'],dataset_generation=manifest['generation'],price_basis='raw',
        return_definition='price_return_v1',universe_id=checked['screen_id'],universe_version='1.0',
        factor_id='basic.return_20d' if target=='factors' else None,
        strategy_id='trend' if target=='strategy' else None)
    route=encode_route_query(build_workspace_state(context,target))
    selection=dict(screen_id=checked['screen_id'],selected_on=checked['session'],
        symbols=list(checked['symbols']),semantics='fixed_members_selected_on_session',
        history_policy='diagnostic_history_through_selection_date_not_historical_stock_selection')
    owned.attrs['screen_selection']=selection
    owned.attrs['research_dataset']['selection_id']=identity_hash(selection)
    # Commit session state only after every check and route validation succeeds.
    session['_registered_research_dataset']=owned
    session['_use_registered_research_dataset']=True
    return route


def screen_input_matches(session, context):
    """A reopened fixed-pool link cannot silently run the demo or another pool."""
    frame=session.get('_registered_research_dataset')
    if not session.get('_use_registered_research_dataset') or frame is None:
        return False
    selection=frame.attrs.get('screen_selection',{})
    metadata=frame.attrs.get('research_dataset',{})
    return (selection.get('screen_id')==context.universe_id
        and selection.get('selected_on')==str(context.as_of)
        and metadata.get('dataset_id')==context.dataset_id
        and metadata.get('snapshot_id')==context.snapshot_id
        and metadata.get('selection_id')==identity_hash(selection)
        and sorted(frame.symbol.unique())==sorted(context.symbols or (context.symbol,)))
