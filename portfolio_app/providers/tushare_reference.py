"""Dated reference batches; row coverage is separate from point-in-time evidence."""
import numpy as np
import pandas as pd
import re

from .base import ProviderBatch, ProviderError
from ..field_registry import TUSHARE_BASIC_FIELDS
from ..instrument_master import _date
from ..snapshot_contracts import identity_hash


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
