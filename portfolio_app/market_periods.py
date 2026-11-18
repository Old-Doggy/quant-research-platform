"""Trading-period aggregation and independent historical date windows."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


PERIODS = ("1d", "1w", "1m")


def _parse_date(value: object, field: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"{field} is invalid")
    return timestamp.normalize()


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    if frame.empty:
        return frame.copy()
    required = {"trade_date", "open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"market frame is missing required columns: {', '.join(missing)}")
    data = frame.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.normalize()
    if data["trade_date"].isna().any():
        raise ValueError("market frame contains invalid trade_date")
    if "symbol" not in data.columns:
        data["symbol"] = ""
    data["symbol"] = data["symbol"].fillna("").astype(str)
    for column in ("open", "high", "low", "close", "vol", "amount", "turnover_rate"):
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)


def _period_key(period: str) -> tuple[str, str]:
    value = str(period or "").strip().lower()
    if value == "1d":
        return "D", "D"
    if value == "1w":
        return "W-SUN", "W"
    if value == "1m":
        return "ME", "M"
    raise ValueError("period must be one of 1d, 1w, 1m")


def _empty_columns(frame: pd.DataFrame) -> list[str]:
    columns = ["symbol", "trade_date", "period_start", "period_end", "open", "high", "low", "close"]
    columns.extend(column for column in ("pre_close", "vol", "amount", "turnover_rate", "is_complete") if column in frame.columns or column == "is_complete")
    return columns


def aggregate_ohlcv(frame: pd.DataFrame, period: str = "1d") -> pd.DataFrame:
    """Aggregate daily bars without inventing missing trading sessions.

    ``trade_date`` is the last observed session in a period. Calendar bounds
    are retained separately so an incomplete latest week/month can be shown.
    """
    data = _prepare(frame)
    frequency, _ = _period_key(period)
    if data.empty:
        return pd.DataFrame(columns=_empty_columns(data))
    if period == "1d":
        result = data.copy()
        result["period_start"] = result["trade_date"].dt.strftime("%Y-%m-%d")
        result["period_end"] = result["trade_date"].dt.strftime("%Y-%m-%d")
        result["is_complete"] = True
        return result

    grouped = data.groupby(["symbol", pd.Grouper(key="trade_date", freq=frequency)], sort=True, dropna=False)
    rows: list[dict[str, object]] = []
    for (symbol, bucket), group in grouped:
        group = group.sort_values("trade_date", kind="stable")
        if period == "1w":
            period_start = bucket - pd.Timedelta(days=6)
            period_end = bucket
        else:
            period_start = bucket.replace(day=1)
            period_end = bucket
        row: dict[str, object] = {
            "symbol": symbol,
            "trade_date": group["trade_date"].iloc[-1],
            "period_start": period_start.normalize().strftime("%Y-%m-%d"),
            "period_end": period_end.normalize().strftime("%Y-%m-%d"),
            "open": group["open"].iloc[0],
            "high": group["high"].max(),
            "low": group["low"].min(),
            "close": group["close"].iloc[-1],
            "is_complete": True,
        }
        if "pre_close" in group.columns:
            row["pre_close"] = group["pre_close"].iloc[0]
        for column in ("vol", "amount"):
            if column in group.columns:
                row[column] = group[column].sum(min_count=1)
        if "turnover_rate" in group.columns:
            row["turnover_rate"] = group["turnover_rate"].sum(min_count=1)
        rows.append(row)
    result = pd.DataFrame(rows).sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)
    if not result.empty and frame.attrs.get("previous_close_policy") != "explicit_source_only.v1":
        result["pre_close"] = result.groupby("symbol", dropna=False)["close"].shift(1)
    result.attrs = data.attrs.copy()
    # Keep this metadata as ordinary Python bools for JSON/UI consumers.
    result["is_complete"] = pd.Series([bool(value) for value in result["is_complete"]], dtype=object)
    return result


def _mark_completeness(
    frame: pd.DataFrame,
    period: str,
    *,
    observed_start: pd.Timestamp,
    observed_end: pd.Timestamp,
) -> pd.DataFrame:
    if frame.empty or period == "1d":
        return frame
    result = frame.copy()
    result["is_complete"] = (
        (pd.to_datetime(result["period_start"]) >= observed_start)
        & (pd.to_datetime(result["period_end"]) <= observed_end)
    ).map(bool).astype(object)
    return result


def build_market_window(
    frame: pd.DataFrame,
    *,
    period: str = "1d",
    start: object | None = None,
    end: object | None = None,
) -> dict[str, object]:
    """Apply a session-date window, then aggregate the requested period."""
    data = _prepare(frame)
    _period_key(period)
    if data.empty:
        return {
            "status": "EMPTY",
            "message": "当前窗口没有可用行情。",
            "period": period,
            "window": {"start": None, "end": None},
            "frame": aggregate_ohlcv(data, period),
            "observed_sessions": 0,
            "bars": 0,
        }
    minimum, maximum = data["trade_date"].min(), data["trade_date"].max()
    window_start = _parse_date(start, "start") if start is not None else minimum
    window_end = _parse_date(end, "end") if end is not None else maximum
    if window_start > window_end:
        raise ValueError("start cannot be after end")
    selected = data.loc[data["trade_date"].between(window_start, window_end)].copy()
    aggregated = aggregate_ohlcv(selected, period)
    aggregated = _mark_completeness(
        aggregated,
        period,
        observed_start=window_start,
        observed_end=window_end,
    )
    return {
        "status": "READY" if not selected.empty else "EMPTY",
        "message": "历史行情" if not selected.empty else "当前窗口没有可用行情。",
        "period": period,
        "window": {"start": window_start.strftime("%Y-%m-%d"), "end": window_end.strftime("%Y-%m-%d")},
        "frame": aggregated,
        "observed_sessions": int(len(selected)),
        "bars": int(len(aggregated)),
    }
