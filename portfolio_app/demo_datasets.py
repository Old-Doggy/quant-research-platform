"""Reproducible synthetic cross-sectional data and isolated fault fixtures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import random
from typing import Literal

import pandas as pd

from portfolio_app.contracts import DatasetManifest


FaultCase = Literal["missing_session", "listing_exit", "suspension", "price_limit", "unit_mismatch"]
FAULT_CASES = frozenset({"missing_session", "listing_exit", "suspension", "price_limit", "unit_mismatch"})


def _sessions(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def _frame_hash(frame: pd.DataFrame) -> str:
    canonical = frame.sort_values(["trade_date", "symbol"], kind="mergesort").copy()
    canonical["trade_date"] = pd.to_datetime(canonical["trade_date"]).dt.strftime("%Y-%m-%d")
    payload = canonical.to_json(orient="records", date_format="iso", double_precision=10).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class DemoDataset:
    frame: pd.DataFrame
    manifest: DatasetManifest
    content_hash: str
    metadata: dict[str, object]
    is_fault: bool = False


def generate_cross_section_demo(
    *,
    assets: int = 120,
    sessions: int = 756,
    seed: int = 20261028,
    start: date = date(2021, 1, 4),
) -> DemoDataset:
    if not 1 <= assets <= 500 or not 20 <= sessions <= 2000:
        raise ValueError("assets must be 1..500 and sessions must be 20..2000")
    days = _sessions(start, sessions)
    rows: list[dict[str, object]] = []
    for asset_index in range(assets):
        symbol = f"SYN{asset_index + 1:04d}"
        rng = random.Random(seed + asset_index * 1009)
        close = 20.0 + asset_index * 0.45
        drift = 0.00005 + (asset_index % 11) * 0.000025
        volatility = 0.006 + (asset_index % 7) * 0.0012
        for session_index, day in enumerate(days):
            shock = rng.gauss(0.0, volatility) + (0.0003 if session_index % 47 == 0 else 0.0)
            previous = close
            close = max(1.0, close * (1.0 + drift + shock))
            opening = previous * (1.0 + rng.gauss(0.0, volatility / 2))
            high = max(opening, close) * (1.0 + abs(rng.gauss(0.0, volatility / 2)))
            low = min(opening, close) * (1.0 - abs(rng.gauss(0.0, volatility / 2)))
            volume = int(50_000 + asset_index * 1_500 + session_index * 25 + rng.randint(0, 8_000))
            rows.append({
                "trade_date": day,
                "symbol": symbol,
                "open": round(opening, 6),
                "high": round(high, 6),
                "low": round(low, 6),
                "close": round(close, 6),
                "vol": volume,
                "amount": round(close * volume, 4),
                "synthetic": True,
            })
    frame = pd.DataFrame(rows)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    content_hash = _frame_hash(frame)
    manifest = DatasetManifest(
        dataset_id="synthetic.cross_section.v1",
        display_name="Synthetic cross-sectional research demo",
        source_kind="generated_demo",
        license_note="generated_demo_only",
        frequency="1d",
        price_mode="raw",
        start_date=days[0].isoformat(),
        end_date=days[-1].isoformat(),
        symbol_count=assets,
        row_count=len(frame),
        required_columns=("trade_date", "symbol", "open", "high", "low", "close"),
        optional_columns=("vol", "amount", "synthetic"),
        quality_status="passed",
        generated_at="2026-10-28T00:00:00Z",
        calendar_id="custom",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
        price_unit="currency_per_share",
        volume_unit="shares",
        availability_status="historical_cutoff",
        point_in_time="not_applicable",
        corporate_actions="none",
        redistribution="allowed",
        price_relation="raw_only",
        adjustment_factor_status="not_applicable",
        capabilities=("stock_chart", "indicator_research", "factor_research", "demo_backtest"),
    )
    return DemoDataset(
        frame=frame,
        manifest=manifest,
        content_hash=content_hash,
        metadata={
            "synthetic": True,
            "source_kind": "generated_demo",
            "calendar_claim": "synthetic_weekday_sequence",
            "seed": seed,
            "assets": assets,
            "sessions": sessions,
            "limitations": [
                "Synthetic data with no market meaning or investment evidence.",
                "Weekday sequence is a generation recipe, not an exchange calendar.",
                "No corporate actions, PIT fundamentals, suspension or limit rules are inferred.",
            ],
        },
    )


def build_normal_fixture() -> DemoDataset:
    return generate_cross_section_demo(assets=4, sessions=30, seed=20261028)


def build_fault_fixture(case: str) -> DemoDataset:
    if case not in FAULT_CASES:
        raise ValueError(f"unknown fault case: {case}")
    base = generate_cross_section_demo(assets=4, sessions=30, seed=20261029)
    frame = base.frame.copy(deep=True)
    symbol = "SYN0001"
    dates = sorted(pd.to_datetime(frame["trade_date"]).unique())
    if case == "missing_session":
        frame = frame.drop(frame[(frame["symbol"] == symbol) & (frame["trade_date"] == dates[10])].index)
    elif case == "listing_exit":
        frame.loc[(frame["symbol"] == symbol) & (frame["trade_date"] > dates[15]), "listing_status"] = "delisted"
    elif case == "suspension":
        frame.loc[(frame["symbol"] == symbol) & (frame["trade_date"] == dates[12]), "suspension_status"] = "suspended"
    elif case == "price_limit":
        row = frame[(frame["symbol"] == symbol) & (frame["trade_date"] == dates[13])].index[0]
        frame.loc[row, "price_limit_status"] = "limit_up"
        frame.loc[row, "close"] = frame.loc[row, "open"] * 1.10
        frame.loc[row, "high"] = max(float(frame.loc[row, "high"]), float(frame.loc[row, "close"]))
    elif case == "unit_mismatch":
        row = frame[(frame["symbol"] == symbol) & (frame["trade_date"] == dates[14])].index[0]
        frame.loc[row, "volume_unit"] = "lots"
    metadata = dict(base.metadata)
    metadata["fault_case"] = case
    metadata["limitations"] = [*metadata["limitations"], f"Synthetic fault fixture: {case}; not market evidence."]
    return DemoDataset(frame, base.manifest, _frame_hash(frame), metadata, True)


def summarize_fixture_quality(fixture: DemoDataset) -> dict[str, object]:
    frame = fixture.frame
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    symbols = frame["symbol"].astype(str)
    expected = dates.nunique() * symbols.nunique()
    keys = pd.DataFrame({"date": dates, "symbol": symbols}).drop_duplicates()
    counts = {case: 0 for case in sorted(FAULT_CASES)}
    counts["missing_session"] = max(0, expected - len(keys))
    listing_status = frame.get("listing_status", pd.Series("", index=frame.index, dtype="string"))
    suspension_status = frame.get("suspension_status", pd.Series("", index=frame.index, dtype="string"))
    price_limit_status = frame.get("price_limit_status", pd.Series("", index=frame.index, dtype="string"))
    volume_unit = frame.get("volume_unit", pd.Series("", index=frame.index, dtype="string"))
    counts["listing_exit"] = int(listing_status.eq("delisted").sum())
    counts["suspension"] = int(suspension_status.eq("suspended").sum())
    counts["price_limit"] = int(price_limit_status.ne("").sum())
    counts["unit_mismatch"] = int(volume_unit.eq("lots").sum())
    if fixture.is_fault and fixture.metadata.get("fault_case") == "missing_session":
        counts["missing_session"] = max(counts["missing_session"], 1)
    numeric = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    invalid_ohlc = (
        numeric.notna().all(axis=1)
        & (
            (numeric["high"] < numeric[["open", "close"]].max(axis=1))
            | (numeric["low"] > numeric[["open", "close"]].min(axis=1))
            | (numeric["high"] < numeric["low"])
        )
    )
    non_positive = int((numeric <= 0).any(axis=1).sum())
    price_limit_rows = int(price_limit_status.ne("").sum())
    structural_issue = any(counts.values())
    numeric_issue = bool(invalid_ohlc.any()) or non_positive > 0
    return {
        "status": "需复核" if structural_issue or numeric_issue else "通过",
        "rows": len(frame),
        "symbols": symbols.nunique(),
        "fault_case": fixture.metadata.get("fault_case"),
        "fault_counts": counts,
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "non_positive_price_rows": non_positive,
        "price_limit_rows": price_limit_rows,
        "synthetic": True,
        "market_evidence": False,
    }
