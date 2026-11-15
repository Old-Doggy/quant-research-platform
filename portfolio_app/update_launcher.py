"""Launch one checked refresh outside Streamlit, keeping request/status files local."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from .dataset_registry import _atomic_write_json
from .daily_refresh import validate_free_scope
from .process_lock import process_lock
from .update_store import UpdateBusy


def launch_free_refresh(root,*,symbols,start,end):
    symbols=validate_free_scope(symbols,start,end)
    directory=Path(root)/'launches'
    directory.mkdir(parents=True,exist_ok=True)
    request_id='refresh-'+uuid4().hex
    request=directory/(request_id+'.request.json')
    result=directory/(request_id+'.result.json')
    _atomic_write_json(request,dict(root=str(Path(root).resolve()),symbols=symbols,start=start,end=end))
    flags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0
    child=subprocess.Popen([sys.executable,'-m','portfolio_app.update_cli','--request',str(request),'--result',str(result)],
        cwd=Path(__file__).resolve().parents[1],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=flags,start_new_session=os.name!='nt')
    record=dict(request_id=request_id,pid=child.pid,created_at=time.time())
    _atomic_write_json(directory/(request_id+'.launch.json'),record)
    return record


def refresh_report(root,request_id):
    import re
    if not re.fullmatch(r'refresh-[a-f0-9]{32}',request_id):
        raise ValueError('更新请求身份无效')
    path=Path(root)/'launches'/(request_id+'.result.json')
    try:
        if path.exists():
            report=json.loads(path.read_text(encoding='utf8'))
            if report.get('status') not in {'published','incomplete','needs_review','no_sessions','failed'}:
                raise ValueError('任务结果状态无效')
            return report
        launch=path.with_name(request_id+'.launch.json')
        record=json.loads(launch.read_text(encoding='utf8'))
        with process_lock(path.with_suffix('.running.lock')):
            # The child needs a short grace period to import and acquire its lease.
            if time.time()-record['created_at']<15:
                return dict(status='awaiting_result')
        return dict(status='interrupted',error_code='worker_exited_without_result')
    except UpdateBusy:
        return dict(status='awaiting_result')
    except (ValueError,OSError,KeyError,TypeError):
        return dict(status='failed',error_code='status_unreadable')


def recent_refreshes(root, *, limit=20):
    directory=Path(root)/'launches'
    records=[]
    for path in sorted(directory.glob('refresh-*.launch.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:limit]:
        try:
            record=json.loads(path.read_text(encoding='utf8'))
            records.append({**record,'report':refresh_report(root,record['request_id'])})
        except (ValueError,OSError,KeyError,TypeError):
            continue
    return records
