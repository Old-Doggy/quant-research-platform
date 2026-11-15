import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from portfolio_app.update_launcher import launch_free_refresh, recent_refreshes, refresh_report
from portfolio_app.process_lock import process_lock
from portfolio_app.update_store import UpdateBusy


@pytest.mark.parametrize('symbols,start,end', [
    (['fund.SH'],'2025-01-01','2025-01-02'),
    (['600000.SH'],'2024-01-01','2026-01-01'),
    ('600000.SH','2025-01-01','2025-01-02'),
    ([None],'2025-01-01','2025-01-02'),
])
def test_invalid_scope_never_starts_process_or_network(tmp_path, monkeypatch, symbols, start, end):
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('invalid request launched'))
    with pytest.raises(ValueError):
        launch_free_refresh(tmp_path,symbols=symbols,start=start,end=end)
    assert not (tmp_path/'launches').exists()


def test_launcher_detaches_worker_and_preserves_request_on_restart(tmp_path,monkeypatch):
    calls=[]
    class Child:
        pid=123
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:(calls.append((a,kw)) or Child()))
    record=launch_free_refresh(tmp_path,symbols=['600000.SH'],start='2025-01-01',end='2025-01-06')
    args,kwargs=calls[0]
    assert 'portfolio_app.update_cli' in args[0]
    assert kwargs['stdout']==subprocess.DEVNULL
    assert kwargs['creationflags'] or kwargs['start_new_session']
    request=json.loads((tmp_path/'launches'/(record['request_id']+'.request.json')).read_text())
    assert request['symbols']==['600000.SH']
    assert refresh_report(tmp_path,record['request_id'])['status']=='awaiting_result'
    assert recent_refreshes(tmp_path)[0]['request_id']==record['request_id']


def test_crashed_worker_is_not_permanently_waiting_and_finished_result_survives_restart(tmp_path):
    directory=tmp_path/'launches'
    directory.mkdir()
    request='refresh-'+'a'*32
    (directory/(request+'.launch.json')).write_text(json.dumps(dict(request_id=request,pid=123,created_at=time.time()-60)))
    assert refresh_report(tmp_path,request)['status']=='interrupted'
    with process_lock(directory/(request+'.result.running.lock')):
        assert refresh_report(tmp_path,request)['status']=='awaiting_result'
    (directory/(request+'.result.json')).write_text(json.dumps(dict(status='no_sessions')))
    assert recent_refreshes(tmp_path)[0]['report']['status']=='no_sessions'
    (directory/(request+'.result.json')).write_text('{')
    assert refresh_report(tmp_path,request)['error_code']=='status_unreadable'


def test_free_refresh_single_instance_lock_rejects_another_process(tmp_path):
    from portfolio_app.update_cli import execute
    request=dict(root=str(tmp_path),symbols=['600000.SH'],start='2025-01-01',end='2025-01-06')
    with process_lock(tmp_path/'locks'/'free-refresh.lock'):
        with pytest.raises(UpdateBusy):
            execute(request)
        child=subprocess.run([sys.executable,'-c',
            "from portfolio_app.update_cli import execute; import json,sys; execute(json.loads(sys.argv[1]))",
            json.dumps(request)],capture_output=True,text=True,timeout=15)
        assert child.returncode!=0
        assert 'UpdateBusy' in child.stderr
