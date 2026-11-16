"""ETF raw daily prices: bounded optional SDK, explicit fund-unit evidence."""
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .base import ProviderBatch,ProviderError
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash


def sdk_daily(symbol):
    if find_spec('akshare') is None:
        raise ProviderError('dependency_missing','请安装可选采集组件AKShare')
    with tempfile.TemporaryDirectory(prefix='quant-etf-') as directory:
        target=Path(directory)/'daily.parquet'
        try:
            result=subprocess.run([sys.executable,'-m','portfolio_app.providers.etf','--worker',symbol,str(target)],
                capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        except subprocess.TimeoutExpired:
            raise ProviderError('network_timeout','ETF来源请求超时',retryable=True) from None
        if result.returncode or not target.is_file():
            raise ProviderError('upstream_error','ETF来源请求未完成',retryable=True)
        if target.stat().st_size>16*1024*1024:
            raise ValueError('ETF响应超出预算')
        return pd.read_parquet(target)


class SinaETF:
    def __init__(self,*,transport=None):
        self.transport=transport

    def daily(self,symbol,*,start,end):
        if not isinstance(symbol,str) or not re.fullmatch(r'(?:5\d{5}\.SH|15\d{4}\.SZ)',symbol):
            raise ValueError('请提供明确沪深场内基金代码')
        _date(start);_date(end)
        if start>end or (pd.Timestamp(end)-pd.Timestamp(start)).days>366:
            raise ValueError('ETF单次观察范围不超过一年')
        raw=self.transport(symbol=symbol) if self.transport else sdk_daily(symbol)
        if not isinstance(raw,pd.DataFrame) or len(raw)>20000 or raw.columns.duplicated().any():
            raise ValueError('ETF来源表结构或行数无效')
        if not {'date','open','high','low','close','volume'}<=set(raw):
            raise ValueError('ETF来源缺少必需字段')
        frame=raw.rename(columns={'date':'trade_date'}).copy()
        dates=pd.to_datetime(frame.trade_date,errors='raise')
        if dates.isna().any() or dates.duplicated().any():
            raise ValueError('ETF日期缺失或重复')
        frame['trade_date']=dates
        frame=frame.loc[dates.between(pd.Timestamp(start),pd.Timestamp(end))].sort_values('trade_date').reset_index(drop=True)
        if 'amount' not in frame: frame['amount']=np.nan
        for field in ['open','high','low','close','volume','amount']:
            numbers=pd.to_numeric(frame[field],errors='raise')
            if (numbers.notna() & ~np.isfinite(numbers)).any():
                raise ValueError('ETF数值不是有限值')
            frame[field]=numbers
        if (frame[['open','high','low','close','volume']].isna().any().any()
                or frame[['open','high','low','close']].le(0).any().any() or frame.volume.lt(0).any()
                or frame.amount.lt(0).any() or not np.allclose(frame.volume,frame.volume.round(),atol=1e-6,rtol=0)
                or frame.high.lt(frame[['open','close','low']].max(axis=1)).any()
                or frame.low.gt(frame[['open','close','high']].min(axis=1)).any()):
            raise ValueError('ETF价量范围无效')
        average=frame.amount/frame.volume.where(frame.volume.gt(0))
        precision=1./frame.volume.where(frame.volume.gt(0))
        if ((average < frame.low-precision) | (average > frame.high+precision)).any():
            raise ValueError('ETF量额单位与日内价格不符')
        frame['symbol']=symbol
        frame['source_volume']=frame.volume
        frame['source_amount']=frame.amount
        metadata=dict(provider='sina',endpoint='etf_raw_daily',symbol=symbol,start=start,end=end,
            fetched_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),volume_unit='fund_units',amount_unit='CNY',
            coverage='observed_rows_only',price_basis='raw',research_ready=False,
            category_verified=False,event_coverage='unverified',nav_coverage='unavailable',
            missing_amount_rows=int(frame.amount.isna().sum()),
            unit_evidence='2026-11-16 real 510300/511010/518880 amount-volume-price; Tencent lots rounded comparison',
            source_url=f'https://finance.sina.com.cn/realstock/company/{symbol[-2:].lower()+symbol[:6]}/hisdata_klc2/klc_kl.js')
        metadata['batch_id']='sina-etf-'+identity_hash(dict(symbol=symbol,start=start,end=end,raw=raw.to_json(orient='split',date_format='iso')))
        return ProviderBatch(frame,raw,metadata,'unverified')


if __name__=='__main__' and len(sys.argv)==4 and sys.argv[1]=='--worker':
    import akshare as ak
    symbol=sys.argv[2]
    ak.fund_etf_hist_sina(symbol=symbol[-2:].lower()+symbol[:6]).to_parquet(sys.argv[3],index=False)
