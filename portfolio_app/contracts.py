from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import math
import re
from typing import Any

import pandas as pd


CONTRACT_VERSION = "1.1"

UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"

FREQUENCY_VALUES = frozenset({"1d", "1h", "1m", "tick"})
PRICE_MODE_VALUES = frozenset({"raw", "qfq", "hfq", "adjusted", UNKNOWN})
CALENDAR_VALUES = frozenset({
    "cn_stock_exchange",
    "hk_exchange",
    "us_exchange",
    "custom",
    NOT_APPLICABLE,
    UNKNOWN,
})
MARKET_VALUES = frozenset({
    "CN_STOCK",
    "HK_STOCK",
    "US_STOCK",
    "INDEX",
    "ETF",
    "OPTIONS",
    "MACRO",
    UNKNOWN,
})
PRICE_UNIT_VALUES = frozenset({
    "currency_per_share",
    "index_points",
    "contract_price",
    "source_defined",
    NOT_APPLICABLE,
    UNKNOWN,
})
VOLUME_UNIT_VALUES = frozenset({
    "shares",
    "lots",
    "contracts",
    "currency",
    "source_defined",
    NOT_APPLICABLE,
    UNKNOWN,
})
AVAILABILITY_VALUES = frozenset({
    "historical_cutoff",
    "current_cutoff",
    "known",
    NOT_APPLICABLE,
    UNKNOWN,
})
POINT_IN_TIME_VALUES = frozenset({"known", NOT_APPLICABLE, UNKNOWN})
CORPORATE_ACTION_VALUES = frozenset({
    "complete",
    "partial",
    "none",
    NOT_APPLICABLE,
    UNKNOWN,
})
REDISTRIBUTION_VALUES = frozenset({
    "allowed",
    "restricted",
    "prohibited",
    NOT_APPLICABLE,
    UNKNOWN,
})
PRICE_RELATION_VALUES = frozenset({
    "raw_only",
    "adjusted_only",
    "raw_and_adjusted_linked",
    "raw_or_adjusted_explicit",
    NOT_APPLICABLE,
    UNKNOWN,
})
ADJUSTMENT_FACTOR_VALUES = frozenset({
    "available",
    "available_separately",
    "missing",
    NOT_APPLICABLE,
    UNKNOWN,
})
DATA_CAPABILITY_VALUES = frozenset({
    "stock_chart",
    "indicator_research",
    "factor_research",
    "signal_research",
    "demo_backtest",
    "local_backtest_input",
    "cash_backtest",
    "raw_price_share_ledger",
    "universe_research",
    "derivatives_research",
    "convertible_bond_research",
    "regime_research",
    UNKNOWN,
})


class ContractViolation(ValueError):
    """Raised when a data or research artifact violates a stable contract."""


class DisclosureMode(StrEnum):
    PRIVATE_LOCAL = "private_local"
    PUBLIC_REDACTED = "public_redacted"
    PUBLIC_DEMO = "public_demo"


@dataclass(frozen=True)
class DisclosurePolicy:
    mode: DisclosureMode
    allow_raw_data: bool
    allow_target_positions: bool
    allow_aggregate_metrics: bool
    allow_synthetic_data: bool
    allow_strategy_code: bool
    allow_exact_parameters: bool
    notes: str


