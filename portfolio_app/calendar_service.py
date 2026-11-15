"""Versioned full-date calendars; weekdays are never a substitute for sessions."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import pandas as pd

from .dataset_registry import _atomic_write_json
from .snapshot_contracts import identity_hash
from .temporal_contracts import build_session_calendar
from .instrument_master import _date


class CalendarCoverageError(ValueError):
    pass


@dataclass(frozen=True)
class MarketCalendar:
    market: str
    timezone: str
    source: str
    generation: int
    days: tuple[tuple[str, bool], ...]

    def __post_init__(self):
        if self.market not in {'SSE', 'SZSE', 'BSE'} or not self.source or type(self.generation) is not int or self.generation < 1:
            raise ValueError('交易日历市场、来源或版本无效')
        if self.timezone != 'Asia/Shanghai' or not self.days:
            raise ValueError('交易日历缺少日期或时区无效')
        labels = [d for d, is_open in self.days]
        for day, is_open in self.days:
            _date(day)
            if type(is_open) is not bool:
                raise ValueError('交易日历开市状态无效')
        expected = pd.date_range(labels[0], labels[-1]).strftime('%Y-%m-%d').tolist()
        if labels != expected:
            raise ValueError('交易日历日期必须连续，不可重复或缺失')

    @classmethod
    def from_tushare(cls, frame, *, market, source, generation):
        if not {'cal_date', 'is_open', 'exchange'} <= set(frame):
            raise ValueError('交易日历缺少字段')
        if not frame.exchange.eq(market).all():
            raise ValueError('交易日历包含其他市场')
        if not frame.is_open.astype(str).isin({'0', '1'}).all():
            raise ValueError('交易日历开市状态无效')
        dates = pd.to_datetime(frame.cal_date.astype(str), format='%Y%m%d', errors='coerce')
        if dates.isna().any():
            raise ValueError('交易日历日期无效')
        rows = sorted(zip(dates.dt.strftime('%Y-%m-%d'), frame.is_open.astype(str).eq('1')))
        return cls(market, 'Asia/Shanghai', source, generation, tuple(rows))

    def _covered(self, start, end):
        _date(start)
        _date(end)
        if start > end or start < self.days[0][0] or end > self.days[-1][0]:
            raise CalendarCoverageError(f'交易日历覆盖{self.days[0][0]}至{self.days[-1][0]}，请先补齐查询区间')

    def sessions(self, start, end):
        self._covered(start, end)
        return tuple(day for day, opened in self.days if start <= day <= end and opened)

    def next_session(self, session):
        self._covered(session, session)
        for day, opened in self.days:
            if day > session and opened:
                return day
        raise CalendarCoverageError('交易日历覆盖不足，无法确定下一交易日')

    def session_calendar(self, start, end):
        sessions = self.sessions(start, end)
        return build_session_calendar(sessions, calendar_id=self.fingerprint, market=self.market, timezone=self.timezone)

    def to_dict(self):
        payload = asdict(self)
        payload['days'] = [[d, opened] for d, opened in self.days]
        return {'schema_version': 'market-calendar.v1', **payload}

    @property
    def fingerprint(self):
        return 'calendar-' + identity_hash(self.to_dict())

    def save(self, path):
        payload = self.to_dict()
        _atomic_write_json(Path(path), {**payload, 'checksum': identity_hash(payload)})

    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text(encoding='utf8'))
        if payload.pop('checksum', None) != identity_hash(payload):
            raise ValueError('交易日历校验失败')
        if payload.pop('schema_version', None) != 'market-calendar.v1':
            raise ValueError('交易日历版本未知')
        payload['days'] = tuple((day, opened) for day, opened in payload['days'])
        return cls(**payload)
