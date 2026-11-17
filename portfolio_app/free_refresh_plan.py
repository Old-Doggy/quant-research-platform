"""Persist pinned reference inputs so retries never re-download successful shards."""
import json
import re
from uuid import uuid4

from .calendar_service import MarketCalendar
from .dataset_registry import _atomic_write_json, _validate_dataset_id
from .instrument_master import InstrumentMaster, _date
from .providers.free_sdk import FreeDailyProvider
from .snapshot_contracts import identity_hash
from .snapshot_store import SnapshotStore
from .update_jobs import run_update


def save_plan(store, *, dataset_id, master, calendars, references, shards, start, end, symbols):
    plan_id = 'refresh-plan-'+uuid4().hex
    scope = identity_hash(dict(master=master.to_dict(), plan_id=plan_id))
    jobs = {name:store.updates.create(provider=name, dataset='a_daily_raw', scope_hash=scope,
        adapter_version='free-sdk-1.0', mode='incremental', shards=shards) for name in ('baostock','sina')}
    payload = dict(plan_id=plan_id, dataset_id=dataset_id, master=master.to_dict(),
        calendars={m:c.to_dict() for m,c in calendars.items()}, reference_batch_ids=references,
        jobs=jobs, start=start, end=end, symbols=symbols)
    _atomic_write_json(store.root/'refresh-plans'/(plan_id+'.json'), {**payload,'checksum':identity_hash(payload)})
    return plan_id


def read_plan(store, plan_id):
    if not isinstance(plan_id,str) or not re.fullmatch(r'refresh-plan-[a-f0-9]{32}',plan_id):
        raise ValueError('更新计划身份无效')
    payload=json.loads((store.root/'refresh-plans'/(plan_id+'.json')).read_text(encoding='utf8'))
    checksum=payload.pop('checksum',None)
    if checksum!=identity_hash(payload) or payload['plan_id']!=plan_id:
        raise ValueError('更新计划校验失败')
    _validate_dataset_id(payload['dataset_id'])
    _date(payload['start']); _date(payload['end'])
    if set(payload['jobs'])!={'baostock','sina'}:
        raise ValueError('更新计划来源无效')
    for artifact in payload['reference_batch_ids']:
        store.updates.verify_artifact(artifact)
    for name, job in payload['jobs'].items():
        request=store.updates.request(job)
        if request['provider']!=name or request['dataset']!='a_daily_raw':
            raise ValueError('任务与更新计划不一致')
    return payload


def run_plan(root, plan_id, *, retry=False, providers=None):
    store=SnapshotStore(root)
    plan=read_plan(store,plan_id)
    master=InstrumentMaster.from_dict(plan['master'])
    calendars={}
    for market, value in plan['calendars'].items():
        payload={k:v for k,v in value.items() if k!='schema_version'}
        payload['days']=tuple((d,o) for d,o in payload['days'])
        calendars[market]=MarketCalendar(**payload)
    providers=providers or {p:FreeDailyProvider(p) for p in ('sina','baostock')}
    jobs=[]
    artifacts={}
    for name,job in plan['jobs'].items():
        if retry:
            # Only failed/review shards are reset. Successful files stay immutable.
            store.updates.retry_failed(job)
        report=run_update(store.updates,job,lambda part:providers[name].daily(part['symbol'],sessions=part['sessions']))
        jobs.append(report)
        artifacts[name]=[p['artifact_id'] for p in store.updates.shards(job) if p['status']=='succeeded']
    result=dict(plan_id=plan_id,jobs=jobs)
    if any(j['status']!='succeeded' for j in jobs):
        return dict(**result,status='incomplete')
    candidate=dict(batch_ids=artifacts['baostock'],comparison_ids=artifacts['sina'],master=master,
        calendars=calendars,start=plan['start'],end=plan['end'],symbols=plan['symbols'])
    checks=store.inspect_daily(**candidate)
    if any(checks[name]['status']!='passed' for name in ('coverage','comparison')):
        return dict(**result,status='needs_review',checks=checks)
    # Re-running an already published plan does not create a duplicate generation.
    current=store.current(plan['dataset_id'])
    if (current and current['batch_ids']==artifacts['baostock']
            and current['comparison_ids']==artifacts['sina']
            and current.get('reference_batch_ids')==plan['reference_batch_ids']
            and current['instrument_master']==master.to_dict()
            and current['calendars']=={name:value.to_dict() for name,value in calendars.items()}
            and current['range']==dict(start=plan['start'],end=plan['end'],symbols=sorted(set(plan['symbols'])))):
        return dict(**result,status='published',snapshot=current,checks=checks)
    try:
        snapshot=store.publish_daily(dataset_id=plan['dataset_id'],batch_ids=artifacts['baostock'],comparison_ids=artifacts['sina'],
            master=master,calendars=calendars,start=plan['start'],end=plan['end'],symbols=plan['symbols'],
            reference_batch_ids=plan['reference_batch_ids'])
    except ValueError:
        return dict(**result,status='needs_review')
    return dict(**result,status='published',snapshot=snapshot,checks=checks)
