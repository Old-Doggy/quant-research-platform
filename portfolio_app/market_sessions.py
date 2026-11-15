"""Separate observed execution bars from explicitly carried suspension marks."""
from dataclasses import asdict
import math
from numbers import Real

import pandas as pd

from .research_manifest import semantic_hash


class MarketSessionError(ValueError):
    pass


def resolve_session_inputs(frames, calendar=None):
    declared = [f.attrs['session_calendar'] for f in frames.values() if 'session_calendar' in f.attrs]
    if calendar is None and declared:
        calendar = declared[0]
    if calendar is not None and any(c != calendar for c in declared):
        raise MarketSessionError('交易日历版本冲突')
    if calendar is not None and not calendar.can_align:
        raise MarketSessionError('交易日历尚未核验')
    if not frames:
        raise MarketSessionError('portfolio data is empty')
    prepared, statuses, volumes, execution_status = {}, {}, {}, {}
    has_status, has_volume = False, False
    for symbol, source in frames.items():
        frame = source.copy(deep=True)
        if not {'trade_date', 'open', 'high', 'low', 'close'} <= set(frame):
            raise MarketSessionError('行情缺少日期或价格字段')
        dates = pd.to_datetime(frame.trade_date, errors='coerce')
        if dates.isna().any() or dates.duplicated().any():
            raise MarketSessionError('行情日期无效或重复')
        frame['trade_date'] = dates
        frame = frame.sort_values('trade_date').reset_index(drop=True)
        labels = tuple(frame.trade_date.dt.strftime('%Y-%m-%d'))
        if calendar is not None and labels != calendar.sessions:
            raise MarketSessionError(f'{symbol}行情缺失或超出所选交易日历；不能把缺口当停牌')
        if 'tradability' in frame:
            has_status = True
            values = frame.tradability
            if not values.isin({'tradable', 'suspended', 'limit_up', 'limit_down', 'unknown'}).all():
                raise MarketSessionError('可交易状态字段无效')
            statuses[symbol] = dict(zip(labels, values))
        elif calendar is not None:
            statuses[symbol] = dict.fromkeys(labels, 'unknown')
            has_status = True
        else:
            statuses[symbol] = dict.fromkeys(labels, 'tradable')
        execution_status[symbol] = dict(zip(labels, frame.price_status)) if 'price_status' in frame else dict.fromkeys(labels, 'fresh')
        if not set(execution_status[symbol].values()) <= {'fresh', 'stale', 'missing'}:
            raise MarketSessionError('成交价格状态无效')
        frame['valuation_status'] = 'observed'
        previous = None
        for index, session in enumerate(labels):
            close = pd.to_numeric(pd.Series([frame.loc[index, 'close']]), errors='coerce').iloc[0]
            if pd.isna(close):
                if statuses[symbol][session] != 'suspended':
                    raise MarketSessionError('非停牌行情缺失；估值与成交价格不能自动补齐')
                if previous is None:
                    raise MarketSessionError('停牌首日缺少已知前收盘估值')
                if calendar is None:
                    raise MarketSessionError('停牌估值需要明确交易日历')
                frame.loc[index, ['open', 'high', 'low', 'close']] = previous
                frame.loc[index, 'valuation_status'] = 'carried_suspension'
                execution_status[symbol][session] = 'stale'
            else:
                previous = float(close)
        if 'volume' in frame:
            has_volume = True
            normalized = {}
            for session, raw in zip(labels, frame.volume):
                if isinstance(raw, bool) or not isinstance(raw, Real) or not math.isfinite(raw) or raw < 0 or int(raw) != raw:
                    raise MarketSessionError('成交量必须为非负整数，缺失不能当0')
                normalized[session] = int(raw)
            volumes[symbol] = normalized
        elif calendar is not None:
            has_volume = True
            volumes[symbol] = {}
        prepared[symbol] = frame
    metadata = dict(status='explicit' if calendar is not None else 'observed_sessions',
        calendar=asdict(calendar) if calendar is not None else None,
        tradability='declared' if has_status else 'legacy_assumed',
        capacity='declared' if has_volume else 'legacy_unbounded',
        suspended_marks='previous_known_close_only')
    metadata['fingerprint'] = semantic_hash(metadata)
    return prepared, statuses if has_status else None, volumes if has_volume else None, execution_status, metadata
