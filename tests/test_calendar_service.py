import pandas as pd
import pytest


def table():
    days = pd.date_range('2025-01-27', '2025-02-05')
    return pd.DataFrame(dict(cal_date=days.strftime('%Y%m%d'), exchange='SSE',
        is_open=[int(d.strftime('%Y-%m-%d') in {'2025-01-27', '2025-02-05'}) for d in days]))


def test_calendar_covers_holiday_and_produces_no_fake_weekday_sessions(tmp_path):
    from portfolio_app.calendar_service import MarketCalendar
    cal = MarketCalendar.from_tushare(table(), market='SSE', source='synthetic', generation=1)
    assert cal.sessions('2025-01-27', '2025-02-05') == ('2025-01-27', '2025-02-05')
    assert cal.sessions('2025-01-28', '2025-02-04') == ()
    assert cal.next_session('2025-01-27') == '2025-02-05'
    assert cal.session_calendar('2025-01-27', '2025-02-05').sessions == ('2025-01-27', '2025-02-05')
    path = tmp_path / 'calendar.json'
    cal.save(path)
    assert MarketCalendar.load(path).to_dict() == cal.to_dict()


def test_calendar_rejects_incomplete_or_expired_coverage_and_conflicts():
    from portfolio_app.calendar_service import MarketCalendar
    cal = MarketCalendar.from_tushare(table(), market='SSE', source='synthetic', generation=1)
    with pytest.raises(ValueError, match='覆盖'):
        cal.sessions('2025-01-01', '2025-02-05')
    with pytest.raises(ValueError, match='覆盖'):
        cal.next_session('2025-02-05')
    with pytest.raises(ValueError, match='缺失|连续'):
        MarketCalendar.from_tushare(table().drop(index=3), market='SSE', source='synthetic', generation=1)
    bad = table()
    bad['is_open'] = bad.is_open.astype(object)
    bad.loc[0, 'is_open'] = 'yes'
    with pytest.raises(ValueError, match='状态'):
        MarketCalendar.from_tushare(bad, market='SSE', source='synthetic', generation=1)


def test_calendar_version_changes_when_source_revises_a_day():
    from portfolio_app.calendar_service import MarketCalendar
    first = MarketCalendar.from_tushare(table(), market='SSE', source='synthetic', generation=1)
    revised = table()
    revised.loc[1, 'is_open'] = 1
    second = MarketCalendar.from_tushare(revised, market='SSE', source='synthetic', generation=2)
    assert first.fingerprint != second.fingerprint
    assert first.sessions('2025-01-27', '2025-02-05') != second.sessions('2025-01-27', '2025-02-05')