DISCLOSURE_POLICIES = {
    DisclosureMode.PRIVATE_LOCAL: DisclosurePolicy(
        mode=DisclosureMode.PRIVATE_LOCAL,
        allow_raw_data=True,
        allow_target_positions=True,
        allow_aggregate_metrics=True,
        allow_synthetic_data=True,
        allow_strategy_code=True,
        allow_exact_parameters=True,
        notes="本地研究模式；允许读取私人数据和真实策略适配层，但不自动发布。",
    ),
    DisclosureMode.PUBLIC_REDACTED: DisclosurePolicy(
        mode=DisclosureMode.PUBLIC_REDACTED,
        allow_raw_data=False,
        allow_target_positions=False,
        allow_aggregate_metrics=True,
        allow_synthetic_data=True,
        allow_strategy_code=False,
        allow_exact_parameters=False,
        notes="脱敏作品模式；只允许经过确认的聚合结果、摘要逻辑和脱敏证据。",
    ),
    DisclosureMode.PUBLIC_DEMO: DisclosurePolicy(
        mode=DisclosureMode.PUBLIC_DEMO,
        allow_raw_data=False,
        allow_target_positions=False,
        allow_aggregate_metrics=True,
        allow_synthetic_data=True,
        allow_strategy_code=False,
        allow_exact_parameters=False,
        notes="公开演示模式；默认使用合成或明确可再分发数据，不连接私人运行链路。",
    ),
}


def get_disclosure_policy(mode: DisclosureMode | str) -> DisclosurePolicy:
    try:
        return DISCLOSURE_POLICIES[DisclosureMode(mode)]
    except (KeyError, ValueError) as exc:
        raise ContractViolation(f"Unknown disclosure mode: {mode}") from exc


def _as_serializable(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _as_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_serializable(item) for item in value]
    return value


@dataclass(frozen=True)
class DatasetManifest:
    """Stable identity and quality summary for a registered dataset."""

    dataset_id: str
    display_name: str
    source_kind: str
    license_note: str
    frequency: str
    price_mode: str
    start_date: str
    end_date: str
    symbol_count: int
    row_count: int
    required_columns: tuple[str, ...]
    quality_status: str
    generated_at: str
    optional_columns: tuple[str, ...] = ()
    content_hash: str | None = None
    schema_version: str = CONTRACT_VERSION
    calendar_id: str = UNKNOWN
    market: str = UNKNOWN
    timezone: str = UNKNOWN
    price_unit: str = UNKNOWN
    volume_unit: str = UNKNOWN
    availability_status: str = UNKNOWN
    point_in_time: str = UNKNOWN
    corporate_actions: str = UNKNOWN
    redistribution: str = UNKNOWN
    price_relation: str = UNKNOWN
    adjustment_factor_status: str = UNKNOWN
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.display_name or not self.source_kind:
            raise ContractViolation("DatasetManifest requires identity fields")
        if not self.license_note.strip():
            raise ContractViolation("DatasetManifest requires a license note")
        if self.frequency not in FREQUENCY_VALUES:
            raise ContractViolation("DatasetManifest.frequency is invalid")
        if self.price_mode not in PRICE_MODE_VALUES:
            raise ContractViolation("DatasetManifest.price_mode is invalid")
        enum_fields = {
            "calendar_id": (self.calendar_id, CALENDAR_VALUES),
            "market": (self.market, MARKET_VALUES),
            "price_unit": (self.price_unit, PRICE_UNIT_VALUES),
            "volume_unit": (self.volume_unit, VOLUME_UNIT_VALUES),
            "availability_status": (self.availability_status, AVAILABILITY_VALUES),
            "point_in_time": (self.point_in_time, POINT_IN_TIME_VALUES),
            "corporate_actions": (self.corporate_actions, CORPORATE_ACTION_VALUES),
            "redistribution": (self.redistribution, REDISTRIBUTION_VALUES),
            "price_relation": (self.price_relation, PRICE_RELATION_VALUES),
            "adjustment_factor_status": (self.adjustment_factor_status, ADJUSTMENT_FACTOR_VALUES),
        }
        for field_name, (value, allowed) in enum_fields.items():
            if value not in allowed:
                raise ContractViolation(f"DatasetManifest.{field_name} is invalid")
        if not self.timezone or not isinstance(self.timezone, str):
            raise ContractViolation("DatasetManifest.timezone is invalid")
        if any(capability not in DATA_CAPABILITY_VALUES for capability in self.capabilities):
            raise ContractViolation("DatasetManifest.capabilities contains an invalid value")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ContractViolation("DatasetManifest.capabilities cannot contain duplicates")
        if "raw_price_share_ledger" in self.capabilities and self.price_mode != "raw":
            raise ContractViolation("raw_price_share_ledger requires raw price_mode")
        if "cash_backtest" in self.capabilities:
            if self.price_mode != "raw":
                raise ContractViolation("cash_backtest requires raw price_mode")
            if self.corporate_actions != "complete":
                raise ContractViolation("cash_backtest requires complete corporate_actions")
            if self.point_in_time != "known":
                raise ContractViolation("cash_backtest requires known point_in_time")
        if pd.Timestamp(self.end_date) < pd.Timestamp(self.start_date):
            raise ContractViolation("DatasetManifest end_date cannot precede start_date")
        if self.symbol_count < 0 or self.row_count < 0:
            raise ContractViolation("DatasetManifest counts cannot be negative")
        if not self.required_columns:
            raise ContractViolation("DatasetManifest requires required_columns")
        if self.quality_status not in {"passed", "warning", "failed", "unknown"}:
            raise ContractViolation("DatasetManifest.quality_status is invalid")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


