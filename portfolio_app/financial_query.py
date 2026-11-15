"""Conservative daily as-of queries: observations cannot be backdated to history."""
from datetime import datetime
from zoneinfo import ZoneInfo

from .instrument_master import _date


def financial_asof(store, *, endpoint, symbol, as_of, calendar, report_type='1', period=None):
    _date(as_of)
    if period is not None: _date(period)
    # Every as-of date must be in actual recorded calendar coverage.
    if not calendar.sessions(as_of,as_of):
        raise ValueError('财务查询需要明确交易日')
    rows=store.observations(endpoint=endpoint,symbol=symbol)
    candidates=[]
    expected_type='indicator' if endpoint=='fina_indicator' else report_type
    for row in rows:
        if row['report_type']!=expected_type or (period is not None and row['period']!=period):
            continue
        observed=datetime.fromisoformat(row['fetched_at']).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        source_day=max(row['ann_date'],row['f_ann_date'] or row['ann_date'])
        known_day=max(source_day,observed)
        if known_day>=as_of:
            continue
        # Unknown release clock: only a strictly later actual session can use it.
        sessions=calendar.sessions(known_day,as_of)
        usable=next((d for d in sessions if d>known_day),None)
        if usable is None: continue
        candidates.append({**row,'available_at':usable,'availability_policy':'next_session_after_observed_and_announced',
            'pit_coverage':'forward_observation_only'})
    if not candidates:
        return None
    latest_period=max(r['period'] for r in candidates)
    candidates=[r for r in candidates if r['period']==latest_period]
    # Re-observation of the same values does not delay its original eligibility.
    by_version={}
    for row in candidates:
        previous=by_version.get(row['report_version'])
        if previous is None or row['available_at']<previous['available_at']:
            by_version[row['report_version']]=row
    rank=lambda r:(r['available_at'],max(r['ann_date'],r['f_ann_date'] or r['ann_date']))
    latest=max(rank(r) for r in by_version.values())
    chosen=[r for r in by_version.values() if rank(r)==latest]
    if len(chosen)!=1:
        raise ValueError('同一可得日存在不同财务版本，需明确更正顺序')
    return chosen[0]
