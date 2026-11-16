"""Tencent raw daily adapter with explicit board units and requested-session coverage."""
import json
import re
from threading import Lock
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

from .base import ProviderBatch, ProviderError
from ..data import normalise_market_frame, build_data_quality_report
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash
from ..provider_normalize import PREVIOUS_CLOSE_POLICY


class TencentProvider:
    def __init__(self, *, transport=None, min_interval=1.5):
        if min_interval < 0:
            raise ValueError('请求间隔不能为负')
        self._transport = transport or self._http
        self.min_interval = min_interval
        self._last_request = 0.
        self._lock = Lock()

    @staticmethod
    def _http(symbol, start, end):
        query = urlencode(dict(param=f'{symbol},day,{start},{end},640,'))
        with urlopen('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?' + query, timeout=20) as response:
            return json.load(response)

    def _request(self, symbol, start, end):
        failure = False
        with self._lock:
            delay = self.min_interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            try:
                result = self._transport(symbol, start, end)
            except Exception:
                failure, result = True, None
            finally:
                self._last_request = time.monotonic()
        if failure:
            raise ProviderError('network_error', '腾讯行情连接失败', retryable=True)
        if not isinstance(result, dict) or result.get('code') != 0 or not isinstance(result.get('data'), dict):
            raise ProviderError('invalid_response', '腾讯行情响应无效')
        data = result['data'].get(symbol)
        if not isinstance(data, dict) or not isinstance(data.get('day'), list) or not data['day']:
            raise ProviderError('raw_unavailable', '腾讯未返回原始日线；不使用复权数据替代')
        return data['day']

    def daily(self, symbol, *, sessions):
        if not isinstance(symbol, str) or not re.fullmatch(r'(?:6\d{5}\.SH|[03]\d{5}\.SZ|[489]\d{5}\.BJ)', symbol):
            raise ValueError('腾讯适配器只支持明确的A股代码')
        sessions = tuple(sessions)
        if not sessions or sessions != tuple(sorted(set(sessions))):
            raise ValueError('请提供有序且不重复的真实交易日')
        for session in sessions:
            _date(session)
        code, market = symbol.split('.')
        upstream_code = market.lower() + code
        parts = []
        capped = []
        for year in range(int(sessions[0][:4]), int(sessions[-1][:4]) + 1):
            start, end = max(sessions[0], f'{year}-01-01'), min(sessions[-1], f'{year}-12-31')
            rows = self._request(upstream_code, start, end)
            if len(rows) > 640 or any(not isinstance(row, list) or len(row) < 9 for row in rows):
                raise ProviderError('invalid_response', '腾讯日线字段或行数无效')
            if len(rows) == 640:
                capped.append(year)
            part = pd.DataFrame([[r[i] for i in (0,1,2,3,4,5,7,8)] for r in rows],
                columns=['trade_date','open','close','high','low','source_vol','source_turnover','source_amount'])
            part['request_year'] = year
            parts.append(part)
        raw = pd.concat(parts, ignore_index=True)
        labels = raw.trade_date.astype(str)
        dates = pd.to_datetime(labels, format='%Y-%m-%d', errors='coerce')
        if dates.isna().any() or not dates.dt.strftime('%Y-%m-%d').eq(labels).all():
            raise ProviderError('invalid_response', '腾讯日线日期无效')
        selected = raw.loc[labels.isin(sessions)].drop(columns='request_year').copy()
        for _, repeated in selected.loc[selected.trade_date.duplicated(False)].groupby('trade_date'):
            if len(repeated.drop_duplicates()) > 1:
                raise ProviderError('conflicting_rows', '腾讯重叠请求返回冲突日线')
        selected = selected.drop_duplicates('trade_date').sort_values('trade_date').reset_index(drop=True)
        multiplier = 1 if code.startswith('688') and market == 'SH' else 100
        for field in ('open','high','low','close','source_vol','source_amount','source_turnover'):
            values = pd.to_numeric(selected[field], errors='coerce')
            if (selected[field].notna() & values.isna()).any() or (values.notna() & ~np.isfinite(values)).any():
                raise ProviderError('invalid_values', '腾讯日线存在无效数值')
            selected[field] = values
        selected['vol'] = selected.source_vol * multiplier
        selected['amount'] = selected.source_amount * 10000.
        selected['turnover_rate'] = selected.source_turnover / 100.
        volume = selected.vol.dropna()
        if not np.allclose(volume, volume.round(), atol=1e-6, rtol=0):
            raise ProviderError('invalid_values', '腾讯成交量单位换算后不是整数股')
        positive = selected.vol.gt(0) & selected.amount.notna()
        average = selected.amount / selected.vol.where(selected.vol.gt(0))
        # Upstream amount is rounded to 0.01 ten-thousand CNY.
        tolerance = np.maximum(.02, 100. / selected.vol.where(selected.vol.gt(0)))
        if (positive & ((average < selected.low - tolerance) | (average > selected.high + tolerance))).any():
            raise ProviderError('unit_mismatch', '腾讯成交均价与当日价格范围不符，请核对单位')
        selected['ts_code'] = symbol
        frame = normalise_market_frame(selected) if not selected.empty else selected
        if not frame.empty and build_data_quality_report(frame)['status'] != '通过':
            raise ProviderError('invalid_values', '腾讯日线质量检查未通过')
        if not frame.empty:
            frame['volume'] = frame.vol
        frame['source_pre_close'] = np.nan
        frame['pre_close'] = np.nan
        frame.attrs['previous_close_policy'] = PREVIOUS_CLOSE_POLICY
        missing = sorted(set(sessions) - set(selected.trade_date))
        batch_id = 'tencent-daily-' + identity_hash(dict(symbol=symbol, sessions=sessions, raw=raw.to_json(orient='split')))
        frame.attrs['field_units'] = dict(price='CNY_per_share', volume='shares', amount='CNY',
            source_vol='shares' if multiplier == 1 else 'lots_100_shares', source_amount='ten_thousand_CNY', turnover_rate='fraction')
        frame.attrs['normalization'] = dict(profile='tencent.raw.star' if multiplier == 1 else 'tencent.raw.lots',
            version='1.0', batch_id=batch_id)
        frame.attrs['research_dataset'] = dict(dataset_id='tencent.a_daily_raw', version=batch_id, price_basis='raw', source_kind='provider')
        if 'return_contract' in frame.attrs:
            frame.attrs['return_contract']['price_basis'] = 'raw'
        return ProviderBatch(frame, raw, dict(provider='tencent', upstream='Tencent Finance', endpoint='newfqkline',
            symbol=symbol, batch_id=batch_id, requested_sessions=list(sessions), missing_sessions=missing,
            capped_request_years=capped, source_url='https://akshare.akfamily.xyz/data/stock/stock.html',
            adapter_reference='akshare/stock/quote/stock_hist_tx.py', live_coverage='unverified',
            research_ready=False, automatic_fallback=False), 'partial' if missing else 'complete')
