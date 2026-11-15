"""Shanghai suggested windows; this module never installs system tasks."""
from datetime import datetime
from zoneinfo import ZoneInfo


WINDOWS=('08:30','09:25','18:30','21:30')


def due_windows(now,*,completed):
    instant=datetime.fromisoformat(now) if isinstance(now,str) else now
    if not isinstance(instant,datetime) or instant.tzinfo is None:
        raise ValueError('调度时间必须明确时区')
    if set(completed)-set(WINDOWS):
        raise ValueError('未知更新窗口')
    local=instant.astimezone(ZoneInfo('Asia/Shanghai'))
    return [window for window in WINDOWS if window<=local.strftime('%H:%M') and window not in completed]
