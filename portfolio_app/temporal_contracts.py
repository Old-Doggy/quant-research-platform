"""Explicit trading-session and point-in-time contracts.

This module deliberately does not generate a market calendar. A calendar is
usable only when its sessions are supplied and validated by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from portfolio_app.contracts import DatasetManifest


class TemporalContractViolation(ValueError):
    """Raised when dates, sessions, time zones, or PIT fields are unsafe."""


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EXCHANGE_CALENDARS = {"cn_stock_exchange", "hk_exchange", "us_exchange"}


def _zone(timezone: str) -> ZoneInfo:
    if not isinstance(timezone, str) or not timezone.strip():
        raise TemporalContractViolation("timezone is required")
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise TemporalContractViolation(f"unknown timezone: {timezone}") from exc


def _date_label(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is not None or value.hour or value.minute or value.second or value.microsecond:
            raise TemporalContractViolation("session dates must be date-only labels")
        value = value.strftime("%Y-%m-%d")
    elif isinstance(value, date):
        value = value.isoformat()
    elif isinstance(value, str):
        value = value.strip()
    else:
        raise TemporalContractViolation("session dates must be date-only labels")
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise TemporalContractViolation("session dates must use YYYY-MM-DD labels")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise TemporalContractViolation("session date is invalid") from exc
    return parsed.isoformat()


def _as_of(value: object, timezone: str) -> pd.Timestamp:
    zone = _zone(timezone)
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return pd.Timestamp(value).tz_localize(zone)
    if isinstance(value, str) and _DATE_RE.fullmatch(value.strip()):
        return pd.Timestamp(value.strip()).tz_localize(zone)
    try:
        timestamp = pd.Timestamp(value)
    except Exception as exc:  # noqa: BLE001 - normalize public contract errors
        raise TemporalContractViolation("as_of is invalid") from exc
    if timestamp.tzinfo is None:
        raise TemporalContractViolation("as_of timestamp requires timezone")
    return timestamp.tz_convert(zone)


@dataclass(frozen=True)
class SessionCalendar:
    calendar_id: str
    market: str
    timezone: str
    sessions: tuple[str, ...]
    status: str
    source_kind: str = "explicit_session_table"

    @property
    def can_align(self) -> bool:
        return self.status == "verified" and bool(self.sessions)

    def is_session(self, value: object) -> bool:
        if not self.can_align:
            return False
        try:
            label = _date_label(value)
        except TemporalContractViolation:
            return False
        return label in self.sessions

    def normalize_as_of(self, value: object) -> pd.Timestamp:
        if not self.can_align:
            raise TemporalContractViolation("calendar is unavailable; cannot normalize as_of")
        return _as_of(value, self.timezone)


@dataclass(frozen=True)
class PointInTimeValidation:
    status: str
    missing_available_at: int
    future_available_at: int
    row_count: int
    can_read: bool


@dataclass(frozen=True)
class TemporalReadiness:
    status: str
    reasons: tuple[str, ...]


def build_session_calendar(
    sessions: Iterable[object],
    *,
    calendar_id: str,
    market: str,
    timezone: str,
) -> SessionCalendar:
    _zone(timezone)
    labels = [_date_label(value) for value in sessions]
    if not labels:
        raise TemporalContractViolation("session calendar requires explicit sessions")
    if len(set(labels)) != len(labels):
        raise TemporalContractViolation("session calendar contains duplicate sessions")
    if calendar_id in _EXCHANGE_CALENDARS and any(date.fromisoformat(label).weekday() >= 5 for label in labels):
        raise TemporalContractViolation("exchange session calendar contains a weekend")
    ordered = tuple(sorted(labels))
    return SessionCalendar(calendar_id, market, timezone, ordered, "verified")


def load_session_calendar(
    source: str | Path,
    *,
    calendar_id: str,
    market: str,
    timezone: str,
) -> SessionCalendar:
    path = Path(source)
    if not path.is_file():
        raise TemporalContractViolation("session calendar source must be a file")
    try:
        if path.suffix.lower() in {".parquet", ".pq"}:
            frame = pd.read_parquet(path)
        else:
            frame = pd.read_csv(path, dtype=object)
    except Exception as exc:  # noqa: BLE001 - normalize source failures
        raise TemporalContractViolation("cannot read session calendar source") from exc
    if "trade_date" not in frame.columns:
        raise TemporalContractViolation("session calendar requires trade_date")
    raw_dates = frame["trade_date"].astype(str).str.strip()
    compact = pd.to_datetime(raw_dates, format="%Y%m%d", errors="coerce")
    standard = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    parsed = compact.fillna(standard)
    if parsed.isna().any():
        raise TemporalContractViolation("session calendar contains invalid trade_date")
    calendar = build_session_calendar(
        parsed.dt.strftime("%Y-%m-%d").tolist(),
        calendar_id=calendar_id,
        market=market,
        timezone=timezone,
    )
    return SessionCalendar(
        calendar.calendar_id,
        calendar.market,
        calendar.timezone,
        calendar.sessions,
        calendar.status,
        "session_file",
    )


def missing_session_calendar(*, calendar_id: str, market: str, timezone: str) -> SessionCalendar:
    _zone(timezone)
    return SessionCalendar(calendar_id, market, timezone, (), "missing", "missing")


def _available_at_series(frame: pd.DataFrame, timezone: str) -> pd.Series:
    if "available_at" not in frame.columns:
        raise TemporalContractViolation("PIT frame requires available_at")
    _zone(timezone)
    parsed: list[pd.Timestamp | pd.NaT] = []
    for value in frame["available_at"].tolist():
        if value is None or pd.isna(value):
            parsed.append(pd.NaT)
            continue
        try:
            timestamp = pd.Timestamp(value)
        except Exception as exc:  # noqa: BLE001
            raise TemporalContractViolation("available_at is invalid") from exc
        if timestamp.tzinfo is None:
            raise TemporalContractViolation("available_at timestamp requires timezone")
        parsed.append(timestamp.tz_convert(timezone))
    return pd.Series(parsed, index=frame.index, dtype=f"datetime64[ns, {timezone}]")


def validate_point_in_time_frame(
    frame: pd.DataFrame,
    *,
    as_of: object,
    timezone: str,
) -> PointInTimeValidation:
    cutoff = _as_of(as_of, timezone)
    available = _available_at_series(frame, timezone)
    missing = int(available.isna().sum())
    future = int((available.notna() & (available > cutoff)).sum())
    return PointInTimeValidation(
        status="blocked" if missing or future else "verified",
        missing_available_at=missing,
        future_available_at=future,
        row_count=len(frame),
        can_read=missing == 0 and future == 0,
    )


def filter_point_in_time(
    frame: pd.DataFrame,
    *,
    as_of: object,
    timezone: str,
) -> pd.DataFrame:
    cutoff = _as_of(as_of, timezone)
    validation = validate_point_in_time_frame(frame, as_of=cutoff, timezone=timezone)
    if validation.missing_available_at:
        raise TemporalContractViolation("PIT frame has missing available_at")
    available = _available_at_series(frame, timezone)
    return frame.loc[available <= cutoff].copy()


def select_membership_as_of(
    frame: pd.DataFrame,
    *,
    as_of: object,
    timezone: str,
) -> pd.DataFrame:
    cutoff = _as_of(as_of, timezone)
    required = {"symbol", "effective_from", "effective_to"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise TemporalContractViolation(f"membership frame requires: {', '.join(missing)}")
    validation = validate_point_in_time_frame(frame, as_of=cutoff, timezone=timezone)
    if validation.missing_available_at:
        raise TemporalContractViolation("membership frame has missing available_at")
    available = _available_at_series(frame, timezone)
    effective_from = pd.to_datetime(frame["effective_from"], errors="coerce").dt.date
    effective_to = pd.to_datetime(frame["effective_to"], errors="coerce").dt.date
    if effective_from.isna().any() or effective_to.isna().any():
        raise TemporalContractViolation("membership effective dates are invalid")
    cutoff_date = cutoff.date()
    mask = (
        available.le(cutoff)
        & effective_from.le(cutoff_date)
        & effective_to.ge(cutoff_date)
    )
    return frame.loc[mask].copy()


def temporal_readiness(
    manifest: DatasetManifest,
    calendar: SessionCalendar,
    frame: pd.DataFrame,
    *,
    as_of: object,
) -> TemporalReadiness:
    """Return a fail-closed gate for calendar/PIT-dependent research."""
    reasons: list[str] = []
    if manifest.calendar_id == "unknown" or manifest.market == "unknown" or manifest.timezone == "unknown":
        reasons.append("manifest.calendar_or_market_timezone")
    if manifest.point_in_time != "known":
        reasons.append("manifest.point_in_time")
    if not calendar.can_align:
        reasons.append("calendar")
    elif manifest.calendar_id != calendar.calendar_id or manifest.market != calendar.market:
        reasons.append("calendar_identity")
    elif manifest.timezone != calendar.timezone:
        reasons.append("calendar_timezone")
    try:
        cutoff = calendar.normalize_as_of(as_of)
    except TemporalContractViolation:
        reasons.append("as_of")
        cutoff = None
    if cutoff is not None and not calendar.is_session(cutoff.date().isoformat()):
        reasons.append("as_of_not_session")
    try:
        validation = validate_point_in_time_frame(frame, as_of=as_of, timezone=manifest.timezone)
        if validation.missing_available_at:
            reasons.append("available_at_missing")
        if validation.future_available_at:
            reasons.append("available_at_future")
    except TemporalContractViolation:
        reasons.append("available_at_invalid")
    return TemporalReadiness("READY" if not reasons else "BLOCKED", tuple(dict.fromkeys(reasons)))
