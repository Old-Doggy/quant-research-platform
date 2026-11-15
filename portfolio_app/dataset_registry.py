"""Local, source-preserving dataset registration and version preview.

The registry stores metadata and content fingerprints only. It never copies,
rewrites, or imports the source dataset, and it intentionally omits source
paths from every persisted record.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from portfolio_app.contracts import DatasetManifest


REGISTRY_SCHEMA_VERSION = 1


class RegistrationConfirmationRequired(ValueError):
    """Raised when a new or changed version needs explicit confirmation."""


def _validate_dataset_id(dataset_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", dataset_id):
        raise ValueError("dataset_id must be a non-empty path-safe identifier")


def _validate_target_version(version: str) -> None:
    if not re.fullmatch(r"v[0-9]{3,}", version):
        raise ValueError("target_version must be a path-safe version identifier")


@dataclass(frozen=True)
class SourceFingerprint:
    content_hash: str
    file_count: int
    total_bytes: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetUpdatePreview:
    dataset_id: str
    status: str
    proposed_version: str
    requires_confirmation: bool
    fingerprint: SourceFingerprint
    previous_versions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["fingerprint"] = self.fingerprint.to_dict()
        payload["previous_versions"] = list(self.previous_versions)
        return payload


def fingerprint_source(source: str | Path) -> SourceFingerprint:
    """Hash a file or directory deterministically without exposing its path."""
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    digest = hashlib.sha256()
    total_bytes = 0
    for item in files:
        relative_name = item.name if path.is_file() else item.relative_to(path).as_posix()
        file_hash = hashlib.sha256()
        with item.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                file_hash.update(chunk)
                total_bytes += len(chunk)
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(file_hash.digest())
    return SourceFingerprint(digest.hexdigest(), len(files), total_bytes)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _index_path(registry_root: Path) -> Path:
    return registry_root / "index.json"


def _version_root(registry_root: Path, dataset_id: str, version: str) -> Path:
    return registry_root / "datasets" / dataset_id / version


def _record_payload(manifest: DatasetManifest, version: str, fingerprint: SourceFingerprint) -> dict[str, object]:
    return {
        "dataset_id": manifest.dataset_id,
        "version": version,
        "fingerprint": fingerprint.to_dict(),
        "manifest": manifest.to_dict(),
    }


def _read_version_records(registry_root: Path) -> list[dict[str, object]]:
    root = registry_root / "datasets"
    if not root.is_dir():
        return []
    records: list[dict[str, object]] = []
    for manifest_path in sorted(root.glob("*/*/manifest.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("manifest"), dict):
                records.append(payload)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda item: (str(item.get("dataset_id", "")), str(item.get("version", ""))))


def _load_index_records(registry_root: Path) -> tuple[list[dict[str, object]], bool]:
    index_path = _index_path(registry_root)
    if not index_path.exists():
        return _read_version_records(registry_root), False
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        records = payload["datasets"]
        if not isinstance(records, list):
            raise ValueError("datasets must be a list")
        return records, False
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return _read_version_records(registry_root), True


def load_dataset_registry(registry_root: str | Path) -> dict[str, object]:
    root = Path(registry_root)
    records, recovered = _load_index_records(root)
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "recovered": recovered,
        "datasets": records,
    }


def _records_for_dataset(registry_root: Path, dataset_id: str) -> list[dict[str, object]]:
    records, _ = _load_index_records(registry_root)
    return [record for record in records if record.get("dataset_id") == dataset_id]


def _next_version(records: list[dict[str, object]]) -> str:
    numbers = []
    for record in records:
        value = str(record.get("version", ""))
        if value.startswith("v") and value[1:].isdigit():
            numbers.append(int(value[1:]))
    return f"v{max(numbers, default=0) + 1:03d}"


def preview_dataset_update(
    registry_root: str | Path,
    manifest: DatasetManifest,
    source: str | Path,
    *,
    target_version: str | None = None,
) -> DatasetUpdatePreview:
    _validate_dataset_id(manifest.dataset_id)
    if target_version is not None:
        _validate_target_version(target_version)
    fingerprint = fingerprint_source(source)
    root = Path(registry_root)
    records = _records_for_dataset(root, manifest.dataset_id)
    previous_versions = tuple(str(record["version"]) for record in records)
    same_record = next(
        (record for record in records if record.get("fingerprint", {}).get("content_hash") == fingerprint.content_hash),
        None,
    )
    if target_version is not None:
        if target_version not in previous_versions:
            raise ValueError(f"target_version does not exist: {target_version}")
        status = "duplicate" if same_record and same_record.get("version") == target_version else "overwrite"
        return DatasetUpdatePreview(
            manifest.dataset_id, status, target_version, status == "overwrite", fingerprint, previous_versions
        )
    if same_record is not None:
        return DatasetUpdatePreview(
            manifest.dataset_id, "duplicate", str(same_record["version"]), False, fingerprint, previous_versions
        )
    status = "new" if not records else "rewritten"
    return DatasetUpdatePreview(
        manifest.dataset_id, status, _next_version(records), True, fingerprint, previous_versions
    )


def _write_index(registry_root: Path, records: list[dict[str, object]]) -> None:
    _atomic_write_json(
        _index_path(registry_root),
        {"schema_version": REGISTRY_SCHEMA_VERSION, "datasets": records},
    )


def register_dataset(
    registry_root: str | Path,
    manifest: DatasetManifest,
    source: str | Path,
    *,
    target_version: str | None = None,
    confirm: bool = False,
) -> DatasetUpdatePreview:
    root = Path(registry_root)
    preview = preview_dataset_update(root, manifest, source, target_version=target_version)
    if preview.requires_confirmation and not confirm:
        raise RegistrationConfirmationRequired(
            f"registration requires confirmation: {preview.status} {manifest.dataset_id} {preview.proposed_version}"
        )
    if preview.status == "duplicate":
        return preview
    if preview.status == 'overwrite':
        raise ValueError('已登记版本不可覆盖（immutable）；请登记新版本以保留旧研究引用')

    record = _record_payload(manifest, preview.proposed_version, preview.fingerprint)
    version_root = _version_root(root, manifest.dataset_id, preview.proposed_version)
    records, _ = _load_index_records(root)
    from .snapshot_contracts import snapshot_from_hash
    previous = [r for r in records if r.get('dataset_id') == manifest.dataset_id]
    generation = max((r.get('snapshot', {}).get('generation', 0) for r in previous), default=0) + 1
    record['snapshot'] = asdict(snapshot_from_hash(preview.fingerprint.content_hash,
        dataset_id=manifest.dataset_id, generation=generation, price_basis=manifest.to_dict().get('price_mode', 'unknown')))
    if preview.status == "overwrite":
        records = [
            existing for existing in records
            if not (existing.get("dataset_id") == manifest.dataset_id and existing.get("version") == preview.proposed_version)
        ]
    records.append(record)
    _atomic_write_json(version_root / "manifest.json", record)
    _write_index(root, sorted(records, key=lambda item: (str(item.get("dataset_id", "")), str(item.get("version", "")))))
    return preview


def repair_dataset_registry(registry_root: str | Path) -> None:
    root = Path(registry_root)
    _write_index(root, _read_version_records(root))
