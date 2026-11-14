from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from portfolio_app.data_catalog import (
    build_dataset_manifest,
    build_quality_summary,
    generate_seeded_baseline,
    preview_market_import,
    write_dataset_manifest,
)


def test_seeded_baseline_is_deterministic_and_large_enough_for_chart_research():
    first = generate_seeded_baseline(sessions=520, seed=2026)
    second = generate_seeded_baseline(sessions=520, seed=2026)

    pd.testing.assert_frame_equal(first, second)
    assert first["symbol"].nunique() >= 8
    assert first["trade_date"].nunique() == 520
    assert len(first) >= 8 * 500
    assert first["trade_date"].is_monotonic_increasing


def test_dataset_manifest_and_quality_summary_capture_coverage_and_gaps(tmp_path: Path):
    frame = generate_seeded_baseline(sessions=80, seed=7)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    frame.loc[len(frame) - 1, "symbol"] = frame.iloc[0]["symbol"]

    quality = build_quality_summary(frame)
    manifest = build_dataset_manifest(
        frame,
        dataset_id="test.baseline",
        display_name="Test baseline",
        source_kind="seeded_demo",
        license_note="generated for tests",
        price_mode="raw",
    )
    destination = tmp_path / "manifest.json"
    write_dataset_manifest(destination, manifest, quality)

    assert quality["symbols"] >= 8
    assert quality["duplicate_key_rows"] >= 2
    assert quality["status"] == "需复核"
    assert manifest.price_mode == "raw"
    payload = destination.read_text(encoding="utf-8")
    assert "test.baseline" in payload
    assert "duplicate_key_rows" in payload


def test_import_preview_is_read_only_and_reports_normalisation(tmp_path: Path):
    source = tmp_path / "input.csv"
    source.write_text(
        "symbol,date,open,high,low,close,volume\n"
        "AAA,20240102,10,11,9,10.5,100\n"
        "AAA,20240102,10,11,9,10.5,100\n"
        "AAA,20240103,10.5,12,10,11,120\n",
        encoding="utf-8",
    )
    before = source.read_bytes()

    preview = preview_market_import(source)

    assert preview["can_import"] is False
    assert preview["raw_rows"] == 3
    assert preview["normalised_rows"] == 2
    assert preview["quality"]["duplicate_key_rows"] >= 2
    assert source.read_bytes() == before
    accepted = preview_market_import(source, duplicate_policy="keep_last")
    assert accepted["can_import"] is True
    assert accepted["normalised_rows"] == 2


def test_import_preview_fails_closed_for_missing_ohlc_columns(tmp_path: Path):
    source = tmp_path / "invalid.csv"
    source.write_text("symbol,date,close\nAAA,20240102,10\n", encoding="utf-8")

    preview = preview_market_import(source)

    assert preview["can_import"] is False
    assert preview['failure']['code'] == 'INPUT_INVALID'
    assert '字段映射' in preview['failure']['action']
    assert preview["frame"].empty


def test_duplicate_does_not_hide_a_missing_symbol_session():
    frame = generate_seeded_baseline(sessions=60)
    frame = pd.concat([frame.iloc[1:], frame.iloc[[2]]], ignore_index=True)
    quality = build_quality_summary(frame)
    assert quality["missing_session_cells"] == 1
    assert 0 <= quality["coverage_ratio"] < 1


@pytest.mark.parametrize("field,value", [
    ("open", -1), ("high", 1), ("low", float("inf")),
    ("close", "bad"), ("trade_date", "bad-date"),
])
def test_preview_rejects_invalid_source_rows(field, value):
    raw = pd.DataFrame({"symbol": ["AAA"], "trade_date": ["2024-01-02"],
                        "open": [10], "high": [12], "low": [9], "close": [11]})
    raw[field] = value
    source = BytesIO(raw.to_csv(index=False).encode())
    source.name = "invalid.csv"
    preview = preview_market_import(source)
    assert preview["can_import"] is False
    assert preview["raw_rows"] == 1
    assert preview["error"]


def test_preview_applies_mapping_and_preserves_stream_and_metadata():
    source = BytesIO(b"ticker,day,o,h,l,c,name\nAAA,20240102,10,12,9,11,Example\n")
    source.name = "mapped.csv"
    source.seek(4)
    preview = preview_market_import(source, column_map={
        "ticker": "symbol", "day": "trade_date", "o": "open", "h": "high", "l": "low", "c": "close"})
    assert source.tell() == 4
    assert preview["can_import"] is True
    assert preview["frame"]["name"].iloc[0] == "Example"


def test_preview_rejects_ambiguous_column_aliases():
    source = BytesIO(b"date,trade_date,open,high,low,close\n20240102,20240102,10,12,9,11\n")
    source.name = "ambiguous.csv"
    preview = preview_market_import(source)
    assert preview["can_import"] is False
    assert preview['failure']['code'] == 'INPUT_INVALID'


def test_quality_survives_csv_roundtrip_and_missing_schema():
    frame = generate_seeded_baseline(sessions=60)
    source = BytesIO(frame.to_csv(index=False).encode())
    quality = build_quality_summary(pd.read_csv(source))
    assert quality["coverage_ratio"] == 1
    assert quality["invalid_ohlc_rows"] == 0
    assert build_quality_summary(pd.DataFrame({"close": [1]}))["status"] != "通过"
