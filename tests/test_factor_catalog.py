from __future__ import annotations

import json
from pathlib import Path

import pytest

from portfolio_app.factor_catalog import (
    FactorCatalogError,
    FactorStatus,
    load_factor_catalog,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("suffix", ["jsonl", "csv"])
def test_registry_summary_omits_formula_and_source_fields(tmp_path, suffix):
    row = dict(factor_id="DEMO-001", design_family="momentum", framework_key="demo",
               fields_used="close", expression="private_formula", source_files="private_notes.txt")
    path=tmp_path/f"registry.{suffix}"
    if suffix == "jsonl":
        path.write_text(json.dumps(row)+"\n", encoding="utf-8")
    else:
        import csv
        with path.open("w", encoding="utf-8", newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    catalog=load_factor_catalog(path)
    assert catalog.total_count == 1
    assert catalog.status_counts[FactorStatus.DESIGN_ONLY.value] == 1
    serialized=json.dumps(catalog.to_dict())
    for forbidden in ["expression", "source_files", "private_formula", "private_notes"]:
        assert forbidden not in serialized


def test_available_fields_change_status_but_do_not_expose_dependencies() -> None:
    path = ROOT / "tests" / "fixtures" / "factor_catalog_small.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "factor_id": "DEMO-001",
                "status": "used_or_tested",
                "design_family": "price_momentum",
                "framework_key": "momentum_demo",
                "expression": "close / delay(close, 5) - 1",
                "fields_used": "close|volume",
                "source_files": "private_notes.txt",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        catalog = load_factor_catalog(path, available_fields={"close"})
        assert catalog.entries[0].compute_status is FactorStatus.DATA_UNAVAILABLE

        catalog = load_factor_catalog(path, available_fields={"close", "volume"})
        assert catalog.entries[0].compute_status is FactorStatus.COMPUTABLE
        summary = catalog.entries[0].to_dict()
        assert summary["data_dependency_count"] == 2
        assert "fields_used" not in summary
        assert "expression" not in summary
    finally:
        path.unlink(missing_ok=True)


def test_validated_status_requires_explicit_reviewed_ids() -> None:
    path = ROOT / "tests" / "fixtures" / "factor_catalog_reviewed.jsonl"
    path.write_text(
        json.dumps(
            {
                "factor_id": "DEMO-002",
                "design_family": "quality",
                "framework_key": "quality_demo",
                "fields_used": "close",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        catalog = load_factor_catalog(path, available_fields={"close"})
        assert catalog.entries[0].compute_status is FactorStatus.COMPUTABLE

        catalog = load_factor_catalog(
            path,
            available_fields={"close"},
            validated_ids={"DEMO-002"},
        )
        assert catalog.entries[0].compute_status is FactorStatus.VALIDATED
    finally:
        path.unlink(missing_ok=True)


def test_archived_source_status_is_preserved_and_unsafe_labels_are_redacted() -> None:
    path = ROOT / "tests" / "fixtures" / "factor_catalog_archived.jsonl"
    path.write_text(
        json.dumps(
            {
                "factor_id": "DEMO-003",
                "status": "archived",
                "design_family": "C:\\private\\family",
                "framework_key": "private_notes.py",
                "fields_used": "close",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        catalog = load_factor_catalog(path, available_fields={"close"})
        entry = catalog.entries[0]
        assert entry.compute_status is FactorStatus.ARCHIVED
        summary = json.dumps(entry.to_dict(), ensure_ascii=False).lower()
        assert "private_notes" not in summary
        assert "c:\\private" not in summary
    finally:
        path.unlink(missing_ok=True)


def test_registry_reader_is_read_only_and_rejects_duplicate_or_malformed_rows() -> None:
    fixture_dir = ROOT / "tests" / "fixtures"
    fixture_dir.mkdir(exist_ok=True)
    duplicate = fixture_dir / "factor_catalog_duplicate.jsonl"
    row = {"factor_id": "DUP", "design_family": "x", "framework_key": "x", "fields_used": "close"}
    duplicate.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    malformed = fixture_dir / "factor_catalog_malformed.jsonl"
    malformed.write_text("not-json\n", encoding="utf-8")
    try:
        with pytest.raises(FactorCatalogError, match="duplicate"):
            load_factor_catalog(duplicate)
        with pytest.raises(FactorCatalogError):
            load_factor_catalog(malformed)
    finally:
        duplicate.unlink(missing_ok=True)
        malformed.unlink(missing_ok=True)
