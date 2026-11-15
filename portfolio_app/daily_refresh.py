"""A limited free-source daily refresh path; research eligibility stays separate."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .instrument_master import InstrumentMaster, _date
from .calendar_service import MarketCalendar
from .providers.baostock_reference import BaoStockReference
from .providers.free_sdk import FreeDailyProvider
from .snapshot_contracts import identity_hash
from .snapshot_store import SnapshotStore
from .update_jobs import run_update


def refresh_free_daily(root, *, symbols, start, end, observed_on=None, dataset_id='free-a-daily',
                       reference=None, providers=None):
    _date(start); _date(end)
    observed_on=_date(observed_on or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    if start>end or (date.fromisoformat(end)-date.fromisoformat(start)).days>366:
        raise ValueError('首版免费更新每次最多一年，请分段补抓')
    symbols=sorted(set(symbols))
    if not symbols or len(symbols)>20 or any(not isinstance(s,str) or not s.endswith(('.SH','.SZ')) for s in symbols):
        raise ValueError('免费更新每次选择1至20只沪深A股')
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
    master_id=identity_hash(master.to_dict())
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
    jobs=[]
    artifacts={}
    for name in ('baostock','sina'):
        job=store.updates.create(provider=name,dataset='a_daily_raw',scope_hash=master_id,
            adapter_version='free-sdk-1.0',mode='incremental',shards=shards)
        report=run_update(store.updates,job,lambda part:providers[name].daily(part['symbol'],sessions=part['sessions']))
        jobs.append(report)
        artifacts[name]=[p['artifact_id'] for p in store.updates.shards(job) if p['status']=='succeeded']
    if any(j['status']!='succeeded' for j in jobs):
        return dict(status='incomplete',jobs=jobs,message='部分来源未完成，当前快照保持原版')
    session_start=min(d for p in shards for d in p['sessions'])
    session_end=max(d for p in shards for d in p['sessions'])
    try:
        snapshot=store.publish_daily(dataset_id=dataset_id,batch_ids=artifacts['baostock'],comparison_ids=artifacts['sina'],
            master=master,calendars=calendars,start=session_start,end=session_end,symbols=symbols,
            reference_batch_ids=references)
    except ValueError:
        return dict(status='needs_review',jobs=jobs,message='覆盖或跨源核对未通过，当前快照保持原版')
    return dict(status='published',jobs=jobs,snapshot=snapshot)
