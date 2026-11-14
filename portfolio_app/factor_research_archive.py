"""Private local factor-research archives and comparable-run checks."""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import uuid
import zipfile
from typing import Any
import math

from .research_manifest import compare_run_manifests


class FactorArchiveError(ValueError):
    """Raised when a factor archive or comparison is unsafe or inconsistent."""


_PRIVATE_MARKERS = ("source_path", "source_file", "account", "secret", "token", "password")


def _json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FactorArchiveError("archive payload is not serializable") from exc


def _check_public(value: Any, location: str = "payload") -> None:
    if callable(value):
        raise FactorArchiveError(f"{location} contains executable value")
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).lower()
            if any(marker in name for marker in _PRIVATE_MARKERS):
                raise FactorArchiveError(f"{location} contains private field")
            _check_public(item, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_public(item, f"{location}[{index}]")
    elif isinstance(value, str) and value != "private_local" and ("C:/" in value or "\\\\" in value or "/Users/" in value or "/home/" in value or "private" in value.lower()):
        raise FactorArchiveError(f"{location} contains private material")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_factor_archive(config: dict[str, Any], result: dict[str, Any], *, name: str = "factor research") -> bytes:
    if not isinstance(config, dict) or not isinstance(result, dict):
        raise FactorArchiveError("config and result must be mappings")
    if config.get("disclosure_mode") != "private_local":
        raise FactorArchiveError("factor archive is local-only")
    _check_public(config, "config")
    _check_public(result, "result")
    config_bytes = _json(config)
    result_bytes = _json(result)
    manifest = {
        "schema_version": "factor-archive.v1",
        "archive_id": uuid.uuid4().hex,
        "name": str(name).strip()[:100] or "factor research",
        "disclosure_mode": "private_local",
        "config_sha256": _digest(config_bytes),
        "result_sha256": _digest(result_bytes),
    }
    manifest_bytes = _json(manifest)
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("manifest.json", manifest_bytes)
        output.writestr("config.json", config_bytes)
        output.writestr("result.json", result_bytes)
    return archive.getvalue()


def open_factor_archive(archive: bytes) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        with zipfile.ZipFile(BytesIO(archive)) as source:
            if sorted(source.namelist()) != ["config.json", "manifest.json", "result.json"]:
                raise FactorArchiveError("unexpected archive members")
            manifest = json.loads(source.read("manifest.json"))
            config_bytes = source.read("config.json")
            result_bytes = source.read("result.json")
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
        raise FactorArchiveError("archive cannot be opened") from exc
    if manifest.get("schema_version") != "factor-archive.v1" or manifest.get("disclosure_mode") != "private_local":
        raise FactorArchiveError("unsupported factor archive")
    if _digest(config_bytes) != manifest.get("config_sha256") or _digest(result_bytes) != manifest.get("result_sha256"):
        raise FactorArchiveError("archive checksum mismatch")
    config = json.loads(config_bytes)
    result = json.loads(result_bytes)
    _check_public(config, "config")
    _check_public(result, "result")
    return manifest, config, result


def copy_factor_config(config: dict[str, Any], *, name: str = "copy") -> dict[str, Any]:
    if not isinstance(config, dict):
        raise FactorArchiveError("config must be a mapping")
    _check_public(config, "config")
    copied = json.loads(_json(config))
    copied["copy_name"] = str(name).strip()[:100] or "copy"
    return {"config": copied}


def _comparison_signature(run: dict[str, Any]) -> tuple[Any, ...]:
    config = run.get("config")
    if not isinstance(config, dict):
        raise FactorArchiveError("run is missing config")
    values = (config.get("dataset_id"), config.get("data_version"), config.get("label_id"),
              config.get("processing_version"), config.get("cost"),
              config.get('date_start'), config.get('date_end'), run.get('engine_version'))
    if any(value is None for value in values):
        raise FactorArchiveError('runs are not comparable: missing comparison semantics')
    return values


def compare_factor_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        raise FactorArchiveError("runs cannot be empty")
    if any('run_manifest' in run for run in runs):
        comparison = compare_run_manifests([run.get('run_manifest', {}) for run in runs])
        if not comparison['ranking_allowed']:
            raise FactorArchiveError('runs are not comparable by ' + ', '.join(d['field'] for d in comparison['differences']))
        signatures = [tuple(run['run_manifest']['basis'][key] for key in ('data', 'cost', 'engine')) for run in runs]
        fields = ('data', 'cost', 'engine')
    else:
        signatures = [_comparison_signature(run) for run in runs]
        fields = ("dataset", "data version", "label", "processing", "cost", 'start', 'end', 'engine')
    for index, values in enumerate(zip(*signatures)):
        if len(set(values)) != 1:
            raise FactorArchiveError(f"runs are not comparable by {fields[index]}")
    rows: list[dict[str, Any]] = []
    for run in runs:
        metrics = run.get("metrics", {})
        if not isinstance(metrics, dict) or type(metrics.get("nav")) not in (int, float) or not math.isfinite(metrics['nav']):
            raise FactorArchiveError("run is missing numeric nav metric")
        rows.append({"nav": float(metrics["nav"]), "config": dict(run["config"])})
    rows.sort(key=lambda item: item["nav"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return {"comparable": True, "signature": list(signatures[0]), "rows": rows}
