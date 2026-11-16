"""A dated price/volume screen; fixed snapshots never become historical dynamic pools."""
import math
import operator

from .instrument_master import _date
from .market_overview import market_overview
from .snapshot_contracts import identity_hash


SCREEN_FIELDS = {'close':'收盘价（元）','price_change':'当日价格涨跌幅',
    'amount':'成交额（元）','volume':'成交量（股）'}
OPERATORS = {'ge':operator.ge,'le':operator.le,'gt':operator.gt,'lt':operator.lt}


def validate_screen(config):
    if not isinstance(config,dict) or set(config)!={'schema','session','snapshot_id','universe_policy','conditions'}:
        raise ValueError('筛选配置字段不完整或包含未知字段')
    if config['schema']!='daily-screener.v1' or config['universe_policy']!='snapshot_listed_on_session':
        raise ValueError('筛选版本或股票池时点规则未知')
    _date(config['session'])
    if not isinstance(config['snapshot_id'],str) or not config['snapshot_id']:
        raise ValueError('筛选需要固定行情版本')
    conditions=config['conditions']
    if not isinstance(conditions,list) or len(conditions)>12:
        raise ValueError('筛选最多12项条件')
    for condition in conditions:
        if not isinstance(condition,dict) or set(condition)!={'field','op','value','missing'}:
            raise ValueError('筛选条件字段无效')
        if condition['field'] not in SCREEN_FIELDS or condition['op'] not in OPERATORS:
            raise ValueError('字段尚未具备可验收的数据时点或运算不支持')
        if condition['missing'] not in ('exclude','keep'):
            raise ValueError('筛选缺值规则未知')
        value=condition['value']
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError('筛选阈值必须是有限数值')
    return config


def screen_daily(frame, *, manifest, config):
    validate_screen(config)
    if config['snapshot_id']!=manifest['snapshot_id']:
        raise ValueError('筛选的固定版本与行情不一致')
    report=market_overview(frame,manifest=manifest,session=config['session'])
    selected=report['details'].copy()
    steps=[]
    for condition in config['conditions']:
        values=selected[condition['field']]
        missing=values.isna()
        keep=OPERATORS[condition['op']](values,condition['value']).fillna(False)
        keep=keep | missing if condition['missing']=='keep' else keep & ~missing
        before=len(selected)
        selected=selected.loc[keep].copy()
        steps.append(dict(condition=dict(condition),before=before,after=len(selected),missing=int(missing.sum())))
    selected=selected.sort_values('symbol').reset_index(drop=True)
    identity=dict(config=config,symbols=selected.symbol.tolist(),definition='dated-price-volume-screen.v1')
    return dict(screen_id='screen-'+identity_hash(identity),snapshot_id=manifest['snapshot_id'],
        dataset_id=manifest['dataset_id'],generation=manifest['generation'],session=config['session'],
        universe_policy=config['universe_policy'],config=config,steps=steps,initial=report['expected'],
        symbols=selected.symbol.tolist(),details=selected,
        research_ready=manifest.get('research_capabilities',{}).get('corporate_action_backtest') is True,
        pool_semantics='fixed_members_selected_on_session')
