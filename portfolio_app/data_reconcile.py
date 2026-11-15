"""Coverage and raw daily reconciliation; conflicts never overwrite either input."""
from collections import Counter
import math

import pandas as pd

from .instrument_master import _date


# Half of each source's declared output quantum, in canonical units.
# Price tolerance stays below one A-share tick: a one-tick difference fails.
_PROFILES = {
    'tushare_a_daily': ('tushare', .005, .5, .5),
    'tencent.raw.lots': ('tencent', .005, .5, 50.),
    'tencent.raw.star': ('tencent', .005, .5, 50.),
    'sina.sdk.raw': ('sina', .005, 0., .5),
    'baostock.sdk.raw': ('baostock', .00005, 0., .00005),
    'eastmoney.sdk.raw': ('eastmoney', .005, 50., .005),
}


def _keys(frame):
    if not {'ts_code','trade_date'} <= set(frame):
        raise ValueError('日线核对缺少证券或日期')
    data = frame.copy(deep=True)
    data['trade_date'] = pd.to_datetime(data.trade_date, errors='coerce')
    if data.trade_date.isna().any() or data.ts_code.isna().any() or data.duplicated(['ts_code','trade_date']).any():
        raise ValueError('日线核对日期、代码无效或重复')
    return data.set_index(['ts_code','trade_date'])


def _contract(frame, provider):
    units = frame.attrs.get('field_units', {})
    if units.get('price') != 'CNY_per_share' or units.get('volume') != 'shares' or units.get('amount') != 'CNY':
        raise ValueError('跨源核对必须使用相同的元、股、元单位')
    if frame.attrs.get('research_dataset', {}).get('price_basis') != 'raw':
        raise ValueError('跨源核对只接受原始价格，不能混合复权基准')
    profile = frame.attrs.get('normalization', {}).get('profile')
    values = _PROFILES.get(profile)
    if values is None or values[0] != provider:
        raise ValueError('来源单位或输出精度尚未核验')
    return values


def compare_daily_sources(primary, secondary, *, primary_provider, secondary_provider, price_tick=.01):
    if primary_provider == secondary_provider:
        raise ValueError('同一真实上游不能作为独立交叉验证')
    if not math.isfinite(price_tick) or price_tick <= 0:
        raise ValueError('最小报价单位无效')
    p, s = _contract(primary, primary_provider), _contract(secondary, secondary_provider)
    first, second = _keys(primary), _keys(secondary)
    fields = ('open','high','low','close','volume','amount')
    if not set(fields) <= set(first) or not set(fields) <= set(second):
        raise ValueError('跨源核对缺少价格、数量或金额')
    differences = []
    price_diffs = []
    for key in sorted(set(first.index) | set(second.index)):
        symbol, session = key[0], key[1].strftime('%Y-%m-%d')
        if key not in first.index or key not in second.index:
            differences.append(dict(symbol=symbol,session=session,field='row',status='missing_row'))
            continue
        for field in fields:
            a, b = first.loc[key,field], second.loc[key,field]
            if pd.isna(a) or pd.isna(b):
                differences.append(dict(symbol=symbol,session=session,field=field,status='missing_value'))
                continue
            try:
                valid = math.isfinite(float(a)) and math.isfinite(float(b)) and min(float(a),float(b))>=0
                if field in fields[:4]:
                    valid = valid and min(float(a),float(b))>0
            except (ValueError,TypeError):
                valid = False
            if not valid:
                differences.append(dict(symbol=symbol,session=session,field=field,status='conflict',reason='invalid_value'))
                continue
            delta = abs(float(a)-float(b))
            if field in fields[:4]:
                price_diffs.append(delta)
                # Even when both prices are rounded, a full tick disagreement is unresolved.
                tolerance = min(p[1]+s[1], price_tick/2)
            elif field=='volume':
                tolerance = p[2]+s[2]
            else:
                tolerance = p[3]+s[3]
            status = 'equal' if delta <= 1e-8 else ('within_source_precision' if delta <= tolerance+1e-8 else 'conflict')
            if status != 'equal':
                differences.append(dict(symbol=symbol,session=session,field=field,status=status,
                    primary=float(a),secondary=float(b),difference=delta,tolerance=tolerance))
    counts = dict(Counter(row['status'] for row in differences))
    status = 'conflict' if counts.get('conflict') else ('incomplete' if counts.get('missing_row') or counts.get('missing_value') else 'passed')
    if not len(first) and not len(second):
        status = 'incomplete'
    return dict(status=status,primary_provider=primary_provider,secondary_provider=secondary_provider,
        counts=counts,differences=differences,max_price_difference=max(price_diffs,default=None),
        comparison_scope='raw_daily_only',automatic_replacement=False)


def check_daily_coverage(frame, *, master, calendars, start, end, symbols, verified_suspensions=None):
    _date(start)
    _date(end)
    if start>end or not symbols:
        raise ValueError('覆盖检查范围无效')
    records = {r.symbol:r for r in master.records.values()}
    if set(symbols)-set(records):
        raise ValueError('覆盖检查证券不在主表')
    data = _keys(frame)
    evidence = verified_suspensions or {}
    if any(not isinstance(batch,str) or not batch.strip() for batch in evidence.values()):
        raise ValueError('停牌豁免必须附已核验批次身份')
    allowed, rows, gaps = set(), [], []
    for symbol in sorted(set(symbols)):
        instrument = records[symbol]
        calendar = calendars.get(instrument.market)
        if calendar is None or calendar.market!=instrument.market:
            raise ValueError('覆盖检查缺少对应市场日历')
        for session in calendar.sessions(start,end):
            key=(symbol,pd.Timestamp(session))
            allowed.add(key)
            listed=instrument.listed_on<=session and (instrument.delisted_on is None or session<instrument.delisted_on)
            observed=key in data.index
            suspended=(symbol,session) in evidence
            if observed and (not listed or suspended):
                status='conflict'
            elif not listed:
                status='not_listed'
            elif observed:
                status='observed'
            elif suspended:
                status='suspended'
            else:
                status='unknown_gap'
                gaps.append(dict(symbol=symbol,session=session))
            rows.append(dict(symbol=symbol,session=session,status=status,
                evidence_batch=evidence.get((symbol,session))))
    for symbol,day in set(data.index)-allowed:
        rows.append(dict(symbol=symbol,session=day.strftime('%Y-%m-%d'),status='conflict',reason='outside_scope_or_calendar'))
    if any(not isinstance(key,tuple) or len(key)!=2 or (key[0],pd.Timestamp(key[1])) not in allowed for key in evidence):
        raise ValueError('停牌证据超出核对范围或交易日历')
    counts=dict(Counter(r['status'] for r in rows))
    return dict(status='conflict' if counts.get('conflict') else ('incomplete' if gaps else 'passed'),
        counts=counts,rows=rows,unknown_gaps=gaps,validation_scope='expected_daily_keys_only')
