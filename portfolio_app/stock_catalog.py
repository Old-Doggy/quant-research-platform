"""Pure stock-directory and quote-view helpers for the local workbench."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import pandas as pd


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _name_map(names: Mapping[str, object] | pd.DataFrame | None) -> dict[str, str]:
    if names is None:
        return {}
    if isinstance(names, pd.DataFrame):
        if not {"symbol", "name"}.issubset(names.columns):
            if {"ts_code", "name"}.issubset(names.columns):
                return dict(zip(names["ts_code"].map(_text), names["name"].map(_text)))
            return {}
        return dict(zip(names["symbol"].map(_text), names["name"].map(_text)))
    return {_text(key): _text(value) for key, value in names.items()}


def _symbol_column(frame: pd.DataFrame) -> pd.Series:
    if "symbol" in frame.columns:
        return frame["symbol"].map(_text)
    if "ts_code" in frame.columns:
        return frame["ts_code"].map(_text)
    return pd.Series("", index=frame.index, dtype="string")


def _sorted_frame(frame: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    data["_symbol"] = _symbol_column(data)
    data["_date"] = pd.to_datetime(data.get("trade_date"), errors="coerce")
    data = data.loc[data["_symbol"].ne("") & data["_date"].notna()]
    if symbol is not None:
        data = data.loc[data["_symbol"].eq(str(symbol))]
    return data.sort_values(["_symbol", "_date"], kind="stable")


def build_stock_catalog(
    frame: pd.DataFrame,
    *,
    names: Mapping[str, object] | pd.DataFrame | None = None,
    price_unit: str = "unknown",
    volume_unit: str = "unknown",
) -> list[dict[str, object]]:
    """Build a stable, latest-quote directory without strategy execution."""
    data = _sorted_frame(frame)
    name_map = _name_map(names)
    result: list[dict[str, object]] = []
    for symbol, group in data.groupby("_symbol", sort=True):
        latest = group.iloc[-1]
        previous = _number(latest.get("pre_close"))
        if previous is None and len(group) > 1:
            previous = _number(group.iloc[-2].get("close"))
        close = _number(latest.get("close"))
        change = close / previous - 1 if close is not None and previous not in (None, 0) else None
        result.append(
            {
                "symbol": str(symbol),
                "name": name_map.get(str(symbol), ""),
                "latest_date": latest["_date"].strftime("%Y-%m-%d"),
                "close": close,
                "change": change,
                "price_unit": price_unit or "unknown",
                "volume_unit": volume_unit or "unknown",
                "observations": int(len(group)),
            }
        )
    return result


def search_stock_catalog(catalog: Sequence[Mapping[str, object]], query: str) -> list[dict[str, object]]:
    """Search by symbol or display name while preserving catalog order."""
    needle = str(query or "").strip().casefold()
    if not needle:
        return [dict(item) for item in catalog]
    return [
        dict(item)
        for item in catalog
        if needle in str(item.get("symbol", "")).casefold()
        or needle in str(item.get("name", "")).casefold()
    ]


def build_market_view(
    frame: pd.DataFrame,
    *,
    symbol: str,
    name: str = "",
    price_unit: str = "unknown",
    volume_unit: str = "unknown",
) -> dict[str, object]:
    """Return a pure historical quote page payload.

    Strategy and signal fields are deliberately absent. The strategy workspace
    remains the separate place where simulated research state is shown.
    """
    data = _sorted_frame(frame, symbol)
    base = {
        "symbol": str(symbol or ""),
        "name": str(name or ""),
        "price_unit": price_unit or "unknown",
        "volume_unit": volume_unit or "unknown",
        "history": [],
    }
    if not str(symbol or "").strip():
        return {**base, "status": "EMPTY", "message": "请选择一个标的。"}
    if frame is None or frame.empty:
        return {**base, "status": "EMPTY", "message": "当前数据集没有可用行情。"}
    if data.empty:
        return {**base, "status": "NOT_FOUND", "message": "当前数据集中找不到该标的。"}

    history: list[dict[str, object]] = []
    for _, row in data.iterrows():
        history.append(
            {
                "date": row["_date"].strftime("%Y-%m-%d"),
                "open": _number(row.get("open")),
                "high": _number(row.get("high")),
                "low": _number(row.get("low")),
                "close": _number(row.get("close")),
                "volume": _number(row.get("vol")),
            }
        )
    latest = data.iloc[-1]
    close = _number(latest.get("close"))
    previous = _number(latest.get("pre_close"))
    if previous is None and len(data) > 1:
        previous = _number(data.iloc[-2].get("close"))
    return {
        **base,
        "status": "READY",
        "message": "历史行情",
        "latest_date": latest["_date"].strftime("%Y-%m-%d"),
        "quote": {
            "close": close,
            "previous_close": previous,
            "change": close / previous - 1 if close is not None and previous not in (None, 0) else None,
            "open": _number(latest.get("open")),
            "high": _number(latest.get("high")),
            "low": _number(latest.get("low")),
            "volume": _number(latest.get("vol")),
            "price_unit": price_unit or "unknown",
            "volume_unit": volume_unit or "unknown",
        },
        "history": history,
    }
