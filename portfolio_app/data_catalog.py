from __future__ import annotations

from datetime import date, timedelta
import json
import numpy as np
from pathlib import Path
import random
import zipfile
from typing import BinaryIO

import pandas as pd

from portfolio_app.contracts import DatasetManifest
from portfolio_app.data import _normalise_column_name, build_data_quality_report, normalise_market_frame


BASELINE_SYMBOLS = (
    ("DEMO_TREND", 100.0, 0.00045, 0.010),
    ("DEMO_VALUE", 82.0, 0.00025, 0.008),
    ("DEMO_DEFENSIVE", 118.0, 0.00020, 0.005),
    ("DEMO_VOLATILE", 64.0, 0.00010, 0.018),
    ("DEMO_MOMENTUM", 46.0, 0.00055, 0.013),
    ("DEMO_REVERSAL", 136.0, 0.00005, 0.012),
    ("DEMO_CYCLICAL", 72.0, 0.00035, 0.015),
    ("DEMO_STABLE", 156.0, 0.00018, 0.004),
)


def _trading_days(start: date, sessions: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < sessions:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def generate_seeded_baseline(
    sessions: int = 520,
    seed: int = 2026,
    start: date = date(2024, 1, 2),
) -> pd.DataFrame:
    """Generate a deterministic multi-symbol daily-bar baseline for local research."""
    if sessions < 60:
        raise ValueError("sessions must be at least 60")
    days = _trading_days(start, sessions)
    rows: list[dict[str, object]] = []
    for symbol_index, (symbol, base, drift, volatility) in enumerate(BASELINE_SYMBOLS):
        rng = random.Random(seed + symbol_index * 101)
        close = base
        for index, day in enumerate(days):
            regime = 0.0008 if (index // 80) % 2 == 0 else -0.00035
            shock = rng.gauss(0.0, volatility) + 0.0006 * (index % 17 == 0)
            previous = close
            close = max(5.0, close * (1.0 + drift + regime + shock))
            opening = previous * (1.0 + rng.gauss(0.0, volatility / 2))
            high = max(opening, close) * (1.0 + abs(rng.gauss(0.0, volatility)))
            low = min(opening, close) * (1.0 - abs(rng.gauss(0.0, volatility)))
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": day,
                    "open": round(opening, 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "vol": int(100_000 + symbol_index * 12_000 + index * 140 + rng.randint(0, 20_000)),
                    "amount": round(close * (100_000 + index * 140), 2),
                }
            )
    return normalise_market_frame(pd.DataFrame(rows), source_name="seeded baseline")


def build_quality_summary(frame: pd.DataFrame) -> dict[str, object]:
    """Return the existing quality report plus dataset-level coverage fields."""
    report_frame = frame.copy()
    if "trade_date" in report_frame.columns:
        report_frame["trade_date"] = pd.to_datetime(report_frame["trade_date"], errors="coerce")
    report = build_data_quality_report(report_frame)
    result = dict(report)
    if "symbol" not in report_frame.columns and "ts_code" in report_frame.columns:
        report_frame["symbol"] = report_frame["ts_code"].astype(str)
    if report_frame.empty or "trade_date" not in report_frame.columns or "symbol" not in report_frame.columns:
        result.update({"date_count": 0, "missing_session_cells": 0})
        return result
    dates = report_frame["trade_date"].dropna().drop_duplicates().sort_values()
    symbols = report_frame["symbol"].astype(str).drop_duplicates()
    expected_cells = len(dates) * len(symbols)
    result["date_count"] = int(len(dates))
    unique_keys = report_frame.assign(
        _symbol=report_frame["symbol"].astype(str),
        _date=report_frame["trade_date"],
    ).drop_duplicates(["_date", "_symbol"])
    result["missing_session_cells"] = int(max(0, expected_cells - len(unique_keys)))
    result["coverage_ratio"] = float(len(unique_keys) / expected_cells) if expected_cells else 0.0
    if result["missing_session_cells"] > 0 and result["status"] == "通过":
        result["status"] = "需复核"
    return result


def build_dataset_manifest(
    frame: pd.DataFrame,
    *,
    dataset_id: str,
    display_name: str,
    source_kind: str,
    license_note: str,
    price_mode: str = "raw",
    generated_at: str = "2026-10-16T00:00:00Z",
    calendar_id: str = "unknown",
    market: str = "unknown",
    timezone: str = "unknown",
    price_unit: str = "unknown",
    volume_unit: str = "unknown",
    availability_status: str = "unknown",
    point_in_time: str = "unknown",
    corporate_actions: str = "unknown",
    redistribution: str = "unknown",
    price_relation: str = "unknown",
    adjustment_factor_status: str = "unknown",
    capabilities: tuple[str, ...] = (),
) -> DatasetManifest:
    quality = build_quality_summary(frame)
    required_columns = ("trade_date", "symbol", "open", "high", "low", "close")
    optional_columns = tuple(column for column in ("vol", "amount", "pre_close", "roe", "pb") if column in frame.columns)
    return DatasetManifest(
        dataset_id=dataset_id,
        display_name=display_name,
        source_kind=source_kind,
        license_note=license_note,
        frequency="1d",
        price_mode=price_mode,
        start_date=str(quality.get("start") or "1970-01-01"),
        end_date=str(quality.get("end") or "1970-01-01"),
        symbol_count=int(quality.get("symbols", 0)),
        row_count=int(quality.get("rows", 0)),
        required_columns=required_columns,
        optional_columns=optional_columns,
        quality_status="passed" if quality.get("status") == "通过" else "warning",
        generated_at=generated_at,
        calendar_id=calendar_id,
        market=market,
        timezone=timezone,
        price_unit=price_unit,
        volume_unit=volume_unit,
        availability_status=availability_status,
        point_in_time=point_in_time,
        corporate_actions=corporate_actions,
        redistribution=redistribution,
        price_relation=price_relation,
        adjustment_factor_status=adjustment_factor_status,
        capabilities=capabilities,
    )


def write_dataset_manifest(path: str | Path, manifest: DatasetManifest, quality: dict[str, object]) -> None:
    """Write a small manifest beside a dataset; never writes the source data."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"manifest": manifest.to_dict(), "quality": quality}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_import_frame(file_object: str | Path | BinaryIO) -> tuple[pd.DataFrame, int]:
    source = getattr(file_object, "name", str(file_object))
    suffix = Path(str(source)).suffix.lower()
    original_position = file_object.tell() if hasattr(file_object, "tell") else None
    try:
        if hasattr(file_object, "seek"):
            file_object.seek(0)
        if isinstance(file_object, (str, Path)):
            size = Path(file_object).stat().st_size
        else:
            file_object.seek(0, 2)
            size = file_object.tell()
            file_object.seek(0)
        if size > 64 * 1024 * 1024:
            raise ValueError('import exceeds 64 MiB file limit')
        if suffix in {'.parquet', '.pq'}:
            import pyarrow.parquet as pq
            metadata = pq.ParquetFile(file_object).metadata
            if metadata.num_rows > 150000 or metadata.num_columns > 128 or sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups)) > 96 * 1024 * 1024:
                raise ValueError('import exceeds table limits')
            if hasattr(file_object, 'seek'):
                file_object.seek(0)
        if suffix == '.xlsx':
            with zipfile.ZipFile(file_object) as source:
                if sum(item.file_size for item in source.infolist()) > 96 * 1024 * 1024:
                    raise ValueError('expanded import exceeds memory limit')
            if hasattr(file_object, 'seek'):
                file_object.seek(0)
        raw = pd.read_parquet(file_object) if suffix in {".parquet", ".pq"} else (
            pd.read_excel(file_object, dtype=object, nrows=150001) if suffix in {".xlsx", ".xls"} else pd.read_csv(file_object, dtype=object, nrows=150001)
        )
        if len(raw) > 150000 or raw.shape[1] > 128 or raw.memory_usage(index=True, deep=True).sum() > 96 * 1024 * 1024:
            raise ValueError('import exceeds table limits')
        return raw, int(len(raw))
    finally:
        if original_position is not None:
            file_object.seek(original_position)


def import_source_columns(file_object: str | Path | BinaryIO) -> list[str]:
    """Inspect original field names without consuming the upload stream."""
    raw, _ = _read_import_frame(file_object)
    return [str(column) for column in raw.columns]


def _prepare_import_columns(raw: pd.DataFrame, column_map: dict[str, str] | None) -> pd.DataFrame:
    mapped = [
        _normalise_column_name(column_map.get(str(column), str(column)) if column_map else str(column))
        for column in raw.columns
    ]
    duplicates = sorted({column for column in mapped if mapped.count(column) > 1})
    if duplicates:
        raise ValueError(f"ambiguous columns after mapping: {', '.join(duplicates)}")
    result = raw.copy()
    result.columns = mapped
    return result


def _validate_import_source(frame: pd.DataFrame) -> int:
    required = {"trade_date", "open", "high", "low", "close"}
    symbol_column = "ts_code" if "ts_code" in frame.columns else "symbol" if "symbol" in frame.columns else None
    missing = sorted(required - set(frame.columns))
    if symbol_column is None:
        missing.append("symbol")
    if missing:
        raise ValueError(f"source is missing required columns: {', '.join(missing)}")
    dates_text = frame["trade_date"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    dates = pd.to_datetime(dates_text, format="%Y%m%d", errors="coerce")
    dates = dates.fillna(pd.to_datetime(dates_text, errors="coerce"))
    if dates.isna().any():
        raise ValueError("source contains invalid trade_date values")
    prices = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(prices.to_numpy(dtype=float)).all():
        raise ValueError("source contains invalid OHLC values")
    if (prices <= 0).any().any():
        raise ValueError("source OHLC values must be positive")
    if (prices["high"] < prices[["open", "close"]].max(axis=1)).any() or (prices["low"] > prices[["open", "close"]].min(axis=1)).any() or (prices["high"] < prices["low"]).any():
        raise ValueError("source contains invalid OHLC relationships")
    if frame[symbol_column].isna().any() or frame[symbol_column].astype(str).str.strip().eq("").any():
        raise ValueError("source contains missing symbol values")
    symbols = frame[symbol_column].astype(str).str.strip().str.upper()
    keys = pd.DataFrame({"_date": dates, "_symbol": symbols})
    return int(keys.duplicated(["_date", "_symbol"], keep=False).sum())


def preview_market_import(
    file_object: str | Path | BinaryIO,
    *,
    duplicate_policy: str = "reject",
    column_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Read, normalise and validate an import without mutating its source."""
    raw_rows = 0
    frame = pd.DataFrame()
    prepared = pd.DataFrame()
    quality: dict[str, object] = {}
    try:
        source = getattr(file_object, "name", str(file_object))
        raw, raw_rows = _read_import_frame(file_object)
        prepared = _prepare_import_columns(raw, column_map)
        raw_duplicate_key_rows = _validate_import_source(prepared)
        frame = normalise_market_frame(prepared, source_name=str(source))
        if raw_duplicate_key_rows and duplicate_policy == 'keep_last':
            frame.attrs['normalization_audit']['duplicate_policy'] = 'keep_last_confirmed'
        quality = build_quality_summary(frame)
        quality["duplicate_key_rows"] = max(int(quality.get("duplicate_key_rows", 0)), raw_duplicate_key_rows)
        if raw_duplicate_key_rows:
            quality["status"] = "需复核"
        if duplicate_policy not in {"reject", "keep_last"}:
            raise ValueError("duplicate_policy must be reject or keep_last")
        return {
            "can_import": not raw_duplicate_key_rows or duplicate_policy == "keep_last",
            "error": "source contains duplicate date/symbol keys" if raw_duplicate_key_rows and duplicate_policy == "reject" else "",
            "raw_rows": raw_rows,
            "normalised_rows": int(len(frame)),
            "columns": list(prepared.columns),
            "quality": quality,
            "frame": frame,
        }
    except Exception as exc:  # noqa: BLE001 - preview must report user data errors
        from .research_diagnostics import capture_error
        failure = capture_error(exc, operation='import')
        return {
            "can_import": False,
            "error": failure['message'],
            "failure": failure,
            "raw_rows": raw_rows,
            "normalised_rows": len(frame),
            "columns": list(prepared.columns),
            "quality": quality,
            "frame": frame,
        }
