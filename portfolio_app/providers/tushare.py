"""Tushare HTTP adapter; credentials and raw upstream error text stay private."""
import json
import os
from threading import Lock
import time
from urllib.request import Request, urlopen

import pandas as pd
from dataclasses import asdict

from .base import ProviderError, ProviderBatch
from ..provider_normalize import normalize_daily
from ..instrument_master import _date
from ..instrument_master import Instrument
from ..calendar_service import MarketCalendar
from ..snapshot_contracts import identity_hash


DAILY_FIELDS = 'ts_code,trade_date,open,high,low,close,pre_close,vol,amount'


class TushareProvider:
    def __init__(self, *, token=None, transport=None, row_limit=6000, min_interval=1.3):
        self._token = (os.environ.get('TUSHARE_TOKEN', '') if token is None else token).strip()
        self._transport = transport or self._http
        if type(row_limit) is not int or row_limit < 1 or min_interval < 0:
            raise ValueError('invalid provider limits')
        self.row_limit, self.min_interval = row_limit, min_interval
        self._lock, self._last_request = Lock(), 0.

    def __repr__(self):
        return f'TushareProvider(credentials_configured={bool(self._token)})'

    def _http(self, endpoint, params, *, fields):
        body = json.dumps(dict(api_name=endpoint, token=self._token, params=params, fields=fields)).encode()
        request = Request('https://api.waditu.com', data=body,
            headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def query(self, endpoint, params, *, fields=''):
        if not self._token:
            raise ProviderError('credentials_missing', '尚未配置Tushare token')
        failure = None
        with self._lock:
            delay = self.min_interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            try:
                result = self._transport(endpoint, dict(params), fields=fields)
            except Exception:
                # Never retain a request-bearing exception as a chained cause.
                failure = ProviderError('network_error', '数据源连接失败，请稍后重试', retryable=True)
                result = None
            finally:
                self._last_request = time.monotonic()
        if failure:
            raise failure
        if not isinstance(result, dict):
            raise ProviderError('invalid_response', '数据源响应格式无效')
        if result.get('code') != 0:
            message = str(result.get('msg', '')).lower()
            if any(k in message for k in ('每分钟', '频次', '访问频率', 'rate limit')):
                raise ProviderError('rate_limited', '数据源限流，请稍后重试', retryable=True)
            if 'token' in message and any(k in message for k in ('无效', '不对', '失效', 'invalid')):
                raise ProviderError('credentials_invalid', 'Tushare凭据无效，请检查本机配置')
            if any(k in message for k in ('权限', '积分', 'permission')):
                raise ProviderError('permission_denied', '当前账号没有此接口权限')
            raise ProviderError('upstream_rejected', '数据源未接受请求，请核对权限和参数')
        data = result.get('data')
        if (not isinstance(data, dict) or not isinstance(data.get('fields'), list)
                or not isinstance(data.get('items'), list)
                or any(not isinstance(field, str) or not field for field in data['fields'])
                or len(data['fields']) != len(set(data['fields']))
                or any(not isinstance(row, list) or len(row) != len(data['fields']) for row in data['items'])):
            raise ProviderError('invalid_response', '数据源响应字段或行结构无效')
        return pd.DataFrame(data['items'], columns=data['fields'])

    def daily(self, session, *, expected_symbols, suspended_symbols=(), universe_scope='selection'):
        _date(session)
        expected = set(expected_symbols)
        suspended = set(suspended_symbols)
        if not expected or not suspended <= expected or universe_scope not in {'selection', 'master'}:
            raise ValueError('每日更新需要明确证券范围及已核验停牌名单')
        params = dict(trade_date=session.replace('-', ''))
        raw = self.query('daily', params, fields=DAILY_FIELDS)
        sharded = len(raw) >= self.row_limit
        if sharded:
            parts = []
            for symbol in sorted(expected - suspended):
                part = self.query('daily', {**params, 'ts_code': symbol}, fields=DAILY_FIELDS)
                if len(part) >= self.row_limit or ('ts_code' in part and not part.ts_code.eq(symbol).all()):
                    raise ProviderError('truncated_response', '证券分片仍触及上限或证券不符，不能登记完整')
                parts.append(part)
            raw = pd.concat(parts, ignore_index=True) if parts else raw.iloc[:0]
        if not {'ts_code', 'trade_date'} <= set(raw):
            raise ProviderError('invalid_response', '日线响应缺少证券和日期')
        if not raw.trade_date.astype(str).eq(params['trade_date']).all():
            raise ProviderError('invalid_response', '日线响应包含其他日期')
        unexpected = sorted(set(raw.ts_code) - expected)
        if unexpected and universe_scope == 'master':
            raise ProviderError('universe_mismatch', '日线响应证券与主表不符，请先更新证券主表')
        if set(raw.ts_code) & suspended:
            raise ProviderError('status_conflict', '已核验全天停牌证券仍有日线，请核对状态来源')
        selected = raw.loc[raw.ts_code.isin(expected)].copy()
        missing = sorted(expected - suspended - set(selected.ts_code))
        batch_id = 'tushare-daily-' + identity_hash(dict(session=session, raw=raw.to_json(orient='split')))
        frame = normalize_daily(selected, profile='tushare_a_daily', batch_id=batch_id) if len(selected) else selected.copy()
        metadata = dict(provider='tushare', endpoint='daily', session=session, batch_id=batch_id,
            source_url='https://tushare.pro/document/2?doc_id=27', sharded=sharded,
            expected_symbols=sorted(expected), suspended_symbols=sorted(suspended), missing_symbols=missing,
            universe_scope=universe_scope, excluded_symbols=unexpected)
        return ProviderBatch(frame, raw, metadata, 'partial' if missing else 'complete')

    def instrument_master(self, *, observed_on):
        _date(observed_on)
        parts = []
        for status in ('L', 'D', 'P'):
            frame = self.query('stock_basic', dict(list_status=status),
                fields='ts_code,name,exchange,market,list_date,delist_date')
            if len(frame) >= self.row_limit:
                shards = []
                for exchange in ('SSE', 'SZSE', 'BSE'):
                    part = self.query('stock_basic', dict(list_status=status, exchange=exchange),
                        fields='ts_code,name,exchange,market,list_date,delist_date')
                    if len(part) >= self.row_limit:
                        raise ProviderError('truncated_response', '证券主表交易所分片仍达上限，未登记完整')
                    if 'exchange' not in part or not part.exchange.eq(exchange).all():
                        raise ProviderError('invalid_response', '证券主表交易所分片返回市场不符')
                    shards.append(part)
                frame = pd.concat(shards, ignore_index=True)
            parts.append(frame)
        raw = pd.concat(parts, ignore_index=True)
        if raw.empty:
            raise ProviderError('empty_response', '证券主表为空，未更新本地记录')
        expected = {'ts_code', 'name', 'exchange', 'market', 'list_date', 'delist_date'}
        if not expected <= set(raw) or raw.ts_code.duplicated().any():
            raise ProviderError('invalid_response', '证券主表字段缺失或代码重复')
        rows = []
        categories = {'主板': 'main_a', '科创板': 'star_a', '创业板': 'chinext_a', '北交所': 'bse_a'}
        for record in raw.to_dict('records'):
            if record['market'] not in categories:
                raise ProviderError('unsupported_instrument', '主表包含尚未支持的证券类别')
            symbol = record['ts_code']
            listing = pd.to_datetime(str(record['list_date']), format='%Y%m%d', errors='coerce')
            delist_value = record['delist_date']
            delisted = (pd.to_datetime(str(delist_value), format='%Y%m%d', errors='coerce')
                        if pd.notna(delist_value) and str(delist_value).strip() else None)
            if pd.isna(listing) or (delisted is not None and pd.isna(delisted)):
                raise ProviderError('invalid_response', '主表上市或退市日期无效')
            instrument = Instrument(instrument_id=f"CN:{record['exchange']}:{symbol.split('.')[0]}",
                symbol=symbol, name=record['name'], market=record['exchange'], asset_type='cn_stock',
                subtype=categories[record['market']], listed_on=listing.strftime('%Y-%m-%d'),
                delisted_on=delisted.strftime('%Y-%m-%d') if delisted is not None else None,
                provider='tushare', provider_code=symbol)
            rows.append(asdict(instrument))
        batch_id = 'tushare-master-' + identity_hash(dict(observed_on=observed_on, rows=rows))
        return ProviderBatch(pd.DataFrame(rows), raw,
            dict(provider='tushare', endpoint='stock_basic', batch_id=batch_id, observed_on=observed_on,
                 included_statuses=['L', 'D', 'P'], source_url='https://tushare.pro/document/2?doc_id=25'), 'complete')

    def calendar(self, market, start, end, *, generation):
        batch = self.calendar_batch(market, start, end, generation=generation)
        return MarketCalendar.from_tushare(batch.raw, market=market, source='tushare.trade_cal', generation=generation)

    def calendar_batch(self, market, start, end, *, generation):
        _date(start)
        _date(end)
        if start > end:
            raise ValueError('日历开始日期不能晚于结束日期')
        raw = self.query('trade_cal', dict(exchange=market, start_date=start.replace('-', ''), end_date=end.replace('-', '')),
            fields='exchange,cal_date,is_open,pretrade_date')
        if len(raw) >= self.row_limit:
            raise ProviderError('truncated_response', '交易日历达到接口上限，请缩小日期区间')
        result = MarketCalendar.from_tushare(raw, market=market, source='tushare.trade_cal', generation=generation)
        result.sessions(start, end)  # Require requested edges, not just contiguous returned rows.
        frame = pd.DataFrame(result.days, columns=['session', 'is_open'])
        frame['market'] = market
        return ProviderBatch(frame, raw, dict(provider='tushare', endpoint='trade_cal', market=market,
            batch_id=result.fingerprint, calendar=result.to_dict(),
            source_url='https://tushare.pro/document/2?doc_id=26'), 'complete')
