"""Observed conversion-price facts require publication and effective dates."""
from datetime import datetime
import math
from zoneinfo import ZoneInfo

from .instrument_master import _date
from .providers.convertible import validate_symbol


def conversion_price_asof(events, *, session, as_of):
    _date(session);_date(as_of)
    if session>as_of:
        raise ValueError('估值日期不能晚于信息日期')
    candidates=[];symbols=set()
    for event in events:
        validate_symbol(event['symbol']);symbols.add(event['symbol'])
        if len(symbols)>1: raise ValueError('转股价不能混合不同证券')
        _date(event['ann_date']);_date(event['effective_date'])
        price=event['price']
        if (isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price)
                or price<=0 or event['ann_date']>event['effective_date']):
            raise ValueError('转股价日期或数值矛盾')
        instant=datetime.fromisoformat(event['fetched_at'])
        if instant.tzinfo is None: raise ValueError('转股价观察时间缺少时区')
        observed=instant.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        if event['effective_date']<=session and max(event['ann_date'],observed)<as_of:
            candidates.append(event)
    if not candidates:
        return None
    latest=max(e['effective_date'] for e in candidates)
    selected=[e for e in candidates if e['effective_date']==latest]
    if len({e['price'] for e in selected})!=1:
        raise ValueError('同一生效日转股价冲突')
    return dict(selected[0])


def conversion_premium(*,bond_price,stock_price,conversion_price,face_value):
    values=[bond_price,stock_price,conversion_price,face_value]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in values):
        raise ValueError('转股溢价需要同日、正且有限的价格与面值')
    return bond_price/(face_value*stock_price/conversion_price)-1
