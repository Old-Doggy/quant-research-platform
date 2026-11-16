"""Daily breadth for a pinned universe; unknown observations keep their denominator."""
import numpy as np
import pandas as pd

from .instrument_master import _date
from .calendar_service import MarketCalendar


def overview_sessions(manifest):
    """Use the pinned calendars for the selected securities, never weekdays."""
    scope = manifest['range']
    master = {r['symbol']: r for r in manifest['instrument_master']['records']}
    if set(scope['symbols']) - set(master):
        raise ValueError('概览证券主表不完整')
    markets = {master[s]['market'] for s in scope['symbols']}
    sessions = set()
    for market in markets:
        raw = manifest.get('calendars', {}).get(market)
        if not raw or raw.get('schema_version') != 'market-calendar.v1':
            raise ValueError('概览缺少对应市场日历')
        calendar = MarketCalendar(**{k: v for k, v in raw.items() if k != 'schema_version'})
        if calendar.market != market:
            raise ValueError('概览日历市场不一致')
        sessions.update(calendar.sessions(scope['start'], scope['end']))
    return sorted(sessions)


def market_overview(frame, *, manifest, session, industry=None):
    _date(session)
    scope = manifest['range']
    if not scope['start'] <= session <= scope['end']:
        raise ValueError('概览日期超出行情版本范围')
    if session not in overview_sessions(manifest):
        raise ValueError('概览日期不是已核验交易日')
    units = frame.attrs.get('field_units', {})
    if any(units.get(k) != v for k, v in dict(price='CNY_per_share', volume='shares', amount='CNY').items()):
        raise ValueError('概览缺少已归一的价量单位')
    if frame.attrs.get('research_dataset', {}).get('price_basis') != 'raw':
        raise ValueError('概览仅接受原始日线价格')
    required = {'symbol', 'trade_date', 'close', 'pre_close', 'amount', 'volume'}
    if not required <= set(frame):
        raise ValueError('概览缺少价格基准、量额或证券日期字段')
    data = frame.copy(deep=True)
    data['trade_date'] = pd.to_datetime(data.trade_date, errors='raise')
    if (data.trade_date.dt.tz is not None or data.trade_date.isna().any()
            or not data.trade_date.eq(data.trade_date.dt.normalize()).all()
            or data.duplicated(['symbol', 'trade_date']).any()):
        raise ValueError('概览行情日期缺失或重复')
    if set(data.symbol) - set(scope['symbols']):
        raise ValueError('概览混入快照范围外证券')
    master = {r['symbol']: r for r in manifest['instrument_master']['records']}
    if set(scope['symbols']) - set(master):
        raise ValueError('概览证券主表不完整')
    eligible = sorted(s for s in scope['symbols'] if master[s]['listed_on'] <= session
        and (not master[s].get('delisted_on') or session < master[s]['delisted_on']))
    data = data.loc[data.trade_date.eq(pd.Timestamp(session)) & data.symbol.isin(eligible)].copy()
    for field in ('close', 'pre_close', 'amount', 'volume'):
        raw = data[field]
        numeric = pd.to_numeric(raw, errors='coerce')
        if (raw.map(lambda value: isinstance(value, (bool, np.bool_))).any()
                or (raw.notna() & numeric.isna()).any() or np.isinf(numeric).any()
                or (numeric.dropna() <= 0 if field in ('close', 'pre_close') else numeric.dropna() < 0).any()):
            raise ValueError('概览价格或量额无效')
        data[field] = numeric
    data['price_change'] = data.close / data.pre_close - 1.
    data['observed'] = True
    details = pd.DataFrame({'symbol': pd.Series(eligible, dtype=data.symbol.dtype)}).merge(
        data, on='symbol', how='left', validate='one_to_one')
    details['name'] = details.symbol.map(lambda s: master[s]['name'])
    details['trade_date'] = pd.Timestamp(session)
    observed = details.observed.eq(True)
    valid = observed & details.price_change.notna()
    changes = details.loc[valid, 'price_change']
    missing_base = details.loc[observed & ~valid, 'symbol'].tolist()
    expected = len(eligible)
    amount_valid = observed & details.amount.notna()
    result = dict(scope='snapshot_universe', snapshot_id=manifest['snapshot_id'],
        dataset_id=manifest['dataset_id'], generation=manifest['generation'], session=session,
        expected=expected, observed=int(observed.sum()), valid_return=int(valid.sum()),
        missing_base=missing_base, missing_symbols=details.loc[~observed, 'symbol'].tolist(),
        return_coverage=float(valid.sum() / expected) if expected else None,
        amount_coverage=float(amount_valid.sum() / expected) if expected else None,
        amount_cny=float(details.loc[amount_valid, 'amount'].sum()) if amount_valid.any() else None,
        equal_weight_price_change=float(changes.mean()) if len(changes) else None,
        breadth={'上涨': int((changes > 0).sum()), '平盘': int((changes == 0).sum()),
            '下跌': int((changes < 0).sum()), '涨跌未知': len(missing_base), '行情缺失': int((~observed).sum())},
        details=details, industry=None, return_definition='close_over_source_pre_close_price_change')
    if industry is not None:
        if industry.get('session') != session:
            raise ValueError('行业成分与概览日期不一致')
        assignments = industry['assignments']
        if set(assignments) - set(eligible):
            raise ValueError('行业成分混入概览范围外证券')
        details['industry'] = details.symbol.map(assignments)
        rows = []
        for group, members in details.dropna(subset=['industry']).groupby('industry', sort=True):
            known = members.price_change.dropna()
            rows.append(dict(group=group, members=len(members), valid_return=len(known),
                coverage=len(known) / len(members),
                equal_weight_price_change=float(known.mean()) if len(known) else None))
        result['industry'] = dict(rows=pd.DataFrame(rows, columns=['group', 'members', 'valid_return',
            'coverage', 'equal_weight_price_change']),
            missing_symbols=sorted(set(eligible) - set(assignments)),
            classification_version=industry['classification_version'], membership_id=industry['membership_id'],
            weighting='equal_weight_valid_members')
    return result
