"""Shanghai suggested windows; this module never installs system tasks."""
from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo
from pathlib import Path

from .dataset_registry import _atomic_write_json, _validate_dataset_id
from .snapshot_contracts import identity_hash


WINDOWS=('08:30','09:25','18:30','21:30')


def due_windows(now,*,completed):
    instant=datetime.fromisoformat(now) if isinstance(now,str) else now
    if not isinstance(instant,datetime) or instant.tzinfo is None:
        raise ValueError('调度时间必须明确时区')
    if set(completed)-set(WINDOWS):
        raise ValueError('未知更新窗口')
    local=instant.astimezone(ZoneInfo('Asia/Shanghai'))
    return [window for window in WINDOWS if window<=local.strftime('%H:%M') and window not in completed]


def scheduled_daily(root, *, symbols, start, dataset_id='free-a-daily', now=None, refresh=None):
    """Evaluate one hourly wakeup, catching missed dates from a fixed history start."""
    from .daily_refresh import refresh_free_daily, validate_free_scope
    from .free_refresh_plan import run_plan
    from .process_lock import process_lock
    _validate_dataset_id(dataset_id)
    instant = datetime.now(ZoneInfo('Asia/Shanghai')) if now is None else (
        datetime.fromisoformat(now) if isinstance(now,str) else now)
    if not isinstance(instant,datetime) or instant.tzinfo is None:
        raise ValueError('调度时间必须明确时区')
    local=instant.astimezone(ZoneInfo('Asia/Shanghai'))
    end=(local.date() if local.strftime('%H:%M')>='18:30' else local.date()-timedelta(days=1)).isoformat()
    symbols=validate_free_scope(symbols,start,end)
    identity=dict(dataset_id=dataset_id,symbols=symbols,start=start)
    path=Path(root)/'schedules'/('daily-'+identity_hash(identity)+'.json')
    # The same OS lease protects scheduled and manual updates.
    with process_lock(Path(root)/'locks'/'free-refresh.lock'):
        journal=dict(identity=identity,completed={},pending=None)
        if path.exists():
            journal=json.loads(path.read_text(encoding='utf8'))
            checksum=journal.pop('checksum',None)
            if checksum!=identity_hash(journal) or journal['identity']!=identity:
                raise ValueError('调度记录校验失败')
        if end in journal['completed']:
            return dict(status='already_current',through=end)
        pending=journal.get('pending')
        if refresh is None and pending and pending['end']==end and pending.get('plan_id'):
            result=run_plan(root,pending['plan_id'],retry=True)
        else:
            result=(refresh or refresh_free_daily)(root,symbols=symbols,start=start,end=end,dataset_id=dataset_id)
        if result['status'] in {'published','no_sessions'}:
            journal['completed'][end]=dict(status=result['status'],snapshot_id=result.get('snapshot',{}).get('snapshot_id'))
            journal['pending']=None
        else:
            journal['pending']=dict(end=end,plan_id=result.get('plan_id'),status=result['status'])
        _atomic_write_json(path,{**journal,'checksum':identity_hash(journal)})
        return {**result,'scheduled_through':end}