@dataclass(frozen=True)
class ExecutionPolicy:
    """Explicit execution assumptions shared by research and backtest views."""

    policy_id: str
    execution_lag_days: int
    price_field: str
    fill_model: str
    commission_bps: float
    slippage_bps: float
    reject_untradable: bool
    as_of_policy: str
    lot_size: int = 1
    allow_partial_fill: bool = False
    schema_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ContractViolation("ExecutionPolicy requires policy_id")
        if self.execution_lag_days < 0:
            raise ContractViolation("ExecutionPolicy.execution_lag_days must be non-negative")
        if self.price_field not in {"open", "close", "vwap", "adj_open", "adj_close"}:
            raise ContractViolation("ExecutionPolicy.price_field is invalid")
        if self.fill_model not in {"same_bar", "next_bar", "next_open", "next_close", "custom"}:
            raise ContractViolation("ExecutionPolicy.fill_model is invalid")
        if not math.isfinite(self.commission_bps) or self.commission_bps < 0:
            raise ContractViolation("ExecutionPolicy commission must be non-negative")
        if not math.isfinite(self.slippage_bps) or self.slippage_bps < 0:
            raise ContractViolation("ExecutionPolicy slippage must be non-negative")
        if self.as_of_policy not in {"decision_date", "effective_date", "fill_date"}:
            raise ContractViolation("ExecutionPolicy.as_of_policy is invalid")
        if self.lot_size <= 0:
            raise ContractViolation("ExecutionPolicy.lot_size must be positive")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


