"""Explicit favorites, screen receipts and bounded sanitized task-history backups."""
import json
import math
import sqlite3
from contextlib import closing

from .research_diagnostics import _safe_row
from .screener_store import ScreenerStore
from .watchlist import _clean


def export_user_state(root,snapshot_ids,result_ids):
    files={}
    watch=root/'watchlist.json'
    if watch.exists():
        if watch.stat().st_size>65536:
            raise ValueError('自选文件超出预算')
        try:
            value=json.loads(watch.read_text(encoding='utf-8'))
        except (ValueError,OSError):
            raise ValueError('自选文件无效') from None
        if (not isinstance(value,dict) or set(value)!={'symbols','recent'}
                or value['symbols']!=_clean(value['symbols']) or value['recent']!=_clean(value['recent'],limit=20)):
            raise ValueError('自选内容无效')
        files['watchlist.json']=value
    screens=ScreenerStore(root/'screening') if (root/'screening/screens').exists() else None
    records=screens.records() if screens else []
    if len(records)>1000:
        raise ValueError('保存筛选超出备份预算')
    for row in records:
        value=screens.open(row['identifier'])
        if value['config']['snapshot_id'] not in snapshot_ids:
            raise ValueError('保存筛选引用的快照未包含在本次备份中')
        files['screening/screens/'+row['identifier']+'.json']=value
    tasks=[]
    path=root/'workbench_tasks/tasks.sqlite'
    if path.exists():
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            rows=db.execute('SELECT id,key_id,status,updated,result_id,failure_json FROM tasks ORDER BY updated DESC LIMIT 1001').fetchall()
        if len(rows)>1000:
            raise ValueError('任务记录超出1000条备份预算')
        for task,key,status,updated,result,failure in rows:
            if (status not in {'running','succeeded','failed','cancelled','interrupted'} or not math.isfinite(updated)
                    or not isinstance(task,str) or not isinstance(key,str) or len(task)>128 or len(key)>256):
                raise ValueError('任务历史无效')
            tasks.append(dict(task_id=task,key_id=key,status='interrupted' if status=='running' else status,
                updated=updated,result_id=result if result in result_ids and status=='succeeded' else None,
                failure=_safe_row(json.loads(failure)) if failure else None))
    files['user-state/tasks.json']=dict(schema='backup-task-history.v1',records=tasks)
    return files,dict(schema='selected-user-state.v1',watchlist='watchlist.json' in files,
        screens=len(records),tasks=len(tasks),running_policy='interrupted_on_restore',
        result_policy='only_included_results_referenced')


def restore_user_state(root,payload):
    if not payload.get('user_state'):
        return
    names={n for n in payload['files'] if n=='watchlist.json' or n.startswith('screening/screens/') or n=='user-state/tasks.json'}
    if payload['user_state'].get('schema')!='selected-user-state.v1' or 'user-state/tasks.json' not in names:
        raise ValueError('用户状态备份清单无效')
    record=json.loads((root/'user-state/tasks.json').read_text(encoding='utf-8'))
    if record.get('schema')!='backup-task-history.v1' or not isinstance(record.get('records'),list):
        raise ValueError('任务历史备份无效')
    if len(record['records'])>1000:
        raise ValueError('任务历史备份超出预算')
    seen=set()
    for r in record['records']:
        if (not isinstance(r,dict) or set(r)!={'task_id','key_id','status','updated','result_id','failure'}
                or r['status'] not in {'succeeded','failed','cancelled','interrupted'}
                or type(r['updated']) not in (int,float) or not math.isfinite(r['updated'])
                or not isinstance(r['task_id'],str) or not isinstance(r['key_id'],str)
                or not r['task_id'] or not r['key_id'] or len(r['task_id'])>128 or len(r['key_id'])>256
                or r['task_id'] in seen
                or r['result_id'] is not None and (r['result_id'] not in payload['result_ids'] or r['status']!='succeeded')
                or r['failure'] is not None and r['failure']!=_safe_row(r['failure'])):
            raise ValueError('任务历史备份状态或结果引用无效')
        seen.add(r['task_id'])
    from .research_runtime import TaskJournal
    journal=TaskJournal(root/'workbench_tasks/tasks.sqlite')
    with journal._connect() as db:
        for r in record['records']:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)',(r['task_id'],r['key_id'],0,r['status'],r['updated'],
                r['result_id'],json.dumps(_safe_row(r['failure'])) if r['failure'] else None))
    # Roundtrip through the same strict validators; no silent watchlist repair.
    _,summary=export_user_state(root,payload['snapshot_ids'],payload['result_ids'])
    if summary!=payload['user_state']:
        raise ValueError('用户状态备份数量或引用不一致')
