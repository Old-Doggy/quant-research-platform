"""Read-only data capability profiles for the local research workbench.

The matrix is deliberately about what a dataset can support, not a claim that
every file is clean, licensed, point-in-time safe, or executable. Unknown
properties stay explicit so later research stages can fail closed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from portfolio_app.contracts import (
    ADJUSTMENT_FACTOR_VALUES,
    AVAILABILITY_VALUES,
    CALENDAR_VALUES,
    CORPORATE_ACTION_VALUES,
    DATA_CAPABILITY_VALUES,
    NOT_APPLICABLE,
    MARKET_VALUES,
    POINT_IN_TIME_VALUES,
    PRICE_UNIT_VALUES,
    PRICE_RELATION_VALUES,
    REDISTRIBUTION_VALUES,
    UNKNOWN,
    VOLUME_UNIT_VALUES,
)


MATRIX_KEYS = (
    "dataset_id",
    "display_name",
    "source",
    "license",
    "frequency",
    "price_mode",
    "calendar_id",
    "market",
    "timezone",
    "price_unit",
    "volume_unit",
    "units",
    "coverage_scope",
    "observed_start",
    "observed_end",
    "observed_columns",
    "file_count",
    "cutoff_status",
    "point_in_time",
    "corporate_actions",
    "price_relation",
    "adjustment_factor_status",
    "redistribution",
    "required_columns",
    "optional_columns",
    "quality_status",
    "research_uses",
    "limitations",
)

_PRICE_DIRECTORIES = (
    ("raw", "原始日线行情", "daily_raw_merged"),
    ("qfq", "前复权日线行情", "daily_qfq_merged"),
    ("hfq", "后复权日线行情", "daily_hfq_merged"),
)
_OTHER_DIRECTORIES = (
    ("index_weights", "指数成分权重", "index_weights", ["index_code", "con_code", "trade_date", "weight"], ["universe_research"]),
    ("options_daily", "期权日线与合约资料", "options_daily", ["ts_code", "trade_date", "close"], ["derivatives_research"]),
    ("etf_daily", "ETF日线行情", "etf_daily", ["ts_code", "trade_date", "open", "high", "low", "close"], ["stock_chart", "indicator_research"]),
    ("cb_premium_daily", "可转债溢价日线", "cb_premium_daily", ["ts_code", "trade_date", "close"], ["convertible_bond_research"]),
    ("macro", "宏观与市场宽度输入", "macro", ["trade_date", "series", "value"], ["factor_research", "regime_research"]),
    ("stock_pools", "股票池与候选集合", "stock_pools", ["symbol"], ["universe_research"]),
)
_REQUIRED_COLUMNS = ["trade_date", "symbol", "open", "high", "low", "close"]
_OPTIONAL_COLUMNS = [
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
    "turnover_rate",
    "pe_ttm",
    "pb",
    "roe",
    "dv_ratio",
    "ann_date",
    "holder_ann_date",
]
_OBSERVATION_FILE_LIMIT = 3


def _profile(
    *,
    dataset_id: str,
    display_name: str,
    source: str,
    license_note: str,
    price_mode: str,
    calendar_id: str,
    market: str,
    timezone: str,
    price_unit: str,
    volume_unit: str,
    coverage_scope: str,
    observed_start: str | None,
    observed_end: str | None,
    observed_columns: list[str],
    file_count: int,
    cutoff_status: str,
    point_in_time: str,
    corporate_actions: str,
    price_relation: str,
    adjustment_factor_status: str,
    redistribution: str,
    quality_status: str,
    research_uses: list[str],
    limitations: list[str],
    units: str = "OHLC: price per share; vol: source-defined volume; amount: source-defined turnover",
) -> dict[str, object]:
    return {
        "dataset_id": dataset_id,
        "display_name": display_name,
        "source": source,
        "license": license_note,
        "frequency": "1d",
        "price_mode": price_mode,
        "calendar_id": calendar_id,
        "market": market,
        "timezone": timezone,
        "price_unit": price_unit,
        "volume_unit": volume_unit,
        "units": units,
        "coverage_scope": coverage_scope,
        "observed_start": observed_start,
        "observed_end": observed_end,
        "observed_columns": list(observed_columns),
        "file_count": int(file_count),
        "cutoff_status": cutoff_status,
        "point_in_time": point_in_time,
        "corporate_actions": corporate_actions,
        "price_relation": price_relation,
        "adjustment_factor_status": adjustment_factor_status,
        "redistribution": redistribution,
        "required_columns": list(_REQUIRED_COLUMNS),
        "optional_columns": list(_OPTIONAL_COLUMNS),
        "quality_status": quality_status,
        "research_uses": list(research_uses),
        "limitations": list(limitations),
    }


def _demo_profile() -> dict[str, object]:
    return _profile(
        dataset_id="seeded.demo.baseline.v1",
        display_name="Seeded multi-symbol research baseline",
        source="generated_demo",
        license_note="generated_demo_only",
        price_mode="raw",
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
        price_unit="currency_per_share",
        volume_unit="shares",
        coverage_scope="contract_defined",
        observed_start="2024-01-02",
        observed_end=None,
        observed_columns=[*_REQUIRED_COLUMNS, "vol", "amount"],
        file_count=0,
        cutoff_status="known",
        point_in_time=NOT_APPLICABLE,
        corporate_actions=NOT_APPLICABLE,
        price_relation="raw_only",
        adjustment_factor_status=NOT_APPLICABLE,
        redistribution="allowed",
        quality_status="known",
        research_uses=["stock_chart", "indicator_research", "demo_backtest"],
        limitations=[
            "Synthetic data with no market or investment meaning.",
            "The generated end date depends on the requested session count and is not a live cutoff.",
            "No real corporate-action ledger or point-in-time fundamental history is included.",
        ],
    )


def _local_profile(
    mode: str,
    directory_name: str,
    file_count: int,
    observed_columns: list[str],
    observed_start: str | None,
    observed_end: str | None,
) -> dict[str, object]:
    return _profile(
        dataset_id=f"local.{directory_name}",
        display_name=f"Local {mode} daily bars",
        source="local_directory",
        license_note=UNKNOWN,
        price_mode=mode,
        calendar_id=UNKNOWN,
        market=UNKNOWN,
        timezone=UNKNOWN,
        price_unit="source_defined",
        volume_unit="source_defined",
        coverage_scope="directory_observed",
        observed_start=observed_start,
        observed_end=observed_end,
        observed_columns=observed_columns,
        file_count=file_count,
        cutoff_status=UNKNOWN,
        point_in_time=UNKNOWN,
        corporate_actions=UNKNOWN,
        price_relation="raw_only" if mode == "raw" else "adjusted_only",
        adjustment_factor_status=NOT_APPLICABLE if mode == "raw" else UNKNOWN,
        redistribution=UNKNOWN,
        quality_status=UNKNOWN,
        research_uses=["stock_chart", "indicator_research", "local_backtest_input"],
        limitations=[
            f"Directory observed with {file_count} file(s); schema/date metadata was sampled from at most {_OBSERVATION_FILE_LIMIT} file(s).",
            "Source license, data cutoff, point-in-time availability and corporate-action completeness require dataset-level review.",
            "Adjusted prices must not be used as a direct substitute for raw-price share accounting.",
        ],
    )


def _other_profile(
    dataset_id: str,
    display_name: str,
    directory_name: str,
    required_columns: list[str],
    research_uses: list[str],
    file_count: int,
    observed_columns: list[str],
    observed_start: str | None,
    observed_end: str | None,
    units: str,
) -> dict[str, object]:
    profile = _profile(
        dataset_id=f"local.{dataset_id}",
        display_name=display_name,
        source="local_directory",
        license_note=UNKNOWN,
        price_mode="unknown",
        calendar_id=UNKNOWN,
        market=UNKNOWN,
        timezone=UNKNOWN,
        price_unit=UNKNOWN,
        volume_unit=UNKNOWN,
        coverage_scope="directory_observed",
        observed_start=observed_start,
        observed_end=observed_end,
        observed_columns=observed_columns,
        file_count=file_count,
        cutoff_status=UNKNOWN,
        point_in_time=UNKNOWN,
        corporate_actions=UNKNOWN,
        price_relation=UNKNOWN,
        adjustment_factor_status=UNKNOWN,
        redistribution=UNKNOWN,
        quality_status=UNKNOWN,
        research_uses=research_uses,
        limitations=[
            f"Directory observed with {file_count} file(s); schema/date metadata was sampled from at most {_OBSERVATION_FILE_LIMIT} file(s).",
            "Source license, data cutoff, point-in-time availability and corporate-action completeness require dataset-level review.",
        ],
        units=units,
    )
    profile["required_columns"] = list(required_columns)
    return profile


def _validate_profile(profile: dict[str, object]) -> None:
    if tuple(profile) != MATRIX_KEYS:
        raise ValueError("data capability profile keys do not match the fixed schema")
    if profile["cutoff_status"] not in AVAILABILITY_VALUES:
        raise ValueError("cutoff_status must be known, unknown, or not_applicable")
    if profile["point_in_time"] not in POINT_IN_TIME_VALUES:
        raise ValueError("point_in_time must be known, unknown, or not_applicable")
    if profile["corporate_actions"] not in CORPORATE_ACTION_VALUES:
        raise ValueError("corporate_actions must be known, unknown, or not_applicable")
    if profile["price_relation"] not in PRICE_RELATION_VALUES:
        raise ValueError("price_relation is invalid")
    if profile["adjustment_factor_status"] not in ADJUSTMENT_FACTOR_VALUES:
        raise ValueError("adjustment_factor_status is invalid")
    if profile["calendar_id"] not in CALENDAR_VALUES:
        raise ValueError("calendar_id is invalid")
    if profile["market"] not in MARKET_VALUES:
        raise ValueError("market is invalid")
    if profile["price_unit"] not in PRICE_UNIT_VALUES:
        raise ValueError("price_unit is invalid")
    if profile["volume_unit"] not in VOLUME_UNIT_VALUES:
        raise ValueError("volume_unit is invalid")
    if profile["redistribution"] not in REDISTRIBUTION_VALUES:
        raise ValueError("redistribution is invalid")
    if not profile["timezone"]:
        raise ValueError("timezone is required")
    if not set(profile["research_uses"]).issubset(DATA_CAPABILITY_VALUES):
        raise ValueError("research_uses contains an invalid capability")
    if profile["observed_start"] is not None and profile["observed_end"] is not None:
        if str(profile["observed_end"]) < str(profile["observed_start"]):
            raise ValueError("observed_end cannot precede observed_start")
    if not profile["limitations"]:
        raise ValueError("every capability profile requires limitations")


def _validated(profiles: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for profile in profiles:
        _validate_profile(profile)
        result.append(profile)
    return result


def build_capability_matrix() -> list[dict[str, object]]:
    """Return capability profiles that do not require access to local files."""
    return _validated([_demo_profile()])


def scan_local_data_capabilities(data_root: str | Path) -> list[dict[str, object]]:
    """Scan known data directories without reading or modifying their files.

    The result intentionally omits the root path and file names. A missing
    root is an empty observation; a file passed as the root is a caller error.
    """
    root = Path(data_root)
    if not root.exists():
        return []
    if not root.is_dir():
        raise NotADirectoryError(root)

    profiles = []
    for mode, _display_name, directory_name in _PRICE_DIRECTORIES:
        directory = root / directory_name
        if directory.is_dir():
            files = [item for item in directory.iterdir() if item.is_file()]
            observed = _observe_files(files[:_OBSERVATION_FILE_LIMIT])
            profiles.append(_local_profile(
                mode,
                directory_name,
                len(files),
                observed["columns"],
                observed["start"],
                observed["end"],
            ))
    for dataset_id, display_name, directory_name, required_columns, research_uses in _OTHER_DIRECTORIES:
        directory = root / directory_name
        if directory.is_dir():
            files = [item for item in directory.iterdir() if item.is_file()]
            observed = _observe_files(files[:_OBSERVATION_FILE_LIMIT])
            profiles.append(_other_profile(
                dataset_id,
                display_name,
                directory_name,
                required_columns,
                research_uses,
                len(files),
                observed["columns"],
                observed["start"],
                observed["end"],
                _units_for_dataset(dataset_id),
            ))
    return _validated(profiles)


def _observe_files(files: list[Path]) -> dict[str, object]:
    """Inspect small structural metadata without loading an entire dataset."""
    columns: set[str] = set()
    dates: list[pd.Timestamp] = []
    for path in files:
        suffix = path.suffix.lower()
        try:
            if suffix == ".csv":
                header = pd.read_csv(path, nrows=0)
                columns.update(str(column) for column in header.columns)
                sample = pd.read_csv(path, usecols=lambda column: str(column) in {"trade_date", "date"})
                if not sample.empty:
                    date_column = "trade_date" if "trade_date" in sample.columns else "date"
                    dates.extend(_parse_dates(sample[date_column]))
            elif suffix in {".parquet", ".pq"}:
                import pyarrow.parquet as parquet

                parquet_file = parquet.ParquetFile(path)
                columns.update(str(column) for column in parquet_file.schema.names)
                date_index = parquet_file.schema.names.index("trade_date") if "trade_date" in parquet_file.schema.names else -1
                if date_index >= 0:
                    for batch in parquet_file.iter_batches(columns=["trade_date"], batch_size=100_000):
                        dates.extend(_parse_dates(batch.column(0).to_pandas()))
        except Exception:
            # A failed optional observation is represented as unknown, not as a
            # false claim about columns or coverage.
            continue
    return {
        "columns": sorted(columns),
        "start": min(dates).strftime("%Y-%m-%d") if dates else None,
        "end": max(dates).strftime("%Y-%m-%d") if dates else None,
    }


def _parse_dates(values: object) -> list[pd.Timestamp]:
    series = pd.Series(values)
    text = series.astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    parsed = parsed.fillna(pd.to_datetime(text, errors="coerce"))
    return parsed.dropna().tolist()


def _units_for_dataset(dataset_id: str) -> str:
    if dataset_id == "index_weights":
        return "weight: source-defined index constituent weight"
    if dataset_id == "options_daily":
        return "quote fields: contract-defined price/quantity units; exercise_price: contract price"
    if dataset_id == "macro":
        return "series values: source-defined macro indicator units"
    if dataset_id == "stock_pools":
        return "symbol: instrument identifier; count: constituent count"
    return "OHLC: price per share; vol: source-defined volume; amount: source-defined turnover"
