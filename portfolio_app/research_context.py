"""Versioned, safe identity contracts for workbench research runs.

This module is intentionally independent from the Streamlit pages.  It gives
later workspaces one validated context and one explicit run specification
without carrying executable objects, arbitrary paths, live-trading hooks or
private strategy payloads across page changes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import hashlib
import json
import math
import re
from typing import Any, Mapping


CONTEXT_SCHEMA_VERSION = "2.0"
RUN_SPEC_SCHEMA_VERSION = "1.0"
EXECUTION_MODE = "offline_research_simulation"

ALLOWED_WORKSPACES = frozenset({"watch", "factors", "strategy", "portfolio", "data", "experiments", "showcase"})
ALLOWED_BAR_PERIODS = frozenset({"1d", "1w", "1mo"})
ALLOWED_RUN_TYPES = frozenset({"factor_diagnostic", "backtest", "portfolio_analysis", "data_quality"})
ALLOWED_ENGINE_IDS = frozenset({"offline_research", "seeded_demo"})
_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
_INDICATOR_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)*$")
_VERSION_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
_SYMBOL_RE = re.compile(r"^[0-9A-Z]{1,12}\.(?:SH|SZ|BJ|HK|US)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORBIDDEN_TEXT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/home/|/Users/|\\\\|(?:^|[._-])private(?:[._/-]|$)|qmt|xtquant|broker|account|submit_order|exec\b|eval\b)",
    re.IGNORECASE,
)


class ContractViolation(ValueError):
    """Raised when a context or run specification is unsafe or invalid."""


def _date_text(value: str | date | datetime, field_name: str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ContractViolation(f"{field_name} must be an ISO date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ContractViolation(f"{field_name} must be an ISO date") from exc


def _safe_id(value: str, field_name: str, *, allow_seeded: bool = True) -> str:
    if not isinstance(value, str) or not value or not _ID_RE.fullmatch(value):
        raise ContractViolation(f"{field_name} is not a safe identifier")
    if not allow_seeded and value == "seeded_demo":
        raise ContractViolation(f"{field_name} cannot be seeded_demo")
    return value


def _safe_symbol(value: str, field_name: str = "symbol") -> str:
    if not isinstance(value, str) or not _SYMBOL_RE.fullmatch(value):
        raise ContractViolation(f"{field_name} is invalid")
    return value


def _safe_json_value(value: Any, path: str = "parameters") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractViolation(f"{path} contains a non-finite number")
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item, f"{path}[]") for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not _ID_RE.fullmatch(key):
                raise ContractViolation(f"{path} contains an unsafe key")
            normalized[key] = _safe_json_value(item, f"{path}.{key}")
        return normalized
    raise ContractViolation(f"{path} contains a non-serializable value")


def _reject_forbidden_text(value: Any, field_name: str) -> None:
    if isinstance(value, str) and _FORBIDDEN_TEXT_RE.search(value):
        raise ContractViolation(f"{field_name} contains a forbidden path or live-runtime value")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_forbidden_text(str(key), field_name)
            _reject_forbidden_text(item, field_name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_forbidden_text(item, field_name)


def _fingerprint(payload: Mapping[str, Any], prefix: str) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return prefix + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ResearchContext:
    """The validated, serializable state shared by a research workspace."""

    dataset_id: str
    workspace: str
    as_of: str | date | datetime
    symbol: str | None = None
    symbols: tuple[str, ...] = ()
    bar_period: str = "1d"
    date_start: str | date | datetime | None = None
    date_end: str | date | datetime | None = None
    strategy_id: str | None = None
    factor_id: str | None = None
    indicator_ids: tuple[str, ...] = ()
    disclosure_mode: str = "public_demo"
    snapshot_id: str | None = None
    dataset_generation: int | None = None
    price_basis: str | None = None
    return_definition: str | None = None
    factor_version: str | None = None
    universe_id: str | None = None
    universe_version: str | None = None
    schema_version: str = CONTEXT_SCHEMA_VERSION
    context_id: str = field(init=False)

    def __post_init__(self) -> None:
        _safe_id(self.dataset_id, "dataset_id")
        if self.workspace not in ALLOWED_WORKSPACES:
            raise ContractViolation(f"workspace is unknown: {self.workspace}")
        if self.bar_period not in ALLOWED_BAR_PERIODS:
            raise ContractViolation(f"bar_period is invalid: {self.bar_period}")
        if self.schema_version not in {"1.0", CONTEXT_SCHEMA_VERSION}:
            raise ContractViolation("unsupported context schema_version")
        for name in ('snapshot_id', 'return_definition', 'universe_id'):
            value = getattr(self, name)
            if value is not None:
                _safe_id(value, name)
        for name in ('factor_version', 'universe_version'):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not _VERSION_RE.fullmatch(value)):
                raise ContractViolation(name + ' is not a safe version')
        if self.dataset_generation is not None and (type(self.dataset_generation) is not int or self.dataset_generation < 0):
            raise ContractViolation('dataset_generation must be a non-negative integer')
        if self.price_basis not in {None, 'raw', 'qfq', 'hfq', 'total_return'}:
            raise ContractViolation('price_basis is invalid')
        if self.schema_version == '1.0' and any(getattr(self, name) is not None for name in
                ('snapshot_id', 'dataset_generation', 'price_basis', 'return_definition', 'factor_version', 'universe_id', 'universe_version')):
            raise ContractViolation('v1 context cannot carry v2 provenance')
        as_of = _date_text(self.as_of, "as_of")
        object.__setattr__(self, "as_of", as_of)
        start = _date_text(self.date_start, "date_start") if self.date_start is not None else None
        end = _date_text(self.date_end, "date_end") if self.date_end is not None else as_of
        if start and end < start:
            raise ContractViolation("date_end cannot precede date_start")
        if end > as_of:
            raise ContractViolation("date_end cannot be later than as_of")
        object.__setattr__(self, "date_start", start)
        object.__setattr__(self, "date_end", end)

        if self.symbol is not None and self.symbols:
            raise ContractViolation("provide symbol or symbols, not both")
        if self.symbol is not None:
            object.__setattr__(self, "symbol", _safe_symbol(self.symbol))
        normalized_symbols = tuple(_safe_symbol(item, "symbols") for item in self.symbols)
        if len(set(normalized_symbols)) != len(normalized_symbols):
            raise ContractViolation("symbols cannot contain duplicates")
        if self.symbol is None and not normalized_symbols:
            raise ContractViolation("context requires symbol or symbols")
        object.__setattr__(self, "symbols", normalized_symbols)
        if self.workspace == "watch" and self.symbol is None:
            raise ContractViolation("watch context requires one symbol")
        if self.workspace in {"factors", "portfolio"} and len(normalized_symbols) < 2 and self.symbol is None:
            raise ContractViolation(f"{self.workspace} context requires a symbol universe")

        if self.strategy_id is not None:
            _safe_id(self.strategy_id, 'strategy_id')
        if self.factor_id is not None and (not isinstance(self.factor_id, str)
                or not re.fullmatch(r'[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*', self.factor_id)):
            raise ContractViolation('factor_id is not a safe identifier')
        normalized_indicators = tuple(
            item.upper() if isinstance(item, str) and _INDICATOR_ID_RE.fullmatch(item.upper()) else ""
            for item in self.indicator_ids
        )
        if any(not item for item in normalized_indicators):
            raise ContractViolation("indicator_ids contains an unsafe identifier")
        object.__setattr__(self, "indicator_ids", normalized_indicators)
        if self.disclosure_mode not in {"public_demo", "public_redacted", "private_local"}:
            raise ContractViolation("disclosure_mode is invalid")
        if self.disclosure_mode == "private_local":
            raise ContractViolation("private_local context is not available in the public workbench contract")
        if self.workspace == "strategy" and not self.strategy_id:
            raise ContractViolation("strategy context requires strategy_id")
        if self.workspace == "factors" and not self.factor_id:
            raise ContractViolation("factor context requires factor_id")
        identity = self._identity()
        object.__setattr__(self, "context_id", _fingerprint(identity, "ctx-"))

    def _identity(self) -> dict[str, Any]:
        values = {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "workspace": self.workspace,
            "as_of": self.as_of,
            "symbol": self.symbol,
            "symbols": self.symbols,
            "bar_period": self.bar_period,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "strategy_id": self.strategy_id,
            "factor_id": self.factor_id,
            "indicator_ids": self.indicator_ids,
            "disclosure_mode": self.disclosure_mode,
        }
        if self.schema_version == '2.0':
            # Navigation and display overlays do not change a calculation.
            values.pop('workspace')
            values.pop('indicator_ids')
            values.update({name: getattr(self, name) for name in ('snapshot_id', 'dataset_generation',
                'price_basis', 'return_definition', 'factor_version', 'universe_id', 'universe_version')})
        return values

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity(), "workspace": self.workspace, "indicator_ids": self.indicator_ids,
                "context_id": self.context_id}


@dataclass(frozen=True)
class BrowsingState:
    """Viewport and inspected date; never passed to a research fingerprint."""

    selected_date: str | None = None
    visible_start: str | None = None
    visible_end: str | None = None

    def __post_init__(self):
        for name in ('selected_date', 'visible_start', 'visible_end'):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _date_text(getattr(self, name), name))
        if self.visible_start and self.visible_end and self.visible_start > self.visible_end:
            raise ContractViolation('visible_end cannot precede visible_start')


@dataclass(frozen=True)
class ResultReference:
    """A saved run points to the input identity it actually used."""

    run_id: str
    context_id: str
    snapshot_id: str | None

    def __post_init__(self):
        if not re.fullmatch(r'run-[0-9a-f]{16}', self.run_id):
            raise ContractViolation('run_id is invalid')
        if not re.fullmatch(r'ctx-[0-9a-f]{16}', self.context_id):
            raise ContractViolation('context_id is invalid')
        if self.snapshot_id is not None:
            _safe_id(self.snapshot_id, 'snapshot_id')


@dataclass(frozen=True)
class RunSpec:
    """An explicit offline run request that references a context by identity."""

    context_id: str
    run_type: str
    engine_id: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = RUN_SPEC_SCHEMA_VERSION
    execution_mode: str = EXECUTION_MODE
    run_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.context_id, str) or not re.fullmatch(r"^ctx-[0-9a-f]{16}$", self.context_id):
            raise ContractViolation("context_id is invalid")
        if self.run_type not in ALLOWED_RUN_TYPES:
            raise ContractViolation(f"run_type is unknown: {self.run_type}")
        if self.engine_id not in ALLOWED_ENGINE_IDS:
            raise ContractViolation(f"engine_id is not allowed: {self.engine_id}")
        if self.schema_version != RUN_SPEC_SCHEMA_VERSION:
            raise ContractViolation("unsupported run spec schema_version")
        if self.execution_mode != EXECUTION_MODE:
            raise ContractViolation("only offline research simulation is supported")
        normalized = _safe_json_value(self.parameters)
        _reject_forbidden_text(normalized, "parameters")
        object.__setattr__(self, "parameters", normalized)
        identity = {"schema_version": self.schema_version, "context_id": self.context_id, "run_type": self.run_type, "engine_id": self.engine_id, "parameters": normalized, "execution_mode": self.execution_mode}
        object.__setattr__(self, "run_id", _fingerprint(identity, "run-"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _workspace_from_legacy(params: Mapping[str, Any]) -> str:
    page = str(params.get("page", params.get("workspace", "watch"))).strip().lower()
    return {"research": "factors", "factor": "factors", "strategy": "strategy", "portfolio": "portfolio", "watch": "watch", "showcase": "showcase", "data": "data", "experiments": "experiments"}.get(page, page)


def context_from_legacy_params(params: Mapping[str, Any]) -> ResearchContext:
    if not isinstance(params, Mapping):
        raise ContractViolation("legacy parameters must be a mapping")
    if any(key in params for key in ("data_path", "private_path", "source_path")):
        raise ContractViolation("legacy paths cannot enter ResearchContext")
    workspace = _workspace_from_legacy(params)
    period = {"daily": "1d", "day": "1d", "weekly": "1w", "week": "1w", "monthly": "1mo", "month": "1mo"}.get(str(params.get("period", "1d")).lower(), params.get("period", "1d"))
    indicators = params.get("indicators", params.get("indicator_ids", ())) or ()
    indicator_ids = tuple((item.get("key", "") if isinstance(item, Mapping) else str(item)).upper() for item in indicators)
    symbol = params.get("symbol")
    symbols = tuple(params.get("symbols", ()))
    if workspace in {"factors", "portfolio"} and symbol and not symbols:
        symbols = (symbol,)
        symbol = None
    return ResearchContext(
        dataset_id=params.get("dataset_id", "seeded_demo"),
        workspace=workspace,
        symbol=symbol,
        symbols=symbols,
        bar_period=period,
        as_of=params.get("as_of"),
        date_start=params.get("date_start"),
        date_end=params.get("date_end"),
        strategy_id=params.get("strategy_id"),
        factor_id=params.get("factor_id"),
        indicator_ids=indicator_ids,
        disclosure_mode=params.get("disclosure_mode", "public_demo"),
        schema_version='1.0',
    )


def run_spec_from_legacy_params(params: Mapping[str, Any], *, context: ResearchContext | None = None) -> RunSpec:
    context = context or context_from_legacy_params(params)
    run_type = str(params.get("run_type", "backtest"))
    engine_id = str(params.get("engine_id", "offline_research"))
    reserved = {"page", "workspace", "dataset_id", "symbol", "symbols", "period", "as_of", "date_start", "date_end", "strategy_id", "factor_id", "indicators", "indicator_ids", "disclosure_mode", "run_type", "engine_id", "data_path", "private_path", "source_path"}
    parameters = {str(key): value for key, value in params.items() if key not in reserved}
    return RunSpec(context_id=context.context_id, run_type=run_type, engine_id=engine_id, parameters=parameters)
