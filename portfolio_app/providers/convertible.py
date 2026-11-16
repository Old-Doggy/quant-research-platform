"""Sina CB observations: preserve expired bonds; no lifecycle simulation claim."""
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .base import ProviderBatch,ProviderError
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash


def validate_symbol(symbol):
    if not isinstance(symbol,str) or not re.fullmatch(r'(?:11\d{4}\.SH|12\d{4}\.SZ)',symbol):
        raise ValueError('需要明确沪深可转债代码')


def normalize_profile(raw,symbol):
    validate_symbol(symbol)
    if set(raw.columns)!={'item','value'} or raw['item'].duplicated().any():
        raise ValueError('转债资料字段无效或重复')
    data=dict(zip(raw['item'],raw['value']))
    if data.get('债券代码')!=symbol[-2:].lower()+symbol[:6] or '可转换' not in str(data.get('债券类型','')):
        raise ValueError('不是对应代码的可转债资料')
    face=float(data['债券面值（元）'])
    if not np.isfinite(face) or face<=0:
        raise ValueError('转债面值无效')
    def day(field):
        value=data.get(field)
        return None if value in (None,'','--') else _date(str(value))
    return dict(symbol=symbol,name=data['债券简称'],face_value=face,stock_symbol='unknown',
        list_date=day('上市日期'),maturity_date=day('到期日'),delist_date=day('摘牌日'),
        rating=data.get('信用等级'),profile_basis='latest_observation_not_historical_master')


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.current=None;self.cell=None;self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='tr': self.current=[]
        elif tag in ('td','th') and self.current is not None: self.cell=[]
        elif tag=='a': self.links.extend(value for key,value in attrs if key=='href')
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            if self.current is not None: self.current.append(''.join(self.cell).strip())
            self.cell=None
        elif tag=='tr' and self.current is not None:
            self.rows.append(self.current);self.current=None


def parse_conversion_page(html,symbol,*,fetched_at):
    validate_symbol(symbol)
    instant=datetime.fromisoformat(fetched_at)
    if instant.tzinfo is None: raise ValueError('转股价观察时间缺少时区')
    parser=_Tables();parser.feed(html)
    header=None;events=[]
    for cells in parser.rows:
        if {'公告日期','转股价格生效日期','转股价格（元）'}<=set(cells):
            header=cells;continue
        if header and len(cells)==len(header):
            row=dict(zip(header,cells))
            try:
                ann=_date(row['公告日期']);effective=_date(row['转股价格生效日期']);price=float(row['转股价格（元）'])
            except (ValueError,KeyError):
                raise ValueError('转股价日期或数值无效') from None
            if not np.isfinite(price) or price<=0 or ann>effective:
                raise ValueError('转股价生效时间或数值矛盾')
            event=dict(symbol=symbol,ann_date=ann,effective_date=effective,price=price,fetched_at=fetched_at,
                event_type='conversion_price',availability='forward_observed_only')
            event['event_id']='cb-event-'+identity_hash(event)
            events.append(event)
        elif header:
            header=None
    stocks=set()
    for link in parser.links:
        match=re.search(r'/realstock/company/(sh6\d{5}|sz[03]\d{5})/',link)
        if match:
            code=match[1];stocks.add(code[2:]+'.'+code[:2].upper())
    return dict(stock_symbol=next(iter(stocks)) if len(stocks)==1 else 'unknown',events=events)


