"""A limited free-source daily refresh path; research eligibility stays separate."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
import re

from .instrument_master import InstrumentMaster, _date
from .calendar_service import MarketCalendar
from .providers.baostock_reference import BaoStockReference
from .providers.free_sdk import FreeDailyProvider
from .snapshot_store import SnapshotStore
from .dataset_registry import _validate_dataset_id


def validate_free_scope(symbols, start, end):
    _date(start); _date(end)
    if start > end or (date.fromisoformat(end)-date.fromisoformat(start)).days > 366:
        raise ValueError('首版免费更新每次最多一年，请分段补抓')
    if not isinstance(symbols, (list, tuple)) or any(
        not isinstance(s, str) or not re.fullmatch(r'(?:6\d{5}\.SH|[03]\d{5}\.SZ)', s)
        for s in symbols
    ):
        raise ValueError('免费更新只接受明确的沪深A股代码')
    symbols = sorted(set(symbols))
    if not 1 <= len(symbols) <= 20:
        raise ValueError('免费更新每次选择1至20只沪深A股')
    return symbols


def refresh_free_daily(root, *, symbols, start, end, observed_on=None, dataset_id='free-a-daily',
                       reference=None, providers=None):
    symbols = validate_free_scope(symbols, start, end)
    _validate_dataset_id(dataset_id)
    observed_on=_date(observed_on or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    store=SnapshotStore(root)
    reference=reference or BaoStockReference()
    providers=providers or {p:FreeDailyProvider(p) for p in ('sina','baostock')}
    master=InstrumentMaster()
    references=[]
    for symbol in symbols:
        batch=reference.instrument(symbol,observed_on=observed_on)
        references.append(store.updates.save_artifact(batch))
        master.update(batch.frame.to_dict('records'),observed_on=observed_on,source='baostock.stock_basic',
            batch_id=batch.metadata['batch_id'],provider_scope=['baostock'])
    calendars={}
    for market in sorted({r.market for r in master.records.values()}):
        batch=reference.calendar(market,start,end,generation=1)
        references.append(store.updates.save_artifact(batch))
        payload=batch.metadata['calendar'].copy()
        payload.pop('schema_version')
        payload['days']=tuple((d,o) for d,o in payload['days'])
        calendars[market]=MarketCalendar(**payload)
    shards=[]
    for symbol in symbols:
        instrument=next(r for r in master.records.values() if r.symbol==symbol)
        sessions=[d for d in calendars[instrument.market].sessions(start,end) if instrument.listed_on<=d
            and (instrument.delisted_on is None or d<instrument.delisted_on)]
        if not sessions:
            continue
        shards.append(dict(symbol=symbol,sessions=sessions))
    if not shards:
        return dict(status='no_sessions',message='所选区间没有符合证券上市范围的交易日')
    session_start=min(d for p in shards for d in p['sessions'])
    session_end=max(d for p in shards for d in p['sessions'])
    from .free_refresh_plan import save_plan, run_plan
    plan_id=save_plan(store,dataset_id=dataset_id,master=master,calendars=calendars,references=references,
        shards=shards,start=session_start,end=session_end,symbols=symbols)
    return run_plan(root,plan_id,providers=providers)
