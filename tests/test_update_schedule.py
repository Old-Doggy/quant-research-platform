import json
import pytest

from portfolio_app.update_schedule import scheduled_daily


def test_schedule_catches_sleep_gap_from_fixed_start_and_does_not_repeat_success(tmp_path):
    requests=[]
    def refresh(root,**request):
        requests.append(request)
        return dict(status='published',snapshot=dict(snapshot_id='snapshot-test'))
    options=dict(symbols=['600000.SH'],start='2026-11-01',refresh=refresh)
    # 10:29 UTC = 18:29 Shanghai. Do not claim the current session is ready.
    first=scheduled_daily(tmp_path,now='2026-11-16T10:29:00+00:00',**options)
    assert first['scheduled_through']=='2026-11-15'
    assert scheduled_daily(tmp_path,now='2026-11-16T18:29:00+08:00',**options)['status']=='already_current'
    scheduled_daily(tmp_path,now='2026-11-16T18:31:00+08:00',**options)
    # Computer next wakes up three days later: all dates are in the request.
    scheduled_daily(tmp_path,now='2026-11-19T18:31:00+08:00',**options)
    assert requests[-1]['start']=='2026-11-01'
    assert requests[-1]['end']=='2026-11-19'
    assert len(requests)==3


def test_failure_is_not_completed_and_tampered_schedule_stops(tmp_path):
    options=dict(symbols=['600000.SH'],start='2026-11-01',now='2026-11-16T18:31:00+08:00')
    calls=[]
    def refresh(*a,**kw):
        calls.append(kw)
        return dict(status='incomplete',plan_id='plan-test')
    assert scheduled_daily(tmp_path,refresh=refresh,**options)['status']=='incomplete'
    assert scheduled_daily(tmp_path,refresh=refresh,**options)['status']=='incomplete'
    assert len(calls)==2
    path=next((tmp_path/'schedules').glob('*.json'))
    payload=json.loads(path.read_text())
    assert not payload['completed']
    payload['completed']['2026-11-16']={}
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='校验'):
        scheduled_daily(tmp_path,refresh=refresh,**options)


def test_schedule_invalid_time_and_old_history_stop_before_network(tmp_path):
    for now,start in [('2026-11-16T18:30:00','2026-11-01'),('2026-11-16T18:30:00+08:00','2020-01-01')]:
        with pytest.raises(ValueError):
            scheduled_daily(tmp_path,symbols=['600000.SH'],start=start,now=now,
                refresh=lambda *a,**kw:pytest.fail('invalid scope reached network'))


def test_schedule_rolls_after_a_year_without_replacing_history_identity(tmp_path):
    requests=[]
    def refresh(root,**request):
        requests.append(request)
        return dict(status='published',snapshot=dict(snapshot_id='snapshot-'+str(len(requests))))
    options=dict(symbols=['600000.SH'],start='2025-01-01',refresh=refresh)
    scheduled_daily(tmp_path,now='2025-12-31T18:31:00+08:00',**options)
    result=scheduled_daily(tmp_path,now='2026-01-05T18:31:00+08:00',**options)
    assert requests[-1]['start']=='2025-01-04'
    assert requests[-1]['end']=='2026-01-05'
    assert result['requested_start']=='2025-01-01'
    assert result['effective_start']=='2025-01-04'
    journals=list((tmp_path/'schedules').glob('*.json'))
    assert len(journals)==1
    journal=json.loads(journals[0].read_text())
    assert journal['identity']['start']=='2025-01-01'
    assert set(journal['completed'])=={'2025-12-31','2026-01-05'}


def test_schedule_does_not_silently_skip_a_gap_longer_than_rolling_window(tmp_path):
    options=dict(symbols=['600000.SH'],start='2025-01-01')
    scheduled_daily(tmp_path,now='2025-01-03T18:31:00+08:00',
        refresh=lambda *a,**kw:dict(status='published',snapshot={}),**options)
    with pytest.raises(ValueError,match='补抓'):
        scheduled_daily(tmp_path,now='2026-06-01T18:31:00+08:00',
            refresh=lambda *a,**kw:pytest.fail('uncovered gap reached network'),**options)
