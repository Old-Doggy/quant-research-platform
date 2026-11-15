from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
import math

import pandas as pd

from portfolio_app.indicators import calculate_registered_indicators, normalize_indicator_config


PUBLIC_EVENT_FIELDS = (
    "event_id", "event_type", "status", "symbol", "side", "decision_date",
    "effective_date", "fill_date", "order_id", "fill_id", "quantity", "price",
    "reason_code", "reason_text_public", "evidence", "portfolio_leg",
)


def _public_event(event: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in PUBLIC_EVENT_FIELDS:
        if key not in event:
            continue
        value = event[key]
        if key == "evidence" and not isinstance(value, dict):
            value = {"summary": str(value)}
        result[key] = value
    return result


def _event_payload(events: Sequence[dict[str, object]] | None, bar_times: set[str], cutoff: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    public_events: list[dict[str, object]] = []
    for raw in events or ():
        event = _public_event(dict(raw))
        event_id = str(event.get("event_id") or "")
        date_value = event.get("effective_date", event.get("decision_date"))
        if not event_id or date_value is None:
            continue
        timestamp = _date_text(date_value)
        if timestamp not in bar_times or timestamp > cutoff:
            continue
        event["effective_date"] = timestamp
        public_events.append(event)
    public_events.sort(key=lambda item: (str(item.get("effective_date", "")), str(item.get("event_type", "")), str(item.get("event_id", ""))))
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for event in public_events:
        if event.get("event_type") != "FILL" or str(event.get("side", "")).upper() not in {"BUY", "SELL"}:
            continue
        groups.setdefault((str(event["effective_date"]), str(event["side"]).upper()), []).append(event)
    markers: list[dict[str, object]] = []
    for (timestamp, side), grouped in sorted(groups.items()):
        event_ids = [str(event["event_id"]) for event in grouped]
        prices = [float(value) for event in grouped if (value := _finite_number(event.get("price"))) is not None]
        markers.append({
            "id": event_ids[0] if len(event_ids) == 1 else f"fill-group:{timestamp}:{side}",
            "event_ids": event_ids,
            "time": timestamp,
            "position": "belowBar" if side == "BUY" else "aboveBar",
            "shape": "arrowUp" if side == "BUY" else "arrowDown",
            "color": "#e45756" if side == "BUY" else "#2a9d8f",
            "text": ("买" if side == "BUY" else "卖") + (f"×{len(grouped)}" if len(grouped) > 1 else ""),
            "event_count": len(grouped),
            "price": sum(prices) / len(prices) if prices else None,
        })
    return public_events, markers


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_text(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("chart date is invalid")
    return timestamp.strftime("%Y-%m-%d")


def _validate_zoom(min_visible_bars: int, max_visible_bars: int | None, bar_count: int) -> tuple[int, int, int]:
    if min_visible_bars < 1:
        raise ValueError("min_visible_bars must be positive")
    if bar_count == 0:
        if max_visible_bars is not None and max_visible_bars < 1:
            raise ValueError("max_visible_bars must be positive")
        return 1, 1, 1
    maximum = bar_count if max_visible_bars is None else int(max_visible_bars)
    if maximum < 1:
        raise ValueError("max_visible_bars must be positive")
    if maximum < min_visible_bars:
        if max_visible_bars is None:
            min_visible_bars = maximum
        else:
            raise ValueError("max_visible_bars cannot be smaller than min_visible_bars")
    maximum = min(maximum, bar_count)
    minimum = min(min_visible_bars, maximum)
    return minimum, maximum, maximum


def clamp_chart_range(
    requested: dict[str, object] | None,
    *,
    bar_count: int,
    min_visible_bars: int,
    max_visible_bars: int | None = None,
) -> dict[str, int]:
    """Clamp a logical chart range to history and density bounds."""
    minimum, maximum, _ = _validate_zoom(min_visible_bars, max_visible_bars, bar_count)
    if bar_count <= 0:
        return {"from": 0, "to": 0}
    value = requested or {}
    try:
        raw_from, raw_to = float(value.get("from", 0)), float(value.get("to", bar_count - 1))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("chart range must contain numeric from/to") from exc
    if not math.isfinite(raw_from) or not math.isfinite(raw_to):
        raise ValueError("chart range must be finite")
    left, right = sorted((raw_from, raw_to))
    span = max(minimum, min(maximum, right - left + 1))
    end = max(span - 1, min(bar_count - 1, right))
    start = max(0, end - span + 1)
    return {"from": int(round(start)), "to": int(round(end))}


def build_chart_state_key(
    symbol: str,
    period: str,
    bounds: dict[str, object],
    indicator_config: list[dict[str, object]] | None = None,
) -> str:
    """Build a path-free local-storage key for one chart layout."""
    # Indicator visibility is deliberately excluded: changing indicators must
    # preserve the user's time range. Symbol, period and data bounds define the
    # compatible history surface and therefore the storage scope.
    canonical = json.dumps({
        "symbol": str(symbol), "period": str(period), "bounds": bounds,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    safe_symbol = "".join(char if char.isalnum() or char in "._-" else "_" for char in str(symbol))[:40] or "chart"
    safe_period = "".join(char if char.isalnum() else "_" for char in str(period))[:8]
    return f"quant-chart-state-v1:{safe_symbol}:{safe_period}:{digest}"


def _normalise_bars(frame: pd.DataFrame, symbol: str, as_of: object | None) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if frame.empty:
        return [], []
    required = {"trade_date", "open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"chart frame is missing required columns: {', '.join(missing)}")
    data = frame.copy()
    if symbol and "symbol" in data.columns:
        data = data.loc[data["symbol"].astype(str).eq(symbol)].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    if data["trade_date"].isna().any():
        raise ValueError("chart frame contains invalid trade_date values")
    data = data.sort_values("trade_date", kind="stable").reset_index(drop=True)
    if data["trade_date"].duplicated().any():
        raise ValueError("chart frame contains duplicate trade_date keys")
    if as_of is not None:
        data = data.loc[data["trade_date"] <= pd.Timestamp(as_of)].copy()
    bars: list[dict[str, object]] = []
    volume: list[dict[str, object]] = []
    volume_column = "vol" if "vol" in data.columns else "volume" if "volume" in data.columns else None
    for row in data.itertuples(index=False):
        values = {name: _finite_number(getattr(row, name)) for name in ("open", "high", "low", "close")}
        if any(value is None or value <= 0 for value in values.values()):
            raise ValueError('chart frame contains invalid OHLC prices')
        if values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]) or values["high"] < values["low"]:
            raise ValueError("chart frame contains invalid OHLC relationships")
        time = row.trade_date.strftime("%Y-%m-%d")
        bars.append({"time": time, **values})
        if volume_column is not None:
            volume_value = _finite_number(getattr(row, volume_column))
            if pd.notna(getattr(row, volume_column)) and (volume_value is None or volume_value < 0):
                raise ValueError('chart frame contains invalid volume')
            if volume_value is not None:
                volume.append({"time": time, "value": volume_value, "color": "#e45756" if values["close"] >= values["open"] else "#2a9d8f"})
    return bars, volume


def _indicator_payload(frame: pd.DataFrame, symbol: str, as_of: object | None, config: list[dict[str, object]] | None) -> list[dict[str, object]]:
    if frame.empty or not config:
        return []
    data = frame.copy()
    if symbol and "symbol" in data.columns:
        data = data.loc[data["symbol"].astype(str).eq(symbol)].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    if as_of is not None:
        data = data.loc[data["trade_date"] <= pd.Timestamp(as_of)].copy()
    data = data.sort_values("trade_date", kind="stable").reset_index(drop=True)
    normalized = normalize_indicator_config(config)

    def points(column: str) -> list[dict[str, object]]:
        values = pd.to_numeric(calculated[column], errors="coerce")
        return [
            {"time": timestamp.strftime("%Y-%m-%d"), "value": float(value)}
            for timestamp, value in zip(calculated["trade_date"], values)
            if pd.notna(timestamp) and pd.notna(value)
        ]

    output: list[dict[str, object]] = []
    for selection in normalized:
        calculated = calculate_registered_indicators(data, [selection])
        key = selection["key"]
        params = selection["params"]
        if key == "MA":
            period = params["period"]
            series = [{"label": f"MA{period}", "column": f"ma{period}", "color": "#2864D7", "data": points(f"ma{period}")}]
            label = f"MA{period}"
        elif key == "EMA":
            period = params["period"]
            series = [{"label": f"EMA{period}", "column": f"ema{period}", "color": "#14949B", "data": points(f"ema{period}")}]
            label = f"EMA{period}"
        elif key == "BOLL":
            period, stddev = params["period"], params["stddev"]
            series = [
                {"label": f"BOLL upper{period}", "column": f"boll_upper{period}", "color": "#94a3b8", "style": "dashed", "data": points(f"boll_upper{period}")},
                {"label": f"BOLL mid{period}", "column": f"boll_mid{period}", "color": "#64748b", "data": points(f"boll_mid{period}")},
                {"label": f"BOLL lower{period}", "column": f"boll_lower{period}", "color": "#94a3b8", "style": "dashed", "data": points(f"boll_lower{period}")},
            ]
            label = f"BOLL upper{period}"
        elif key == "RSI":
            period = params["period"]
            series = [{"label": f"RSI{period}", "column": f"rsi{period}", "color": "#526C93", "data": points(f"rsi{period}")}]
            label = f"RSI{period}"
        elif key == "MACD":
            fast, slow, signal = params["fast"], params["slow"], params["signal"]
            series = [
                {"label": "MACD", "column": "macd", "color": "#2864D7", "data": points("macd")},
                {"label": "MACD signal", "column": "macd_signal", "color": "#8A6BC6", "data": points("macd_signal")},
                {"label": "MACD hist", "column": "macd_hist", "color": "#8A6BC6", "data": points("macd_hist")},
            ]
            label = "MACD"
        elif key == "KDJ":
            series = [{"label": name, "column": name.lower(), "color": color, "data": points(name.lower())} for name, color in (("K", "#2864D7"), ("D", "#8A6BC6"), ("J", "#8A6BC6"))]
            label = "KDJ"
        elif key == "ATR":
            period = params["period"]
            series = [{"label": f"ATR{period}", "column": f"atr{period}", "color": "#B65269", "data": points(f"atr{period}")}]
            label = f"ATR{period}"
        elif key == "OBV":
            series = [{"label": "OBV", "column": "obv", "color": "#14949B", "data": points("obv")}]
            label = "OBV"
        elif key == "VWAP":
            series = [{"label": "VWAP", "column": "vwap", "color": "#526C93", "data": points("vwap")}]
            label = "VWAP"
        elif key == "ROC":
            period = params["period"]
            series = [{"label": f"ROC{period}", "column": f"roc{period}", "color": "#14949B", "data": points(f"roc{period}")}]
            label = f"ROC{period}"
        elif key == "CCI":
            period = params["period"]
            series = [{"label": f"CCI{period}", "column": f"cci{period}", "color": "#14949B", "data": points(f"cci{period}")}]
            label = f"CCI{period}"
        elif key == "DMI":
            period = params["period"]
            series = [
                {"label": "+DI", "column": f"plus_di{period}", "color": "#2864D7", "data": points(f"plus_di{period}")},
                {"label": "-DI", "column": f"minus_di{period}", "color": "#8A6BC6", "data": points(f"minus_di{period}")},
                {"label": "ADX", "column": f"adx{period}", "color": "#8A6BC6", "data": points(f"adx{period}")},
            ]
            label = f"DMI{period}"
        elif key == "BIAS":
            period = params["period"]
            series = [{"label": f"BIAS{period}", "column": f"bias{period}", "color": "#526C93", "data": points(f"bias{period}")}]
            label = f"BIAS{period}"
        elif key == "WR":
            period = params["period"]
            series = [{"label": f"WR{period}", "column": f"wr{period}", "color": "#14949B", "data": points(f"wr{period}")}]
            label = f"WR{period}"
        elif key == "DONCHIAN":
            period = params["period"]
            series = [
                {"label": f"Donchian upper{period}", "column": f"donchian_upper{period}", "color": "#94a3b8", "style": "dashed", "data": points(f"donchian_upper{period}")},
                {"label": f"Donchian middle{period}", "column": f"donchian_middle{period}", "color": "#64748b", "data": points(f"donchian_middle{period}")},
                {"label": f"Donchian lower{period}", "column": f"donchian_lower{period}", "color": "#94a3b8", "style": "dashed", "data": points(f"donchian_lower{period}")},
            ]
            label = f"Donchian{period}"
        elif key == "VOL_MA":
            period = params["period"]
            series = [{"label": f"VOL MA{period}", "column": f"vol_ma{period}", "color": "#8A6BC6", "data": points(f"vol_ma{period}")}]
            label = f"VOL MA{period}"
        elif key == "VOLUME_RATIO":
            period = params["period"]
            series = [{"label": f"Volume Ratio{period}", "column": f"volume_ratio{period}", "color": "#14949B", "data": points(f"volume_ratio{period}")}]
            label = f"Volume Ratio{period}"
        else:
            continue
        output.append({"key": key, "pane": "overlay" if key in {"MA", "EMA", "BOLL", "VWAP", "DONCHIAN"} else "panel", "label": label, "params": params, "data": series[0]["data"], "series": series})
    return output


def _period_info(period: str, frame: pd.DataFrame, symbol: str, as_of: object | None) -> dict[str, object]:
    labels = {"1d": "日K", "1w": "周K", "1m": "月K"}
    if period not in labels:
        raise ValueError("period must be one of 1d, 1w, 1m")
    if period == "1d" or frame.empty or "is_complete" not in frame.columns:
        incomplete = 0
    else:
        data = frame.copy()
        if symbol and "symbol" in data.columns:
            data = data.loc[data["symbol"].astype(str).eq(symbol)]
        dates = pd.to_datetime(data.get("trade_date"), errors="coerce")
        data = data.loc[dates.notna()].copy()
        if as_of is not None:
            data = data.loc[pd.to_datetime(data["trade_date"]) <= pd.Timestamp(as_of)]
        incomplete = int((~data["is_complete"].astype(bool)).sum())
    return {
        "label": labels[period],
        "basis": "日线原始数据" if period == "1d" else "由日线聚合",
        "incomplete_bars": incomplete,
    }


def build_ohlcv_payload(
    frame: pd.DataFrame,
    *,
    symbol: str = "",
    as_of: object | None = None,
    events: Sequence[dict[str, object]] | None = None,
    focus_event_id: str | None = None,
    initial_bars: int = 120,
    min_visible_bars: int = 30,
    max_visible_bars: int | None = None,
    indicator_config: list[dict[str, object]] | None = None,
    period: str = "1d",
    data_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a bounded, local-chart-friendly OHLCV and event payload."""
    data_context = dict(data_context or {})
    data_context['price_role'] = 'display_only'
    if frame.attrs.get('return_contract'):
        data_context['research_return_contract'] = dict(frame.attrs['return_contract'])
    bars, volume = _normalise_bars(frame, symbol, as_of)
    minimum, maximum, default_maximum = _validate_zoom(min_visible_bars, max_visible_bars, len(bars))
    period_info = _period_info(period, frame, symbol, as_of)
    if not bars:
        return {
            "symbol": symbol,
            "period": period,
            "period_info": period_info,
            "bars": [],
            "volume": volume,
            "markers": [],
            "events": [],
            "focus_event_id": None,
            "data_context": {"is_realtime": False, **dict(data_context or {})},
            "indicators": [],
            "bounds": {"start": None, "end": None},
            "initial_range": {"from": None, "to": None},
            "zoom": {"min_visible_bars": minimum, "max_visible_bars": maximum, "initial_visible_bars": 1},
            "chart_state": {"version": 1, "period": period, "storage_key": build_chart_state_key(symbol, period, {"start": None, "end": None}, indicator_config), "bounds": {"start": None, "end": None}},
            "density": {"min_bar_spacing": 2.5, "max_bar_spacing": 12},
        }
    initial = max(minimum, min(int(initial_bars), maximum))
    bar_times = {bar["time"] for bar in bars}
    cutoff = bars[-1]["time"]
    public_events, markers = _event_payload(events, bar_times, cutoff)
    focus_id = str(focus_event_id) if focus_event_id is not None else None
    if focus_id and not any(str(event.get("event_id")) == focus_id for event in public_events):
        focus_id = None
    bounds = {"start": bars[0]["time"], "end": bars[-1]["time"]}
    return {
        "symbol": symbol,
        "period": period,
        "period_info": period_info,
        "bars": bars,
        "volume": volume,
        "markers": markers,
        "events": public_events,
        "focus_event_id": focus_id,
        "data_context": {"is_realtime": False, **dict(data_context or {})},
        "indicators": _indicator_payload(frame, symbol, as_of, indicator_config),
        "bounds": bounds,
        "initial_range": {"from": bars[-initial]["time"], "to": bars[-1]["time"]},
        "zoom": {"min_visible_bars": minimum, "max_visible_bars": default_maximum, "initial_visible_bars": initial},
        "chart_state": {"version": 1, "period": period, "storage_key": build_chart_state_key(symbol, period, bounds), "bounds": bounds},
        "density": {"min_bar_spacing": 2.5, "max_bar_spacing": 12},
    }
