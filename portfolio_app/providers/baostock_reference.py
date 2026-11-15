"""Small explicit BaoStock reference queries for the free daily path."""
from dataclasses import asdict
import pandas as pd

from .free_sdk import FreeDailyProvider
from .base import ProviderBatch, ProviderError
from ..instrument_master import Instrument, _date
from ..calendar_service import MarketCalendar
from ..snapshot_contracts import identity_hash


class BaoStockReference:
    def __init__(self, *, transport=None):
        self.provider = FreeDailyProvider('baostock',transport=transport)

    def instrument(self,symbol,*,observed_on):
        _date(observed_on)
        if not isinstance(symbol,str) or not symbol.endswith(('.SH','.SZ')) or len(symbol)!=9:
            raise ValueError('免费主表查询当前仅开放沪深A股')
        raw=self.provider._fetch(symbol,observed_on,observed_on,operation='baostock_master')
        required={'code','code_name','ipoDate','outDate','type','status'}
        expected=symbol[-2:].lower()+'.'+symbol[:6]
        if not required<=set(raw) or len(raw)!=1 or raw.code.iloc[0]!=expected or str(raw.type.iloc[0])!='1':
            raise ProviderError('invalid_response','BaoStock证券资料缺失、证券不符或不是股票')
        row=raw.iloc[0]
        code=symbol[:6]
        if symbol.endswith('.SH') and code.startswith('688'):
            subtype='star_a'
        elif symbol.endswith('.SH') and code.startswith('6'):
            subtype='main_a'
        elif symbol.endswith('.SZ') and code.startswith('3'):
            subtype='chinext_a'
        elif symbol.endswith('.SZ') and code.startswith('0'):
            subtype='main_a'
        else:
            raise ProviderError('unsupported_instrument','证券类别尚未核对')
        listed=_date(str(row.ipoDate))
        out=str(row.outDate).strip() if pd.notna(row.outDate) else ''
        delisted=_date(out) if out else None
        market='SSE' if symbol.endswith('.SH') else 'SZSE'
        instrument=Instrument(f'CN:{market}:{code}',symbol,str(row.code_name),market,'cn_stock',subtype,
            listed,delisted,'baostock',expected)
        batch_id='baostock-master-'+identity_hash(dict(observed_on=observed_on,raw=raw.to_json(orient='split')))
        return ProviderBatch(pd.DataFrame([asdict(instrument)]),raw,dict(provider='baostock',endpoint='stock_basic',
            observed_on=observed_on,batch_id=batch_id,scope='selected_security_only',
            source_url='http://www.baostock.com'), 'complete')

    def calendar(self,market,start,end,*,generation):
        if market not in {'SSE','SZSE'}:
            raise ValueError('免费日历当前仅开放沪深共同交易日')
        _date(start);_date(end)
        if start>end:
            raise ValueError('日历开始日期晚于结束日期')
        raw=self.provider._fetch('600000.SH',start,end,operation='baostock_calendar')
        if not {'calendar_date','is_trading_day'}<=set(raw) or not raw.is_trading_day.astype(str).isin({'0','1'}).all():
            raise ProviderError('invalid_response','BaoStock交易日历字段或状态无效')
        days=[]
        for row in raw.to_dict('records'):
            days.append((_date(str(row['calendar_date'])),str(row['is_trading_day'])=='1'))
        cal=MarketCalendar(market,'Asia/Shanghai','baostock.query_trade_dates',generation,tuple(sorted(days)))
        cal.sessions(start,end)
        batch_id='baostock-calendar-'+identity_hash(dict(market=market,raw=raw.to_json(orient='split')))
        return ProviderBatch(pd.DataFrame(cal.days,columns=['session','is_open']),raw,
            dict(provider='baostock',endpoint='trade_dates',market=market,batch_id=batch_id,
                calendar=cal.to_dict(),market_scope='SSE_SZSE_shared_sessions',source_url='http://www.baostock.com'),'complete')
