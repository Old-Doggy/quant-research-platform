from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import pandas as pd
import pytest

from portfolio_app.data_center import DataCenter, DataCenterBlocked
from portfolio_app.data_catalog import build_dataset_manifest
from portfolio_app.dataset_registry import RegistrationConfirmationRequired
from portfolio_app.temporal_contracts import build_session_calendar


def _source_frame(value: float = 10.0, *, future: bool = False) -> pd.DataFrame:
    available = "2024-01-04T09:00:00+08:00" if future else "2024-01-02T16:00:00+08:00"
    return pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "trade_date": ["20240102", "20240103"],
            "open": [value, value + 0.5],
            "high": [value + 1.0, value + 1.5],
            "low": [value - 1.0, value - 0.5],
            "close": [value + 0.5, value + 1.0],
            "vol": [100, 120],
            "available_at": [available, available],
        }
    )


def _write_csv(path: Path, value: float = 10.0, *, future: bool = False) -> None:
    _source_frame(value, future=future).to_csv(path, index=False)


def _manifest(frame: pd.DataFrame, *, dataset_id: str = "center.demo", redistribution: str = "restricted"):
    return build_dataset_manifest(
        frame,
        dataset_id=dataset_id,
        display_name="Data center demo",
        source_kind="user_import",
        license_note="user supplied",
        price_mode="raw",
        calendar_id="custom",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
        price_unit="currency_per_share",
        volume_unit="shares",
        availability_status="historical_cutoff",
        point_in_time="known",
        corporate_actions="unknown",
        redistribution=redistribution,
        price_relation="raw_only",
        adjustment_factor_status="not_applicable",
    )


def test_data_center_previews_csv_xlsx_and_parquet_without_exposing_source_path(tmp_path: Path):
    csv_path = tmp_path / "bars.csv"
    xlsx_path = tmp_path / "bars.xlsx"
    parquet_path = tmp_path / "bars.parquet"
    frame = _source_frame()
    _write_csv(csv_path)
    frame.to_excel(xlsx_path, index=False)
    frame.to_parquet(parquet_path, index=False)
    center = DataCenter(tmp_path / "registry")

    previews = [center.preview_import(path, dataset_id="center.demo") for path in (csv_path, xlsx_path, parquet_path)]

    assert [item["format"] for item in previews] == ["csv", "xlsx", "parquet"]
    assert all(item["can_import"] for item in previews)
    assert all(item["quality"]["rows"] == 2 for item in previews)
    assert all("available_at" in item["columns"] for item in previews)
    assert all(str(tmp_path) not in json.dumps(item, default=str) for item in previews)


def test_data_center_registers_and_reopens_catalog_without_copying_source(tmp_path: Path):
    source = tmp_path / "bars.csv"
    registry = tmp_path / "registry"
    _write_csv(source)
    center = DataCenter(registry)

    result = center.register_import(source, _manifest(_source_frame()), confirm=True)
    reopened = DataCenter(registry)
    catalog = reopened.catalog()

    assert result.status == "new"
    assert catalog["datasets"][0]["dataset_id"] == "center.demo"
    assert catalog["datasets"][0]["version"] == result.proposed_version
    assert not (registry / "sources").exists()
    assert source.exists()


def test_data_center_requires_confirmation_for_changed_content_and_can_switch_old_version(tmp_path: Path):
    source = tmp_path / "bars.csv"
    registry = tmp_path / "registry"
    _write_csv(source, 10.0)
    center = DataCenter(registry)
    first = center.register_import(source, _manifest(_source_frame(10.0)), confirm=True)
    _write_csv(source, 20.0)

    preview = center.preview_import(source, dataset_id="center.demo")
    assert preview["status"] == "rewritten"
    with pytest.raises(RegistrationConfirmationRequired):
        center.register_import(source, _manifest(_source_frame(20.0)))
    second = center.register_import(source, _manifest(_source_frame(20.0)), confirm=True)
    assert second.proposed_version != first.proposed_version
    selected = center.select_version("center.demo", first.proposed_version)
    assert selected["version"] == first.proposed_version
    assert len(center.catalog("center.demo")["datasets"]) == 2


def test_data_center_blocks_research_when_pit_has_future_information(tmp_path: Path):
    source = tmp_path / "future.csv"
    _write_csv(source, future=True)
    center = DataCenter(tmp_path / "registry")
    result = center.register_import(source, _manifest(_source_frame(future=True)), confirm=True)
    calendar = build_session_calendar(
        ["2024-01-02", "2024-01-03"],
        calendar_id="custom",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
    )

    with pytest.raises(DataCenterBlocked, match="available_at"):
        center.load_for_research(
            source,
            dataset_id="center.demo",
            version=result.proposed_version,
            calendar=calendar,
            as_of="2024-01-03T16:00:00+08:00",
        )


def test_data_center_allows_pit_safe_research_and_returns_no_future_rows(tmp_path: Path):
    source = tmp_path / "safe.csv"
    _write_csv(source, future=False)
    center = DataCenter(tmp_path / "registry")
    result = center.register_import(source, _manifest(_source_frame()), confirm=True)
    calendar = build_session_calendar(
        ["2024-01-02", "2024-01-03"],
        calendar_id="custom",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
    )

    loaded = center.load_for_research(
        source,
        dataset_id="center.demo",
        version=result.proposed_version,
        calendar=calendar,
        as_of="2024-01-03T16:00:00+08:00",
    )

    assert loaded["status"] == "READY"
    assert len(loaded["frame"]) == 2
    assert loaded["frame"]["available_at"].str.contains("2024-01-04").sum() == 0


def test_data_center_never_exports_restricted_data_without_permission(tmp_path: Path):
    source = tmp_path / "restricted.csv"
    destination = tmp_path / "export.csv"
    _write_csv(source)
    center = DataCenter(tmp_path / "registry")
    result = center.register_import(source, _manifest(_source_frame(), redistribution="restricted"), confirm=True)

    with pytest.raises(PermissionError, match="redistribution"):
        center.export_registered(source, destination, dataset_id="center.demo", version=result.proposed_version, confirm=True)
    assert not destination.exists()


def test_data_center_bad_import_is_reported_without_creating_registry(tmp_path: Path):
    source = tmp_path / "bad.csv"
    source.write_text("symbol,trade_date,close\nAAA,20240102,10\n", encoding="utf-8")
    registry = tmp_path / "registry"
    center = DataCenter(registry)

    preview = center.preview_import(source, dataset_id="bad.demo")

    assert preview["can_import"] is False
    assert not registry.exists()


def test_data_center_exposes_capability_catalog_quality_detail_and_version_detail_without_paths(tmp_path: Path):
    source = tmp_path / "bars.csv"
    _write_csv(source)
    center = DataCenter(tmp_path / "registry")
    manifest = _manifest(_source_frame())
    result = center.register_import(source, manifest, confirm=True)

    capabilities = center.capability_catalog(tmp_path / "data-root")
    quality = center.quality_detail(source)
    version = center.version_detail("center.demo", result.proposed_version)

    assert capabilities[0]["dataset_id"] == "seeded.demo.baseline.v1"
    assert quality["rows"] == 2
    assert quality["status"] == "通过"
    assert version["version"] == result.proposed_version
    assert str(tmp_path) not in json.dumps({"capabilities": capabilities, "quality": quality, "version": version}, default=str)
