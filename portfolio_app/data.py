from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd


REQUIRED_PRICE_COLUMNS = ("trade_date", "open", "high", "low", "close")
OPTIONAL_COLUMNS = (
    "pre_close",
    "vol",
    "amount",
    "turnover_rate",
    "pe_ttm",
    "pb",
    "roe",
    "dv_ratio",
    "dt_netprofit_yoy",
    "ts_code",
)


def _normalise_code(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    if "." in text:
        return text
    digits = "".join(character for character in text if character.isdigit())
    return digits.zfill(6) if digits else text


def _normalise_column_name(value: object) -> str:
    text = str(value).strip().lower().replace(" ", "_")
    aliases = {
        "date": "trade_date",
        "datetime": "trade_date",
        "日期": "trade_date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "vol",
        "volume": "vol",
        "volumn": "vol",
        "成交额": "amount",
        "turnover": "turnover_rate",
        "代码": "ts_code",
        "股票代码": "ts_code",
        "symbol": "ts_code",
        "换手率": "turnover_rate",
        "市盈率": "pe_ttm",
        "市净率": "pb",
        "净资产收益率": "roe",
        "股息率": "dv_ratio",
    }
    return aliases.get(text, text)


def normalise_market_frame(frame: pd.DataFrame, source_name: str = "local data") -> pd.DataFrame:
    """Convert common local daily-bar layouts into the app's canonical schema."""
    if frame is None or frame.empty:
        raise ValueError(f"{source_name} is empty")

    result = frame.copy()
    result.columns = [_normalise_column_name(column) for column in result.columns]
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in result.columns]
    if missing:
        raise ValueError(f"{source_name} is missing required columns: {', '.join(missing)}")

    date_text = result["trade_date"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    compact_dates = pd.to_datetime(date_text, format="%Y%m%d", errors="coerce")
    result["trade_date"] = compact_dates.fillna(pd.to_datetime(date_text, errors="coerce"))
    result = result.dropna(subset=["trade_date"]).copy()
    for column in OPTIONAL_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    if "ts_code" in result.columns:
        result["ts_code"] = result["ts_code"].map(_normalise_code)
    numeric_columns = [column for column in result.columns if column != "trade_date" and column != "ts_code"]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    dedupe_columns = ["trade_date", "ts_code"] if result["ts_code"].ne("").any() else ["trade_date"]
    result = result.sort_values(dedupe_columns).drop_duplicates(dedupe_columns, keep="last")
    previous_close = result.groupby("ts_code", dropna=False)["close"].shift(1)
    result["pre_close"] = result["pre_close"].fillna(previous_close)
    result["return"] = result.groupby("ts_code", dropna=False)["close"].pct_change()
    result["symbol"] = result["ts_code"].fillna("").astype(str)
    return result.reset_index(drop=True)


def build_data_quality_report(frame: pd.DataFrame) -> dict[str, object]:
    """Summarise common daily-bar data issues after canonical normalisation."""
    if frame is None:
        raise ValueError("frame is required")

    required = list(REQUIRED_PRICE_COLUMNS)
    missing_columns = [column for column in required if column not in frame.columns]
    if missing_columns:
        return {
            "status": "需复核",
            "rows": int(len(frame)),
            "symbols": 0,
            "missing_columns": missing_columns,
            "missing_required_value_rows": int(len(frame)),
            "invalid_ohlc_rows": 0,
            "non_positive_close_rows": 0,
            "duplicate_key_rows": 0,
            "non_monotonic_rows": 0,
        }

    result = frame.copy()
    symbol = result.get("symbol", result.get("ts_code", pd.Series("", index=result.index)))
    symbol = symbol.fillna("").astype(str)
    price_columns = ["open", "high", "low", "close"]
    missing_required_value_rows = int(result[required].isna().any(axis=1).sum())
    invalid_ohlc = (
        result[price_columns].notna().all(axis=1)
        & (
            (result["high"] < result[["open", "close"]].max(axis=1))
            | (result["low"] > result[["open", "close"]].min(axis=1))
            | (result["high"] < result["low"])
        )
    )
    non_positive_close_rows = int(result["close"].le(0).fillna(False).sum())
    duplicate_key_rows = int(result.assign(_quality_symbol=symbol).duplicated(["trade_date", "_quality_symbol"], keep=False).sum())

    order_frame = pd.DataFrame({"trade_date": pd.to_datetime(result["trade_date"], errors="coerce"), "_symbol": symbol})
    order_frame["previous_date"] = order_frame.groupby("_symbol", dropna=False)["trade_date"].shift(1)
    non_monotonic_rows = int(order_frame["trade_date"].le(order_frame["previous_date"]).fillna(False).sum())
    issue_fields = {
        "missing_columns": [],
        "missing_required_value_rows": missing_required_value_rows,
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "non_positive_close_rows": non_positive_close_rows,
        "duplicate_key_rows": duplicate_key_rows,
        "non_monotonic_rows": non_monotonic_rows,
    }
    has_issue = any(value for key, value in issue_fields.items() if key != "missing_columns") or bool(issue_fields["missing_columns"])
    return {
        "status": "需复核" if has_issue else "通过",
        "rows": int(len(result)),
        "symbols": int(symbol.nunique()),
        "start": result["trade_date"].min().strftime("%Y-%m-%d") if result["trade_date"].notna().any() else None,
        "end": result["trade_date"].max().strftime("%Y-%m-%d") if result["trade_date"].notna().any() else None,
        **issue_fields,
    }


def build_market_summary(frame: pd.DataFrame) -> dict[str, object]:
    """Return compact summary statistics for an analysis workspace."""
    if frame is None or frame.empty:
        return {"rows": 0, "symbols": 0, "start": None, "end": None, "missing_values": 0}
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    symbol = frame.get("symbol", frame.get("ts_code", pd.Series("", index=frame.index)))
    symbol = symbol.fillna("").astype(str)
    returns = pd.to_numeric(frame.get("return", pd.Series(dtype=float)), errors="coerce")
    return {
        "rows": int(len(frame)),
        "symbols": int(symbol.nunique()),
        "start": dates.min().strftime("%Y-%m-%d") if dates.notna().any() else None,
        "end": dates.max().strftime("%Y-%m-%d") if dates.notna().any() else None,
        "missing_values": int(frame.isna().sum().sum()),
        "positive_return_ratio": float(returns.dropna().gt(0).mean()) if returns.notna().any() else 0.0,
    }


def build_symbol_return_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate comparable buy-and-hold return and risk statistics by symbol."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["symbol", "rows", "total_return", "annualized_return", "annualized_volatility", "max_drawdown"])

    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    symbol = result.get("symbol", result.get("ts_code", pd.Series("", index=result.index)))
    result["symbol"] = symbol.fillna("").astype(str)
    calculated_return = result["close"].groupby(result["symbol"]).pct_change()
    result["return"] = pd.to_numeric(result.get("return", calculated_return), errors="coerce")
    rows: list[dict[str, object]] = []
    for symbol, group in result.sort_values(["symbol", "trade_date"]).groupby("symbol", dropna=False):
        returns = group["return"].fillna(0.0)
        equity = (1.0 + returns).cumprod()
        observations = max(len(group), 1)
        total_return = float(equity.iloc[-1] - 1.0)
        annualized_volatility = float(returns.std(ddof=0) * np.sqrt(252))
        rows.append(
            {
                "symbol": symbol,
                "rows": len(group),
                "start": group["trade_date"].min().strftime("%Y-%m-%d"),
                "end": group["trade_date"].max().strftime("%Y-%m-%d"),
                "total_return": total_return,
                "annualized_return": float(equity.iloc[-1] ** (252 / observations) - 1.0),
                "annualized_volatility": annualized_volatility,
                "max_drawdown": float((equity / equity.cummax() - 1.0).min()),
            }
        )
    return pd.DataFrame(rows).sort_values("total_return", ascending=False).reset_index(drop=True)


def read_market_file(file_object: str | Path | BinaryIO) -> pd.DataFrame:
    """Read CSV, Excel, or Parquet market data and normalise it."""
    source_name = getattr(file_object, "name", str(file_object))
    suffix = Path(str(source_name)).suffix.lower()
    if suffix in {".parquet", ".pq"}:
        frame = pd.read_parquet(file_object)
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(file_object)
    else:
        frame = pd.read_csv(file_object)
    return normalise_market_frame(frame, source_name=source_name)


def list_local_symbols(data_root: str | Path, adjusted: str = "qfq") -> list[str]:
    root = Path(data_root) / f"daily_{adjusted}_merged"
    if not root.exists():
        return []
    return sorted(path.stem for path in root.glob("*.parquet"))


def load_local_symbol(data_root: str | Path, symbol: str, adjusted: str = "qfq") -> pd.DataFrame:
    path = Path(data_root) / f"daily_{adjusted}_merged" / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Local symbol data not found: {path}")
    return read_market_file(path)
