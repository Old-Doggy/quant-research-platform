"""Read-only, disclosure-safe adapter for historical factor design registries."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
from pathlib import Path
import re
from typing import Iterable

from .factor_contracts import DisclosureStatus, FactorStatus


class FactorCatalogError(ValueError):
    """Raised when a factor registry cannot be safely read."""


@dataclass(frozen=True)
class FactorCatalogEntry:
    """Safe summary of a factor design; private formula material is excluded."""

    factor_id: str
    name: str
    family: str
    compute_status: FactorStatus
    disclosure_status: DisclosureStatus
    data_dependency_count: int
    registry_status: str

    def to_dict(self) -> dict[str, object]:
        return {key: (value.value if hasattr(value, "value") else value) for key, value in asdict(self).items()}


@dataclass(frozen=True)
class FactorCatalog:
    entries: tuple[FactorCatalogEntry, ...]

    @property
    def total_count(self) -> int:
        return len(self.entries)

    @property
    def status_counts(self) -> dict[str, int]:
        return {
            status.value: sum(entry.compute_status is status for entry in self.entries)
            for status in FactorStatus
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "total_count": self.total_count,
            "status_counts": self.status_counts,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _read_rows(path: Path) -> Iterable[dict[str, object]]:
    if not path.is_file():
        raise FactorCatalogError(f"factor registry does not exist: {path.name}")
    try:
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as handle:
                yield from csv.DictReader(handle)
            return
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FactorCatalogError("factor registry cannot be read") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FactorCatalogError(f"malformed factor registry row at line {line_number}") from exc
        if not isinstance(row, dict):
            raise FactorCatalogError(f"factor registry row {line_number} must be an object")
        yield row


def _field_names(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split("|") if item.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise FactorCatalogError("factor fields_used must be text or a list")


def _safe_label(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    if text and not re.search(r"(?:private|secret|account|\.(?:py|txt|csv|jsonl?)$)", text, re.IGNORECASE) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,80}", text):
        return text
    return fallback


def load_factor_catalog(
    path: str | Path,
    *,
    available_fields: set[str] | None = None,
    validated_ids: set[str] | None = None,
) -> FactorCatalog:
    """Read a registry and return only safe, non-executable factor summaries.

    The source is never modified. A design is ``computable`` only when every
    declared input field is present in ``available_fields``. Validation is an
    explicit review decision and is never inferred from the source status.
    """
    available = set(available_fields or ())
    reviewed = set(validated_ids or ())
    entries: list[FactorCatalogEntry] = []
    seen: set[str] = set()
    for row in _read_rows(Path(path)):
        factor_id = str(row.get("factor_id", "")).strip()
        if not factor_id:
            raise FactorCatalogError("factor registry row is missing factor_id")
        if factor_id in seen:
            raise FactorCatalogError(f"duplicate factor_id: {factor_id}")
        seen.add(factor_id)
        fields = _field_names(row.get("fields_used"))
        source_status = str(row.get("status") or "unknown").strip().lower()
        if source_status == FactorStatus.ARCHIVED.value:
            compute_status = FactorStatus.ARCHIVED
        elif factor_id in reviewed:
            compute_status = FactorStatus.VALIDATED
        elif fields and available and set(fields).issubset(available):
            compute_status = FactorStatus.COMPUTABLE
        elif fields and available:
            compute_status = FactorStatus.DATA_UNAVAILABLE
        else:
            compute_status = FactorStatus.DESIGN_ONLY
        entries.append(
            FactorCatalogEntry(
                factor_id=factor_id,
                name=_safe_label(row.get("framework_key"), "registered_factor"),
                family=_safe_label(row.get("design_family"), "unknown"),
                compute_status=compute_status,
                disclosure_status=DisclosureStatus.PRIVATE,
                data_dependency_count=len(fields),
                registry_status=source_status or "unknown",
            )
        )
    return FactorCatalog(entries=tuple(entries))
