"""Dated reference batches; row coverage is separate from point-in-time evidence."""
import numpy as np
import pandas as pd
import re

from .base import ProviderBatch, ProviderError
from ..field_registry import TUSHARE_BASIC_FIELDS
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash
from ..data import normalise_market_frame, build_data_quality_report


class TushareReference:
    def __init__(self, provider):
        self.provider = provider

    def _daily(self, endpoint, session, expected_symbols, fields, *, doc_id, limit=6000):
        _date(session)
        expected = set(expected_symbols)
        if not expected or any(not isinstance(code, str) or not re.fullmatch(
                r'(?:[06]\d{5}\.SH|[03]\d{5}\.SZ|[489]\d{5}\.BJ)', code) for code in expected):
            raise ValueError('补充数据需要明确证券范围')
        params = dict(trade_date=session.replace('-', ''))
        cap = min(limit, self.provider.row_limit)
        raw = self.provider.query(endpoint, params, fields=','.join(fields))
        sharded = len(raw) >= cap
        if sharded:
            parts = []
            for code in sorted(expected):
                part = self.provider.query(endpoint, {**params, 'ts_code': code}, fields=','.join(fields))
                if len(part) >= cap:
                    raise ProviderError('truncated_response', '补充数据证券分片仍触及行数上限')
                if 'ts_code' not in part or not part.ts_code.eq(code).all():
                    raise ProviderError('invalid_response', '补充数据分片证券不符')
                parts.append(part)
            raw = pd.concat(parts, ignore_index=True)
        if not set(fields) <= set(raw):
            raise ProviderError('invalid_response', '补充数据缺少请求字段')
        if (not raw.trade_date.astype(str).eq(params['trade_date']).all()
                or raw.duplicated(['ts_code', 'trade_date']).any()):
            raise ProviderError('invalid_response', '补充数据日期不符或记录重复')
        frame = raw.loc[raw.ts_code.isin(expected)].copy().sort_values('ts_code').reset_index(drop=True)
        missing = sorted(expected - set(frame.ts_code))
        batch_id = f'tushare-{endpoint}-' + identity_hash(dict(session=session, raw=raw.to_json(orient='split')))
        metadata = dict(provider='tushare', endpoint=endpoint, batch_id=batch_id, session=session,
            source_url=f'https://tushare.pro/document/2?doc_id={doc_id}', sharded=sharded,
            expected_symbols=sorted(expected), missing_symbols=missing, pit_coverage='unverified',
            completeness_scope='requested_rows_only', normalization_version='1.0')
        frame['trade_date'] = pd.to_datetime(frame.trade_date, format='%Y%m%d')
        return frame, raw, metadata

    @staticmethod
    def _number(frame, field, *, required=False, positive=False, nonnegative=False):
        values = pd.to_numeric(frame[field], errors='coerce')
        invalid = frame[field].notna() & values.isna()
        invalid |= values.notna() & ~np.isfinite(values)
        if required:
            invalid |= values.isna()
        if positive:
            invalid |= values.le(0)
        if nonnegative:
            invalid |= values.lt(0)
        if invalid.any():
            raise ProviderError('invalid_values', f'补充字段{field}存在无效数值')
        return values

    @staticmethod
    def _batch(frame, raw, metadata, units):
        frame.attrs['field_units'] = units
        frame.attrs['normalization'] = dict(profile='tushare.' + metadata['endpoint'],
            version='1.0', batch_id=metadata['batch_id'], source_url=metadata['source_url'],
            missing_policy='preserve_missing')
        return ProviderBatch(frame, raw, metadata, 'partial' if metadata['missing_symbols'] else 'complete')

    def adjustment_factors(self, session, *, expected_symbols):
        frame, raw, metadata = self._daily('adj_factor', session, expected_symbols,
            ['ts_code', 'trade_date', 'adj_factor'], doc_id=28)
        frame['adj_factor'] = self._number(frame, 'adj_factor', required=True, positive=True)
        metadata.update(update_window='09:15–09:20 Asia/Shanghai', price_basis='factor_only',
                        row_limit_policy='conservative_threshold_then_security_shards')
        return self._batch(frame, raw, metadata, dict(adj_factor='ratio'))

    def daily_basic(self, session, *, expected_symbols):
        frame, raw, metadata = self._daily('daily_basic', session, expected_symbols,
            ['ts_code', 'trade_date', *TUSHARE_BASIC_FIELDS], doc_id=32)
        units = {}
        for field, (source_unit, unit, multiplier) in TUSHARE_BASIC_FIELDS.items():
            nonnegative = field in {'turnover_rate', 'turnover_rate_f', 'volume_ratio', 'dv_ratio',
                'dv_ttm', 'total_share', 'float_share', 'free_share', 'total_mv', 'circ_mv'}
            values = self._number(frame, field, required=field == 'close', positive=field == 'close',
                                  nonnegative=nonnegative)
            frame['source_' + field] = values
            frame[field] = values * multiplier
            frame[field + '_missing_reason'] = np.where(values.isna(), 'source_missing', '')
            units[field], units['source_' + field] = unit, source_unit
        metadata.update(update_window='15:00–17:00 Asia/Shanghai',
            financial_availability='source_dates_do_not_prove_historical_release_time')
        return self._batch(frame, raw, metadata, units)

    def price_limits(self, session, *, expected_symbols):
        frame, raw, metadata = self._daily('stk_limit', session, expected_symbols,
            ['ts_code', 'trade_date', 'pre_close', 'up_limit', 'down_limit'], doc_id=183, limit=5800)
        for field in ('pre_close', 'up_limit', 'down_limit'):
            frame[field] = self._number(frame, field, positive=True)
        if frame.up_limit.lt(frame.down_limit).any():
            raise ProviderError('invalid_values', '涨停价低于跌停价')
        unknown = frame[['up_limit', 'down_limit']].isna().any(axis=1)
        metadata.update(unresolved_symbols=sorted(frame.loc[unknown, 'ts_code']),
            update_window='09:00 Asia/Shanghai', unknown_limit_policy='require_dated_rule_evidence')
        batch = self._batch(frame, raw, metadata, {f: 'CNY_per_share' for f in ('pre_close', 'up_limit', 'down_limit')})
        return ProviderBatch(batch.frame, batch.raw, batch.metadata,
            'partial' if unknown.any() or metadata['missing_symbols'] else 'complete')

    def index_daily(self, symbol, *, sessions):
        if not isinstance(symbol, str) or not re.fullmatch(r'\d{6}\.(?:SH|SZ|CSI)', symbol):
            raise ValueError('基准需要明确指数代码，不按股票代码推断')
        sessions = tuple(sessions)
        if not sessions or sessions != tuple(sorted(set(sessions))):
            raise ValueError('指数查询需要按顺序提供不重复的真实交易日')
        fields = 'ts_code,trade_date,open,high,low,close,pre_close,vol,amount'
        parts = []
        missing = []
        for session in sessions:
            _date(session)
            part = self.provider.query('index_daily', dict(ts_code=symbol, trade_date=session.replace('-', '')), fields=fields)
            if (not set(fields.split(',')) <= set(part) or len(part) > 1
                    or not part.ts_code.eq(symbol).all()
                    or not part.trade_date.astype(str).eq(session.replace('-', '')).all()):
                raise ProviderError('invalid_response', '指数日线日期、代码或行数不符')
            if part.empty:
                missing.append(session)
            parts.append(part)
        raw = pd.concat(parts, ignore_index=True)
        frame = raw.copy()
        if not frame.empty:
            for field in ('open', 'high', 'low', 'close', 'pre_close'):
                frame[field] = self._number(frame, field, required=True, positive=True)
            for field in ('vol', 'amount'):
                frame[field] = self._number(frame, field, nonnegative=True)
            frame['source_vol'], frame['source_amount'] = frame.vol.copy(), frame.amount.copy()
            frame['amount'] = frame.amount * 1000.
            frame = normalise_market_frame(frame)
            if build_data_quality_report(frame)['status'] != '通过':
                raise ProviderError('invalid_values', '指数行情质量检查未通过')
        batch_id = 'tushare-index-' + identity_hash(dict(symbol=symbol, sessions=sessions, raw=raw.to_json(orient='split')))
        units = {f: 'index_points' for f in ('open','high','low','close','pre_close')}
        units.update(vol='source_lots', source_vol='source_lots', amount='CNY', source_amount='thousand_CNY')
        frame.attrs['field_units'] = units
        frame.attrs['normalization'] = dict(profile='tushare.index_daily', version='1.0', batch_id=batch_id)
        return ProviderBatch(frame, raw, dict(provider='tushare', endpoint='index_daily', batch_id=batch_id,
            symbol=symbol, requested_sessions=list(sessions), missing_sessions=missing,
            source_url='https://tushare.pro/document/2?doc_id=95', return_basis='unclassified_index',
            update_window='around 18:00 Asia/Shanghai; some indices next afternoon',
            volume_scope='source_index_constituents_not_whole_exchange', executable=False),
            'partial' if missing else 'complete')
