from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from portfolio_app.data_catalog import build_dataset_manifest, generate_seeded_baseline
from portfolio_app.dataset_registry import (
    RegistrationConfirmationRequired,
    fingerprint_source,
    load_dataset_registry,
    preview_dataset_update,
    register_dataset,
    repair_dataset_registry,
)


def _manifest(frame: pd.DataFrame, dataset_id: str = "demo.registry"):
    return build_dataset_manifest(
        frame,
        dataset_id=dataset_id,
        display_name="Registry demo",
        source_kind="user_import",
        license_note="user supplied",
        price_mode="raw",
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
        price_unit="currency_per_share",
        volume_unit="shares",
        availability_status="historical_cutoff",
        redistribution="restricted",
        price_relation="raw_only",
        adjustment_factor_status="not_applicable",
    )


def _write_source(path: Path, value: str = "one") -> None:
    path.write_text(f"symbol,trade_date,open,high,low,close\nAAA,20240102,10,11,9,{value}\n", encoding="utf-8")


def test_fingerprint_is_order_stable_and_does_not_expose_source_path(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "b.csv").write_text("b", encoding="utf-8")
    (source / "a.csv").write_text("a", encoding="utf-8")

    fingerprint = fingerprint_source(source)

    assert len(fingerprint.content_hash) == 64
    assert fingerprint.file_count == 2
    assert fingerprint.total_bytes == 2
    assert str(tmp_path) not in json.dumps(fingerprint.to_dict())


def test_preview_new_dataset_requires_confirmation_and_writes_nothing(tmp_path: Path):
    source = tmp_path / "input.csv"
    registry = tmp_path / "registry"
    _write_source(source)
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()
    before = source.read_bytes()

    preview = preview_dataset_update(registry, _manifest(frame), source)

    assert preview.status == "new"
    assert preview.requires_confirmation is True
    assert preview.proposed_version.startswith("v")
    assert not registry.exists()
    assert source.read_bytes() == before

    with pytest.raises(RegistrationConfirmationRequired):
        register_dataset(registry, _manifest(frame), source)
    assert not registry.exists()


def test_confirmed_registration_persists_version_and_never_copies_or_changes_source(tmp_path: Path):
    source = tmp_path / "input.csv"
    registry = tmp_path / "registry"
    _write_source(source)
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()
    before = source.read_bytes()

    result = register_dataset(registry, _manifest(frame), source, confirm=True)
    snapshot = load_dataset_registry(registry)

    assert result.status == "new"
    assert len(snapshot["datasets"]) == 1
    record = snapshot["datasets"][0]
    assert record["dataset_id"] == "demo.registry"
    assert record["version"] == result.proposed_version
    assert (registry / "datasets" / "demo.registry" / result.proposed_version / "manifest.json").exists()
    assert source.read_bytes() == before
    assert str(tmp_path) not in json.dumps(snapshot)


def test_same_content_is_duplicate_and_idempotent(tmp_path: Path):
    source = tmp_path / "input.csv"
    registry = tmp_path / "registry"
    _write_source(source)
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()
    first = register_dataset(registry, _manifest(frame), source, confirm=True)

    preview = preview_dataset_update(registry, _manifest(frame), source)
    second = register_dataset(registry, _manifest(frame), source)

    assert preview.status == "duplicate"
    assert preview.requires_confirmation is False
    assert second.status == "duplicate"
    assert second.proposed_version == first.proposed_version
    assert len(load_dataset_registry(registry)["datasets"]) == 1


def test_changed_content_is_rewritten_and_requires_confirmation(tmp_path: Path):
    source = tmp_path / "input.csv"
    registry = tmp_path / "registry"
    _write_source(source, "10.5")
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()
    first = register_dataset(registry, _manifest(frame), source, confirm=True)

    _write_source(source, "11.5")
    preview = preview_dataset_update(registry, _manifest(frame), source)

    assert preview.status == "rewritten"
    assert preview.requires_confirmation is True
    assert preview.proposed_version != first.proposed_version
    with pytest.raises(RegistrationConfirmationRequired):
        register_dataset(registry, _manifest(frame), source)
    second = register_dataset(registry, _manifest(frame), source, confirm=True)
    assert second.status == "rewritten"
    assert len(load_dataset_registry(registry)["datasets"]) == 2


def test_overwrite_target_is_explicit_and_does_not_happen_without_confirmation(tmp_path: Path):
    source = tmp_path / "input.csv"
    registry = tmp_path / "registry"
    _write_source(source, "10.5")
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()
    first = register_dataset(registry, _manifest(frame), source, confirm=True)

    _write_source(source, "11.5")
    preview = preview_dataset_update(
        registry, _manifest(frame), source, target_version=first.proposed_version
    )
    assert preview.status == "overwrite"
    assert preview.requires_confirmation is True
    with pytest.raises(RegistrationConfirmationRequired):
        register_dataset(registry, _manifest(frame), source, target_version=first.proposed_version)
    with pytest.raises(ValueError, match='immutable|不可覆盖'):
        register_dataset(registry, _manifest(frame), source, target_version=first.proposed_version, confirm=True)
    assert len(load_dataset_registry(registry)["datasets"]) == 1


def test_corrupt_index_can_be_rebuilt_from_version_manifests(tmp_path: Path):
    source = tmp_path / "input.csv"
    registry = tmp_path / "registry"
    _write_source(source)
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()
    result = register_dataset(registry, _manifest(frame), source, confirm=True)
    (registry / "index.json").write_text("{broken", encoding="utf-8")

    recovered = load_dataset_registry(registry)
    assert recovered["recovered"] is True
    assert recovered["datasets"][0]["version"] == result.proposed_version
    repair_dataset_registry(registry)
    repaired = load_dataset_registry(registry)
    assert repaired["recovered"] is False
    assert repaired["datasets"] == recovered["datasets"]


def test_registry_rejects_dataset_ids_that_escape_registry_root(tmp_path: Path):
    source = tmp_path / "input.csv"
    _write_source(source)
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()
    unsafe = _manifest(frame, dataset_id="../outside")

    with pytest.raises(ValueError, match="dataset_id"):
        preview_dataset_update(tmp_path / "registry", unsafe, source)


def test_registry_rejects_unsafe_target_versions(tmp_path: Path):
    source = tmp_path / "input.csv"
    _write_source(source)
    frame = generate_seeded_baseline(sessions=60).iloc[:2].copy()

    with pytest.raises(ValueError, match="target_version"):
        preview_dataset_update(tmp_path / "registry", _manifest(frame), source, target_version="../outside")
