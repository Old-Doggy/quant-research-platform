import json
import subprocess
import sys
from pathlib import Path


def test_update_cli_does_not_require_browser_and_rejects_invalid_scope_without_network(tmp_path):
    request=tmp_path/'request.json'
    result=tmp_path/'result.json'
    request.write_text(json.dumps(dict(symbols=['920599.BJ'],start='2025-01-02',end='2025-01-03',
        root=str(tmp_path/'data'))),encoding='utf8')
    child=subprocess.run([sys.executable,'-m','portfolio_app.update_cli','--request',str(request),'--result',str(result)],
        capture_output=True,text=True,timeout=15)
    assert child.returncode==1
    report=json.loads(result.read_text(encoding='utf8'))
    assert report['status']=='failed' and report['error_code']=='invalid_request'
    assert '920599' not in str(report)


def test_schedule_template_resolves_shanghai_windows_and_never_installs_itself():
    from portfolio_app.update_schedule import due_windows
    assert due_windows('2026-11-16T18:29:00+08:00',completed=[])==['08:30','09:25']
    assert due_windows('2026-11-16T18:31:00+08:00',completed=['08:30','09:25'])==['18:30']
    assert due_windows('2026-11-16T13:31:00+00:00',completed=['08:30','09:25','18:30'])==['21:30']