_PRIVATE_MATERIAL_RE = re.compile(
    r"(?:private\s+(?:strategy|path|data|artifact)|secret|[A-Za-z]:[\\/]|/home/|/Users/|\\\\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResearchEvidenceEnvelope:
    """Disclosure-aware summary of one approved research evidence layer."""

    model_id: str
    evidence_layer: str
    status: str
    source_kind: str
    disclosure_mode: DisclosureMode
    period_start: str
    period_end: str
    metrics: dict[str, float]
    cost_assumption: str
    limitations: tuple[str, ...]
    artifact_ids: tuple[str, ...] = ()
    schema_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.model_id or not self.evidence_layer or not self.source_kind:
            raise ContractViolation("ResearchEvidenceEnvelope requires identity fields")
        if self.status not in {"validated", "validated_with_limitations", "review_required", "unavailable"}:
            raise ContractViolation("ResearchEvidenceEnvelope.status is invalid")
        if pd.Timestamp(self.period_end) < pd.Timestamp(self.period_start):
            raise ContractViolation("Research evidence period_end cannot precede period_start")
        if not self.cost_assumption.strip():
            raise ContractViolation("Research evidence requires cost_assumption")
        if not self.limitations:
            raise ContractViolation("Research evidence requires limitations")
        for key, value in self.metrics.items():
            if not key or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ContractViolation(f"Research evidence metric is invalid: {key}")
        if self.disclosure_mode != DisclosureMode.PRIVATE_LOCAL:
            fields = (*self.limitations, self.cost_assumption, *self.artifact_ids)
            if any(_PRIVATE_MATERIAL_RE.search(str(value)) for value in fields):
                raise ContractViolation("public research evidence cannot contain private material")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    display_name: str
    version: str
    required_features: tuple[str, ...]
    execution_lag_days: int = 1
    parameter_schema: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.display_name or not self.version:
            raise ContractViolation("StrategySpec requires id, display name, and version")
        if self.execution_lag_days < 0:
            raise ContractViolation("execution_lag_days must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


@dataclass(frozen=True)
class TradeEvent:
    """解释性交易事件，连接信号、订单意图和模拟成交。"""

    event_id: str
    event_type: str
    strategy_id: str
    symbol: str
    side: str
    decision_date: str
    effective_date: str | None = None
    fill_date: str | None = None
    reason_code: str = "unspecified"
    reason_text_public: str = ""
    evidence: dict[str, object] = field(default_factory=dict)
    order_id: str | None = None
    fill_id: str | None = None
    quantity: int | None = None
    price: float | None = None
    status: str = "RECORDED"
    constraint_status: str = "NONE"

    def __post_init__(self) -> None:
        if not self.event_id or not self.strategy_id or not self.symbol:
            raise ContractViolation("TradeEvent requires event_id, strategy_id, and symbol")
        if self.event_type not in {"SIGNAL", "ORDER_INTENT", "FILL", "POOL_EVENT"}:
            raise ContractViolation("TradeEvent.event_type is invalid")
        if self.side not in {"BUY", "SELL", "HOLD", "ENTER", "EXIT"}:
            raise ContractViolation("TradeEvent.side is invalid")
        if not self.reason_code or not self.reason_text_public:
            raise ContractViolation("TradeEvent requires reason_code and reason_text_public")
        decision = pd.Timestamp(self.decision_date)
        if self.effective_date is not None and pd.Timestamp(self.effective_date) < decision:
            raise ContractViolation("TradeEvent.effective_date cannot precede decision_date")
        if self.fill_date is not None:
            if self.effective_date is None:
                raise ContractViolation("TradeEvent.fill_date requires effective_date")
            if pd.Timestamp(self.fill_date) < pd.Timestamp(self.effective_date):
                raise ContractViolation("TradeEvent.fill_date cannot precede effective_date")
        if self.quantity is not None and self.quantity < 0:
            raise ContractViolation("TradeEvent.quantity cannot be negative")
        if self.price is not None and self.price <= 0:
            raise ContractViolation("TradeEvent.price must be positive")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


@dataclass(frozen=True)
class OrderIntent:
    order_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: int
    decision_date: str
    execution_date: str
    target_weight: float | None = None

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ContractViolation("OrderIntent.side must be BUY or SELL")
        if self.quantity <= 0:
            raise ContractViolation("OrderIntent.quantity must be positive")
        if pd.Timestamp(self.execution_date) < pd.Timestamp(self.decision_date):
            raise ContractViolation("execution_date cannot precede decision_date")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    symbol: str
    quantity: int
    fill_price: float
    fill_date: str
    commission: float = 0.0
    slippage: float = 0.0

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.fill_price <= 0:
            raise ContractViolation("Fill quantity and price must be positive")
        if self.commission < 0 or self.slippage < 0:
            raise ContractViolation("Fill costs cannot be negative")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


@dataclass(frozen=True)
class PortfolioState:
    as_of_date: str
    cash: float
    equity: float
    gross_exposure: float
    net_exposure: float
    positions_count: int

    def __post_init__(self) -> None:
        if self.cash < 0 or self.equity < 0:
            raise ContractViolation("Portfolio cash and equity cannot be negative")
        if self.gross_exposure < 0 or abs(self.net_exposure) > self.gross_exposure + 1e-12:
            raise ContractViolation("Portfolio exposure values are inconsistent")
        if self.positions_count < 0:
            raise ContractViolation("positions_count cannot be negative")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


@dataclass(frozen=True)
class BacktestResultEnvelope:
    strategy_id: str
    evidence_layer: str
    source_kind: str
    start_date: str
    end_date: str
    metrics: dict[str, float]
    trade_count: int
    schema_version: str = CONTRACT_VERSION
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if pd.Timestamp(self.end_date) < pd.Timestamp(self.start_date):
            raise ContractViolation("Backtest end_date cannot precede start_date")
        if self.trade_count < 0:
            raise ContractViolation("trade_count cannot be negative")
        if not self.evidence_layer or not self.source_kind:
            raise ContractViolation("Backtest result must identify evidence_layer and source_kind")

    def to_dict(self) -> dict[str, object]:
        return _as_serializable(asdict(self))


def _require_columns(frame: pd.DataFrame, required: tuple[str, ...], label: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ContractViolation(f"{label} is missing required columns: {', '.join(missing)}")


def validate_market_frame_contract(frame: pd.DataFrame) -> dict[str, object]:
    required = ("trade_date", "symbol", "open", "high", "low", "close")
    _require_columns(frame, required, "market data")
    if frame.empty:
        raise ContractViolation("market data cannot be empty")
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    if dates.isna().any():
        raise ContractViolation("market data contains invalid trade_date values")
    prices = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if prices.isna().any().any() or (prices <= 0).any().any():
        raise ContractViolation("market data prices must be positive numbers")
    if (prices["high"] < prices[["open", "close"]].max(axis=1)).any() or (prices["low"] > prices[["open", "close"]].min(axis=1)).any() or (prices["high"] < prices["low"]).any():
        raise ContractViolation("market data high/low values are inconsistent")
    keys = frame.assign(_date=dates, _symbol=frame["symbol"].astype(str))[["_date", "_symbol"]]
    if keys.duplicated().any():
        raise ContractViolation("market data contains duplicate date/symbol keys")
    return {"schema_version": CONTRACT_VERSION, "rows": int(len(frame)), "symbols": int(frame["symbol"].nunique())}


def validate_signal_frame_contract(frame: pd.DataFrame) -> dict[str, object]:
    required = (
        "trade_date",
        "symbol",
        "strategy_id",
        "signal",
        "signal_label",
        "reason_code",
        "reason_text_public",
        "reason_evidence",
        "decision_date",
        "effective_date",
    )
    _require_columns(frame, required, "signal data")
    if frame.empty:
        raise ContractViolation("signal data cannot be empty")
    decision_dates = pd.to_datetime(frame["decision_date"], errors="coerce")
    effective_dates = pd.to_datetime(frame["effective_date"], errors="coerce")
    if decision_dates.isna().any() or effective_dates.isna().any():
        raise ContractViolation("signal dates must be valid")
    if (effective_dates < decision_dates).any():
        raise ContractViolation("signal effective_date cannot precede decision_date")
    if frame["reason_code"].isna().any() or frame["reason_code"].astype(str).str.strip().eq("").any():
        raise ContractViolation("signal reason_code values must be present")
    if frame["reason_text_public"].isna().any() or frame["reason_text_public"].astype(str).str.strip().eq("").any():
        raise ContractViolation("signal reason_text_public values must be present")
    if not frame["signal"].isin([-1, 0, 1]).all():
        raise ContractViolation("signal values must be -1, 0, or 1")
    lag = pd.Series(
        [
            int(pd.bdate_range(start=decision, end=effective).size - 1)
            for decision, effective in zip(decision_dates, effective_dates)
        ],
        index=frame.index,
    )
    return {"schema_version": CONTRACT_VERSION, "rows": int(len(frame)), "strategy_ids": sorted(frame["strategy_id"].astype(str).unique().tolist()), "execution_lag_days": int(lag.max())}
