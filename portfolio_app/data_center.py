"""Read-only data-center orchestration for local research inputs."""
from __future__ import annotations

from pathlib import Path
import shutil

import pandas as pd

from portfolio_app.contracts import DatasetManifest
from portfolio_app.data_catalog import preview_market_import
from portfolio_app.data_catalog import build_quality_summary
from portfolio_app.data_capability import build_capability_matrix, scan_local_data_capabilities
from portfolio_app.dataset_registry import (
    DatasetUpdatePreview,
    register_dataset,
    load_dataset_registry,
    preview_dataset_update,
)
from portfolio_app.temporal_contracts import SessionCalendar, temporal_readiness


class DataCenterBlocked(RuntimeError):
    """Raised when a dataset cannot safely enter a research operation."""


class DataCenter:
    def __init__(self, registry_root: str | Path):
        self.registry_root = Path(registry_root)

    @staticmethod
    def _format_for(source: str | Path) -> str:
        suffix = Path(source).suffix.lower()
        return "parquet" if suffix in {".parquet", ".pq"} else suffix.lstrip(".") or "unknown"

    def preview_import(self, source: str | Path, *, dataset_id: str) -> dict[str, object]:
        """Preview and validate a source without registering or mutating it."""
        preview = preview_market_import(source)
        preview.pop("frame", None)
        preview["format"] = self._format_for(source)
        preview["dataset_id"] = dataset_id
        if preview["can_import"]:
            registry_preview = preview_dataset_update(
                self.registry_root,
                _manifest_placeholder(dataset_id),
                source,
            )
            preview.update({
                "status": registry_preview.status,
                "registration_status": registry_preview.status,
                "proposed_version": registry_preview.proposed_version,
                "requires_confirmation": registry_preview.requires_confirmation,
                "previous_versions": list(registry_preview.previous_versions),
            })
        return preview

    def register_import(
        self,
        source: str | Path,
        manifest: DatasetManifest,
        *,
        target_version: str | None = None,
        confirm: bool = False,
    ) -> DatasetUpdatePreview:
        return register_dataset(
            self.registry_root,
            manifest,
            source,
            target_version=target_version,
            confirm=confirm,
        )

    def catalog(self, dataset_id: str | None = None) -> dict[str, object]:
        catalog = load_dataset_registry(self.registry_root)
        if dataset_id is None:
            return catalog
        catalog["datasets"] = [
            record for record in catalog["datasets"] if record.get("dataset_id") == dataset_id
        ]
        return catalog

    def select_version(self, dataset_id: str, version: str) -> dict[str, object]:
        records = self.catalog(dataset_id)["datasets"]
        for record in records:
            if record.get("version") == version:
                return record
        raise KeyError(f"dataset version not found: {dataset_id}/{version}")

    def version_detail(self, dataset_id: str, version: str) -> dict[str, object]:
        """Return one registered version's metadata without source location."""
        record = dict(self.select_version(dataset_id, version))
        return {
            "dataset_id": record.get("dataset_id"),
            "version": record.get("version"),
            "fingerprint": record.get("fingerprint"),
            "manifest": record.get("manifest"),
        }

    @staticmethod
    def capability_catalog(data_root: str | Path | None = None) -> list[dict[str, object]]:
        profiles = build_capability_matrix()
        if data_root is not None:
            profiles.extend(scan_local_data_capabilities(data_root))
        return profiles

    @staticmethod
    def quality_detail(source: str | Path) -> dict[str, object]:
        preview = preview_market_import(source)
        quality = dict(preview.get("quality", {}))
        quality["can_import"] = preview.get("can_import", False)
        if preview.get("error"):
            quality["error"] = preview["error"]
        return quality

    def load_for_research(
        self,
        source: str | Path,
        *,
        dataset_id: str,
        version: str,
        calendar: SessionCalendar,
        as_of: object,
    ) -> dict[str, object]:
        record = self.select_version(dataset_id, version)
        manifest = _manifest_from_dict(record["manifest"])
        preview = preview_market_import(source)
        if not preview["can_import"]:
            raise DataCenterBlocked(f"source quality blocked: {preview['error']}")
        frame = preview["frame"]
        readiness = temporal_readiness(manifest, calendar, frame, as_of=as_of)
        if readiness.status != "READY":
            raise DataCenterBlocked("temporal readiness blocked: " + ", ".join(readiness.reasons))
        from portfolio_app.temporal_contracts import filter_point_in_time

        visible = filter_point_in_time(frame, as_of=as_of, timezone=manifest.timezone)
        return {
            "status": readiness.status,
            "dataset_id": dataset_id,
            "version": version,
            "manifest": manifest.to_dict(),
            "frame": visible,
        }

    def export_registered(
        self,
        source: str | Path,
        destination: str | Path,
        *,
        dataset_id: str,
        version: str,
        confirm: bool = False,
    ) -> None:
        record = self.select_version(dataset_id, version)
        manifest = _manifest_from_dict(record["manifest"])
        if manifest.redistribution != "allowed":
            raise PermissionError("redistribution permission is not allowed")
        if not confirm:
            raise PermissionError("export requires explicit confirmation")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _manifest_from_dict(payload: dict[str, object]) -> DatasetManifest:
    values = dict(payload)
    for field in ("required_columns", "optional_columns", "capabilities"):
        values[field] = tuple(values.get(field, ()))
    return DatasetManifest(**values)


def _manifest_placeholder(dataset_id: str) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        display_name="Registration preview",
        source_kind="preview",
        license_note="preview only",
        frequency="1d",
        price_mode="unknown",
        start_date="1970-01-01",
        end_date="1970-01-01",
        symbol_count=0,
        row_count=0,
        required_columns=("trade_date", "symbol", "open", "high", "low", "close"),
        quality_status="unknown",
        generated_at="2026-10-28T00:00:00Z",
    )
