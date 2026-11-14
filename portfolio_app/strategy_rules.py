"""Restricted, explainable buy and sell rules for offline strategy research.

Rules are data, never Python code.  The compiler accepts a deliberately small
schema and the evaluator interprets that schema over a market frame.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .indicator_math import ema, moving_average, rsi


class RuleValidationError(ValueError):
    """Raised when a strategy rule is outside the supported safe schema."""


_THRESHOLD_OPS = {">", ">=", "<", "<=", "==", "!="}
_LOGIC_OPS = {"AND", "OR"}
_CROSS_DIRECTIONS = {"up", "down"}
_RANK_DIRECTIONS = {"top", "bottom"}
_NUMERIC_TYPES = {"price", "volume", "return", "score"}


@dataclass(frozen=True)
class _Rule:
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _copy_public(self.payload)


@dataclass(frozen=True)
class CompiledStrategyRules:
    buy: _Rule
    sell: _Rule

    def to_dict(self) -> dict[str, Any]:
        return {"buy": self.buy.to_dict(), "sell": self.sell.to_dict()}


def _copy_public(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_public(item) for item in value]
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuleValidationError(f"{label} must be an object")
    return value


def _field(value: Any, field_types: Mapping[str, str], label: str) -> str:
    if not isinstance(value, str) or value not in field_types:
        raise RuleValidationError(f"{label} field is not allowlisted")
    if field_types[value] not in _NUMERIC_TYPES:
        raise RuleValidationError(f"{label} field type is not numeric")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(float(value)):
        raise RuleValidationError(f"{label} must be numeric")
    return float(value)


def _operand(value: Any, field_types: Mapping[str, str], label: str) -> dict[str, Any]:
    if isinstance(value, str):
        name = _field(value, field_types, label)
        return {"kind": "field", "name": name}
    item = _mapping(value, label)
    if set(item) - {"kind", "name", "params"}:
        raise RuleValidationError(f"{label} contains an unknown key")
    if item.get("kind") != "indicator" or not isinstance(item.get("name"), str):
        raise RuleValidationError(f"{label} must be an allowlisted field or indicator")
    name = str(item["name"]).upper()
    params = item.get("params", {})
    if name not in {"MA", "EMA", "RSI"} or not isinstance(params, Mapping):
        raise RuleValidationError(f"{label} indicator is not allowlisted")
    if set(params) - {"period"}:
        raise RuleValidationError(f"{label} indicator has an unknown parameter")
    period = params.get("period", 14)
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0 or period > 500:
        raise RuleValidationError(f"{label} indicator window is invalid")
    required = {"close"}
    if not required.issubset(field_types):
        raise RuleValidationError(f"{label} indicator fields are unavailable")
    return {"kind": "indicator", "name": name, "params": {"period": period}}


def _compile(node: Any, field_types: Mapping[str, str]) -> dict[str, Any]:
    item = _mapping(node, "rule")
    kind = item.get("type")
    if kind == "threshold":
        allowed = {"type", "field", "operator", "value"}
        if set(item) - allowed:
            raise RuleValidationError("threshold contains an unknown key")
        field = _field(item.get("field"), field_types, "threshold")
        operator = item.get("operator")
        if operator not in _THRESHOLD_OPS:
            raise RuleValidationError("threshold operator is invalid")
        value = _number(item.get("value"), "threshold value")
        return {"type": "threshold", "field": field, "operator": operator, "value": value}
    if kind == "cross":
        allowed = {"type", "left", "right", "direction"}
        if set(item) - allowed:
            raise RuleValidationError("cross contains an unknown key")
        direction = item.get("direction")
        if direction not in _CROSS_DIRECTIONS:
            raise RuleValidationError("cross direction is invalid")
        left = _operand(item.get("left"), field_types, "cross left")
        right = _operand(item.get("right"), field_types, "cross right")
        return {"type": "cross", "left": left, "right": right, "direction": direction}
    if kind == "rank":
        allowed = {"type", "field", "direction", "limit"}
        if set(item) - allowed:
            raise RuleValidationError("rank contains an unknown key")
        field = _field(item.get("field"), field_types, "rank")
        direction = item.get("direction")
        if direction not in _RANK_DIRECTIONS:
            raise RuleValidationError("rank direction is invalid")
        limit = item.get("limit")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 10000:
            raise RuleValidationError("rank limit is invalid")
        return {"type": "rank", "field": field, "direction": direction, "limit": limit}
    if kind == "logic":
        allowed = {"type", "operator", "conditions"}
        if set(item) - allowed:
            raise RuleValidationError("logic contains an unknown key")
        operator = item.get("operator")
        conditions = item.get("conditions")
        if operator not in _LOGIC_OPS:
            raise RuleValidationError("logic operator is invalid")
        if not isinstance(conditions, (list, tuple)) or len(conditions) < 2:
            raise RuleValidationError("logic requires at least two conditions")
        if len(conditions) > 16:
            raise RuleValidationError("logic has too many conditions")
        return {"type": "logic", "operator": operator, "conditions": [_compile(child, field_types) for child in conditions]}
    raise RuleValidationError("rule type is invalid")


def compile_strategy_rules(
    buy_rule: Any,
    sell_rule: Any,
    *,
    field_types: Mapping[str, str],
) -> CompiledStrategyRules:
    """Validate separate buy and sell rules without accepting executable code."""
    if not isinstance(field_types, Mapping) or not field_types:
        raise RuleValidationError("field_types are required")
    if buy_rule is None:
        raise RuleValidationError("buy_rule is required")
    if sell_rule is None:
        raise RuleValidationError("sell_rule is required")
    return CompiledStrategyRules(_Rule(_compile(buy_rule, field_types)), _Rule(_compile(sell_rule, field_types)))


def _operand_values(operand: Mapping[str, Any], frame: pd.DataFrame) -> pd.Series:
    if operand["kind"] == "field":
        return pd.to_numeric(frame[operand["name"]], errors="coerce")
    name = operand["name"]
    params = operand["params"]
    output = np.full(len(frame), np.nan, dtype=float)
    indexed = frame.assign(_rule_position=np.arange(len(frame)), _rule_date=pd.to_datetime(frame["trade_date"], errors="coerce"))
    for _, group in indexed.groupby("symbol", sort=False):
        ordered = group.sort_values("_rule_date", kind="mergesort")
        close = pd.to_numeric(ordered["close"], errors="coerce")
        period = params["period"]
        values = moving_average(close, period) if name == "MA" else ema(close, period) if name == "EMA" else rsi(close, period)
        output[ordered["_rule_position"].to_numpy()] = values.to_numpy()
    return pd.Series(output, index=frame.index)


def _evaluate(node: Mapping[str, Any], frame: pd.DataFrame) -> pd.Series:
    kind = node["type"]
    if kind == "threshold":
        value = pd.to_numeric(frame[node["field"]], errors="coerce")
        threshold = node["value"]
        return {">": value > threshold, ">=": value >= threshold, "<": value < threshold, "<=": value <= threshold, "==": value == threshold, "!=": value != threshold}[node["operator"]].fillna(False).astype(bool)
    if kind == "rank":
        values = pd.to_numeric(frame[node["field"]], errors="coerce")
        ranks = values.groupby(pd.to_datetime(frame["trade_date"]), sort=False).rank(method="first", ascending=node["direction"] == "bottom")
        return ranks.le(node["limit"]).fillna(False).astype(bool)
    if kind == "cross":
        difference = _operand_values(node["left"], frame) - _operand_values(node["right"], frame)
        previous = difference.groupby(frame["symbol"], sort=False).shift(1)
        current = difference > 0 if node["direction"] == "up" else difference < 0
        crossed = (previous <= 0) & current if node["direction"] == "up" else (previous >= 0) & current
        return crossed.fillna(False).astype(bool)
    values = [_evaluate(child, frame) for child in node["conditions"]]
    result = values[0]
    for value in values[1:]:
        result = result & value if node["operator"] == "AND" else result | value
    return result.astype(bool)


def evaluate_strategy_rules(rules: CompiledStrategyRules, frame: pd.DataFrame) -> pd.DataFrame:
    """Evaluate compiled rules while preserving the input index and row order."""
    if not isinstance(rules, CompiledStrategyRules):
        raise RuleValidationError("rules must be compiled first")
    required = {"symbol", "trade_date"}
    if not required.issubset(frame.columns):
        raise RuleValidationError("frame requires symbol and trade_date")
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    if dates.isna().any():
        raise RuleValidationError("trade_date contains invalid values")
    return pd.DataFrame({"buy": _evaluate(rules.buy.payload, frame), "sell": _evaluate(rules.sell.payload, frame)}, index=frame.index)
