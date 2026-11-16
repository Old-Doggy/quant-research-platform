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
    return text.zfill(6) if text.isdecimal() else text


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
    if result.columns.duplicated().any():
        # Canonical frames contain both symbol and ts_code. Re-reading such a
        # frame is valid only when the aliases describe the same instrument.
        for name in result.columns[result.columns.duplicated()].unique():
            aliases = result.loc[:, result.columns == name]
            if not all(aliases.iloc[:, 0].equals(aliases.iloc[:, i]) for i in range(1, aliases.shape[1])):
                raise ValueError(f"conflicting column aliases: {name}")
        result = result.loc[:, ~result.columns.duplicated()].copy()
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in result.columns]
    if missing:
        raise ValueError(f"{source_name} is missing required columns: {', '.join(missing)}")

    date_text = result["trade_date"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    compact_dates = pd.to_datetime(date_text, format="%Y%m%d", errors="coerce")
    result["trade_date"] = compact_dates.fillna(pd.to_datetime(date_text, errors="coerce"))
    removed_invalid_dates = int(result["trade_date"].isna().sum())
    result = result.dropna(subset=["trade_date"]).copy()
    for column in OPTIONAL_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    if "ts_code" in result.columns:
        result["ts_code"] = result["ts_code"].map(_normalise_code)
    numeric_columns = [
        column for column in (*REQUIRED_PRICE_COLUMNS[1:], *OPTIONAL_COLUMNS)
        if column != "ts_code" and column in result.columns
    ]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    dedupe_columns = ["trade_date", "ts_code"] if result["ts_code"].ne("").any() else ["trade_date"]
    removed_duplicates = int(result.duplicated(dedupe_columns, keep="last").sum())
    result = result.sort_values(dedupe_columns).drop_duplicates(dedupe_columns, keep="last")
    prior = frame.attrs.get("normalization_audit", {})
    result.attrs["normalization_audit"] = {
        "removed_duplicate_rows": removed_duplicates + int(prior.get("removed_duplicate_rows", 0)),
        "removed_invalid_date_rows": removed_invalid_dates + int(prior.get("removed_invalid_date_rows", 0)),
    }
    previous_close = result.groupby("ts_code", dropna=False)["close"].shift(1)
    if frame.attrs.get('previous_close_policy') == 'explicit_source_only.v1':
        result['pre_close'] = pd.to_numeric(result['source_pre_close'], errors='raise') if 'source_pre_close' in result else np.nan
    else:
        result["pre_close"] = result["pre_close"].fillna(previous_close)
    result["return"] = result.groupby("ts_code", dropna=False)["close"].pct_change(fill_method=None)
    result.attrs['return_contract'] = dict(definition='price_return_v1', version='1.0',
        price_basis=frame.attrs.get('research_dataset', {}).get('price_basis', 'unspecified'),
        action_coverage='unknown', first_observation='missing')
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
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    symbol = result.get("symbol", result.get("ts_code", pd.Series("", index=result.index)))
    symbol = symbol.fillna("").astype(str)
    price_columns = ["open", "high", "low", "close"]
    result[price_columns] = result[price_columns].apply(pd.to_numeric, errors="coerce")
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
        "invalid_price_rows": int((~np.isfinite(result[price_columns]) | result[price_columns].le(0)).any(axis=1).sum()),
        "duplicate_key_rows": duplicate_key_rows,
        "non_monotonic_rows": non_monotonic_rows,
        "normalization_removed_duplicate_rows": int(frame.attrs.get("normalization_audit", {}).get("removed_duplicate_rows", 0)),
        "normalization_removed_invalid_date_rows": int(frame.attrs.get("normalization_audit", {}).get("removed_invalid_date_rows", 0)),
        "invalid_activity_rows": int(pd.concat([
            (pd.to_numeric(result[c], errors='coerce').lt(0)
             | (result[c].notna() & ~np.isfinite(pd.to_numeric(result[c], errors='coerce'))))
            for c in ('vol', 'amount', 'turnover_rate') if c in result
        ], axis=1).any(axis=1).sum()) if any(c in result for c in ('vol','amount','turnover_rate')) else 0,
    }
    ignored = {'missing_columns'}
    duplicate_policy = frame.attrs.get('normalization_audit', {}).get('duplicate_policy')
    if duplicate_policy == 'keep_last_confirmed':
        ignored.add('normalization_removed_duplicate_rows')
    has_issue = result.empty or any(value for key, value in issue_fields.items() if key not in ignored) or bool(issue_fields["missing_columns"])
    return {
        "status": "需复核" if has_issue else "通过",
        "rows": int(len(result)),
        "symbols": int(symbol.nunique()),
        "start": result["trade_date"].min().strftime("%Y-%m-%d") if result["trade_date"].notna().any() else None,
        "end": result["trade_date"].max().strftime("%Y-%m-%d") if result["trade_date"].notna().any() else None,
        **issue_fields,
        'normalization_duplicate_policy': duplicate_policy,
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
    calculated_return = result["close"].groupby(result["symbol"]).pct_change(fill_method=None)
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
    from .data_catalog import _read_import_frame
    frame, _ = _read_import_frame(file_object)
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