def sdk_fetch(operation,symbol):
    validate_symbol(symbol)
    if operation not in {'daily','profile','conversion','quotes'}:
        raise ValueError('未知转债请求')
    with tempfile.TemporaryDirectory(prefix='quant-cb-') as directory:
        path=Path(directory)/'data.parquet'
        try:
            result=subprocess.run([sys.executable,'-m','portfolio_app.providers.convertible','--worker',operation,symbol,str(path)],
                capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        except subprocess.TimeoutExpired:
            raise ProviderError('network_timeout','转债来源请求超时',retryable=True) from None
        if result.returncode or not path.is_file() or path.stat().st_size>16*1024*1024:
            raise ProviderError('upstream_error','转债来源请求未完成',retryable=True)
        return pd.read_parquet(path)


class SinaConvertible:
    def __init__(self,*,transport=None): self.transport=transport or sdk_fetch

    def daily(self,symbol,*,start,end):
        validate_symbol(symbol);_date(start);_date(end)
        if start>end or (pd.Timestamp(end)-pd.Timestamp(start)).days>366:
            raise ValueError('转债单次观察不超过一年')
        raw=self.transport('daily',symbol)
        if not {'date','open','high','low','close','volume'}<=set(raw) or len(raw)>20000 or raw.columns.duplicated().any():
            raise ValueError('转债日线结构无效')
        frame=raw.rename(columns={'date':'trade_date'}).copy()
        frame['trade_date']=pd.to_datetime(frame.trade_date,errors='raise')
        if frame.trade_date.isna().any() or frame.trade_date.duplicated().any():
            raise ValueError('转债日线日期无效或重复')
        frame=frame.loc[frame.trade_date.between(pd.Timestamp(start),pd.Timestamp(end))].sort_values('trade_date').reset_index(drop=True)
        for field in ['open','high','low','close','volume']:
            frame[field]=pd.to_numeric(frame[field],errors='raise')
        if (not np.isfinite(frame[['open','high','low','close','volume']]).all().all()
                or frame[['open','high','low','close']].le(0).any().any() or frame.volume.lt(0).any()
                or not np.allclose(frame.volume,frame.volume.round(),atol=1e-6,rtol=0)
                or frame.high.lt(frame[['open','close','low']].max(axis=1)).any()
                or frame.low.gt(frame[['open','close','high']].min(axis=1)).any()):
            raise ValueError('转债价格或数量无效')
        frame['symbol']=symbol;frame['amount']=np.nan
        fetched=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        meta=dict(provider='sina',endpoint='cb_raw_daily',symbol=symbol,start=start,end=end,fetched_at=fetched,
            volume_unit='bonds',price_unit='CNY_per_bond',amount_unit='unavailable',research_ready=False,
            coverage='observed_rows_only',unit_evidence='2026-11-16 sh113052 Sina quantity / Tencent lots=10')
        meta['batch_id']='sina-cb-'+identity_hash(dict(symbol=symbol,raw=raw.to_json(orient='split',date_format='iso')))
        return ProviderBatch(frame,raw,meta,'unverified')

    def reference(self,symbol):
        validate_symbol(symbol)
        raw=self.transport('profile',symbol)
        master=normalize_profile(raw,symbol)
        fetched=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        html=self.transport('conversion',symbol).iloc[0]['html']
        parsed=parse_conversion_page(html,symbol,fetched_at=fetched)
        quote_html=self.transport('quotes',symbol).iloc[0]['html']
        quote_parsed=parse_conversion_page(quote_html,symbol,fetched_at=fetched)
        stocks={p['stock_symbol'] for p in (parsed,quote_parsed) if p['stock_symbol']!='unknown'}
        if len(stocks)>1: raise ValueError('转债资料正股代码矛盾')
        if parsed['stock_symbol']=='unknown': parsed['stock_symbol']=quote_parsed['stock_symbol']
        master['stock_symbol']=parsed['stock_symbol']
        raw=raw.copy();raw['conversion_html']=html;raw['quotes_html']=quote_html
        meta=dict(provider='sina',endpoint='cb_reference',symbol=symbol,fetched_at=fetched,
            master=master,events=parsed['events'],coverage='observed_only_not_full_event_history',research_ready=False)
        meta['batch_id']='sina-cb-reference-'+identity_hash(meta)
        return ProviderBatch(pd.DataFrame([master]),raw,meta,'unverified')


if __name__=='__main__' and len(sys.argv)==5 and sys.argv[1]=='--worker':
    _,_,operation,symbol,target=sys.argv
    code=symbol[-2:].lower()+symbol[:6]
    if operation in {'conversion','quotes'}:
        with urlopen(f'https://money.finance.sina.com.cn/bond/{operation}/{code}.html',timeout=20) as response:
            body=response.read(4*1024*1024+1)
        if len(body)>4*1024*1024: raise SystemExit(1)
        frame=pd.DataFrame([dict(html=body.decode('gb18030',errors='strict'))])
    else:
        import akshare as ak
        frame=ak.bond_cb_daily_sina(symbol=code) if operation=='daily' else ak.bond_cb_profile_sina(symbol=code)
    frame.to_parquet(target,index=False)
