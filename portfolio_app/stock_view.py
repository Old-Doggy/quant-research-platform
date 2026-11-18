from __future__ import annotations

import math

import pandas as pd

from portfolio_app.data import build_data_quality_report


def number(value: object) -> float | None:
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def quote_previous_closes(frame: pd.DataFrame) -> pd.Series:
    """Respect explicit upstream gaps; legacy fallback is per security only."""
    previous = pd.to_numeric(
        frame.get("pre_close", pd.Series(float("nan"), index=frame.index)), errors="coerce"
    ).replace(0, float("nan"))
    if frame.attrs.get("previous_close_policy") == "explicit_source_only.v1":
        return previous
    close = pd.to_numeric(frame["close"], errors="coerce")
    symbols = frame.get("symbol", frame.get("ts_code", pd.Series("", index=frame.index)))
    return previous.fillna(close.groupby(symbols, dropna=False).shift(1))


def build_single_stock_snapshot(frame: pd.DataFrame, *, symbol: str = "") -> dict[str, object]:
    """Separate the latest historical quote from simulated strategy state."""
    data = frame.sort_values("trade_date").copy()
    if data.empty:
        raise ValueError("single stock snapshot requires data")
    latest = data.iloc[-1]
    close = number(latest["close"])
    previous = number(quote_previous_closes(data).iloc[-1])
    first = number(data.iloc[0]["close"])
    fills = sorted(
        [event for event in frame.attrs.get("trade_events", []) if event.get("event_type") == "FILL"],
        key=lambda event: (event["effective_date"], event["event_id"]),
    )
    return {
        "symbol": symbol or str(latest.get("symbol", "")),
        "latest_date": pd.Timestamp(latest["trade_date"]).strftime("%Y-%m-%d"),
        "close": close,
        "daily_change": close / previous - 1 if close is not None and previous else None,
        "period_return": close / first - 1 if close is not None and first else None,
        "strategy_state": "持有" if number(latest.get("position")) else "观望",
        "signal_state": "持有" if number(latest.get("signal")) else "观望",
        "reason": str(latest.get("reason_text_public", "")),
        "latest_trade": fills[-1] if fills else None,
        "start_date": pd.Timestamp(data.iloc[0]["trade_date"]).strftime("%Y-%m-%d"),
        "observations": len(data),
    }


def build_stock_quote_table(frame: pd.DataFrame, *, limit: int = 12) -> pd.DataFrame:
    """Readable quote history; source units stay unchanged and are never guessed."""
    data = frame.sort_values("trade_date").copy()
    changes = pd.to_numeric(data["close"], errors="coerce") / quote_previous_closes(data) - 1
    data["_change"] = changes
    data = data.tail(max(1, int(limit)))
    table = pd.DataFrame({"日期": pd.to_datetime(data["trade_date"]).dt.strftime("%Y-%m-%d")})
    for key, label in (("open", "开盘"), ("high", "最高"), ("low", "最低"), ("close", "收盘")):
        # Display precision must not turn a positive adjusted quote into zero.
        table[label] = pd.to_numeric(data[key], errors="coerce").round(6)
    table["涨跌幅"] = data["_change"].map(lambda v: f"{v:+.2%}" if pd.notna(v) else "--")
    for key, label in (("vol", "成交量"), ("amount", "成交额"), ("turnover_rate", "换手率")):
        values = data.get(key, pd.Series(float("nan"), index=data.index))
        table[label] = values.map(
            lambda v: "--" if number(v) is None else (f"{float(v):.2f}%" if key == "turnover_rate" else f"{float(v):,.0f}")
        )
    table.attrs = {}
    return table.reset_index(drop=True)


def build_readable_trades(events: list[dict[str, object]]) -> pd.DataFrame:
    """Use the same simulated fills as chart markers, excluding internal IDs."""
    rows = []
    for event in sorted(events, key=lambda item: str(item.get("effective_date", "")), reverse=True):
        if event.get("event_type") != "FILL":
            continue
        rows.append({
            "事件ID": event.get("event_id", ""),
            "信号日期": event["decision_date"], "执行日期": event["effective_date"],
            "操作": {"BUY": "买入", "SELL": "卖出"}.get(str(event["side"]), event["side"]),
            "模拟成交价": number(event.get("price")),
            "触发原因": event.get("reason_text_public", ""),
        })
    return pd.DataFrame(rows, columns=["事件ID", "信号日期", "执行日期", "操作", "模拟成交价", "触发原因"])


def build_market_detail_context(
    frame: pd.DataFrame,
    *,
    symbol: str = "",
    source: str = "本地历史行情",
    price_mode: str = "unknown",
    price_unit: str = "unknown",
    volume_unit: str = "unknown",
    as_of: object | None = None,
) -> dict[str, object]:
    """Build the public data-details drawer context without exposing paths."""
    data = frame.copy()
    dates = pd.to_datetime(data.get("trade_date", pd.Series(dtype="datetime64[ns]")), errors="coerce").dropna()
    quality = build_data_quality_report(data)
    end = dates.max().strftime("%Y-%m-%d") if not dates.empty else None
    cutoff = pd.Timestamp(as_of).strftime("%Y-%m-%d") if as_of is not None else end
    return {
        "source": str(source),
        "symbol": str(symbol),
        "price_mode": str(price_mode),
        "price_unit": str(price_unit),
        "volume_unit": str(volume_unit),
        "as_of": cutoff,
        "latest_date": end,
        "is_realtime": False,
        "quality_status": str(quality.get("status", "unknown")),
        "rows": int(len(data)),
        "observations": int(len(dates)),
        "coverage_start": dates.min().strftime("%Y-%m-%d") if not dates.empty else None,
        "coverage_end": end,
        "missing_required_value_rows": int(quality.get("missing_required_value_rows", 0)),
        "invalid_ohlc_rows": int(quality.get("invalid_ohlc_rows", 0)),
    }
