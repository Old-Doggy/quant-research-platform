"""Safe, public expression trees for offline factor research.

This module intentionally has no Python evaluation path.  A user expression is
parsed into a small immutable tree, checked against explicit budgets, and then
interpreted over a pandas frame.  The tree is the public artifact; private
formula text, paths, and executable objects are never accepted by the parser.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


class ExpressionCompileError(ValueError):
    """Raised when an expression is outside the public safe subset."""


class ExpressionEvaluationError(ValueError):
    """Raised when a valid expression cannot be evaluated on a frame."""


@dataclass(frozen=True)
class ExpressionBudget:
    """Resource limits applied before an expression can run."""

    max_nodes: int = 64
    max_depth: int = 12
    max_window: int = 500
    max_rows: int = 1_000_000
    max_operations: int = 25_000_000

    def __post_init__(self) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (
            self.max_nodes, self.max_depth, self.max_window, self.max_rows, self.max_operations
        )):
            raise ExpressionCompileError("expression budget values must be positive integers")


@dataclass(frozen=True)
class _Node:
    kind: str
    op: str | None = None
    name: str | None = None
    value: int | float | bool | None = None
    children: tuple["_Node", ...] = ()
    window: int | None = None
    params: tuple[tuple[str, int | float], ...] = ()


@dataclass(frozen=True)
class CompiledExpression:
    """Validated expression tree and its public resource summary."""

    root: _Node
    fields: tuple[str, ...]
    indicators: tuple[str, ...]
    windows: tuple[int, ...]
    node_count: int
    max_depth: int

    def to_dict(self) -> dict[str, object]:
        """Return a safe structural summary without executable material."""
        return {
            "tree": _node_to_dict(self.root),
            "fields": list(self.fields),
            "indicators": list(self.indicators),
            "windows": list(self.windows),
            "node_count": self.node_count,
            "max_depth": self.max_depth,
        }


def _node_to_dict(node: _Node) -> dict[str, object]:
    if node.kind == "field":
        return {"kind": "field", "name": node.name}
    if node.kind == "literal":
        return {"kind": "literal", "value": node.value}
    if node.kind == "indicator":
        return {"kind": "indicator", "name": node.name, "params": dict(node.params)}
    payload: dict[str, object] = {"kind": node.kind}
    if node.op is not None:
        payload["op"] = node.op
    if node.kind == "rolling":
        payload["window"] = node.window
        payload["operand"] = _node_to_dict(node.children[0])
    elif node.kind == "unary":
        payload["operand"] = _node_to_dict(node.children[0])
    elif node.kind == "boolean":
        payload["operands"] = [_node_to_dict(child) for child in node.children]
    else:
        payload["left"] = _node_to_dict(node.children[0])
        payload["right"] = _node_to_dict(node.children[1])
    return payload


_BINARY_OPERATORS = {"add", "sub", "mul", "div", "mod"}
_COMPARE_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte"}
_BOOLEAN_OPERATORS = {"and", "or"}
_ROLLING_OPERATORS = {"mean", "sum", "min", "max", "std"}
_UNARY_OPERATORS = {"positive", "negative", "not"}

_INDICATOR_FIELDS = {
    "MA": ("close",), "EMA": ("close",), "BOLL": ("close",), "RSI": ("close",),
    "MACD": ("close",), "KDJ": ("close", "high", "low"), "ATR": ("close", "high", "low"),
    "OBV": ("close", "vol"), "VWAP": ("close", "high", "low", "vol"),
    "ROC": ("close",), "CCI": ("close", "high", "low"), "DMI": ("close", "high", "low"),
    "BIAS": ("close",), "WR": ("close", "high", "low"), "DONCHIAN": ("high", "low"),
    "VOL_MA": ("vol",), "VOLUME_RATIO": ("vol",),
}

_NODE_KEYS = {
    "field": {"kind", "name"},
    "literal": {"kind", "value"},
    "binary": {"kind", "op", "left", "right"},
    "compare": {"kind", "op", "left", "right"},
    "boolean": {"kind", "op", "operands"},
    "unary": {"kind", "op", "operand"},
    "rolling": {"kind", "op", "window", "operand"},
    "indicator": {"kind", "name", "params"},
}


def _safe_number(value: object) -> int | float | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, complex):
        number = float(value)
        if math.isfinite(number):
            return int(value) if isinstance(value, int) else number
    raise ExpressionCompileError("literal must be a finite number or boolean")


def _safe_key_set(value: object, label: str) -> set[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, set | frozenset | list | tuple):
        raise ExpressionCompileError(f"{label} must be a collection of field names")
    fields = {str(item) for item in value}
    if any(not item or not item.replace("_", "").isalnum() for item in fields):
        raise ExpressionCompileError(f"{label} contains an invalid field name")
    return fields


def _mapping_node(payload: Mapping[str, object], allowed_fields: set[str], budget: ExpressionBudget) -> _Node:
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in {"field", "literal", "binary", "compare", "boolean", "unary", "rolling", "indicator"}:
        raise ExpressionCompileError("unknown expression node kind")
    if any(not isinstance(key, str) for key in payload):
        raise ExpressionCompileError("expression node keys must be text")
    unknown = set(payload) - _NODE_KEYS[kind]
    if unknown:
        raise ExpressionCompileError(f"unknown expression node key: {sorted(unknown)[0]}")
    if kind == "field":
        name = payload.get("name")
        if not isinstance(name, str) or name not in allowed_fields:
            raise ExpressionCompileError("field is not allowlisted")
        return _Node(kind="field", name=name)
    if kind == "literal":
        return _Node(kind="literal", value=_safe_number(payload.get("value")))
    if kind in {"binary", "compare"}:
        op = payload.get("op")
        allowed = _BINARY_OPERATORS if kind == "binary" else _COMPARE_OPERATORS
        if op not in allowed:
            raise ExpressionCompileError("operator is not allowlisted")
        left, right = payload.get("left"), payload.get("right")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise ExpressionCompileError(f"{kind} operands must be expression nodes")
        return _Node(kind=kind, op=str(op), children=(
            _mapping_node(left, allowed_fields, budget), _mapping_node(right, allowed_fields, budget)
        ))
    if kind == "boolean":
        op = payload.get("op")
        operands = payload.get("operands")
        if op not in _BOOLEAN_OPERATORS or not isinstance(operands, (list, tuple)) or len(operands) < 2:
            raise ExpressionCompileError("boolean operator or operands are invalid")
        if not all(isinstance(item, Mapping) for item in operands):
            raise ExpressionCompileError("boolean operands must be expression nodes")
        return _Node(kind=kind, op=str(op), children=tuple(_mapping_node(item, allowed_fields, budget) for item in operands))
    if kind == "unary":
        op, operand = payload.get("op"), payload.get("operand")
        if op not in _UNARY_OPERATORS or not isinstance(operand, Mapping):
            raise ExpressionCompileError("unary operator or operand is invalid")
        return _Node(kind=kind, op=str(op), children=(_mapping_node(operand, allowed_fields, budget),))
    if kind == "rolling":
        op, window, operand = payload.get("op"), payload.get("window"), payload.get("operand")
        if op not in _ROLLING_OPERATORS or isinstance(window, bool) or not isinstance(window, int):
            raise ExpressionCompileError("rolling operator or window is invalid")
        if window <= 0 or window > budget.max_window:
            raise ExpressionCompileError("rolling window exceeds expression budget")
        if not isinstance(operand, Mapping):
            raise ExpressionCompileError("rolling operand must be an expression node")
        return _Node(kind=kind, op=str(op), window=window, children=(_mapping_node(operand, allowed_fields, budget),))
    name, params = payload.get("name"), payload.get("params") or {}
    if not isinstance(name, str) or name.upper() not in _INDICATOR_FIELDS or not isinstance(params, Mapping):
        raise ExpressionCompileError("indicator is not allowlisted")
    indicator = name.upper()
    missing = set(_INDICATOR_FIELDS[indicator]) - allowed_fields
    if missing:
        raise ExpressionCompileError(f"indicator fields are not allowlisted: {sorted(missing)[0]}")
    if any(not isinstance(key, str) for key in params):
        raise ExpressionCompileError("indicator parameter keys must be text")
    try:
        from .indicators import normalize_indicator_config

        normalized_params = normalize_indicator_config([{"key": indicator, "params": dict(params)}])[0]["params"]
    except (TypeError, ValueError, KeyError) as exc:
        raise ExpressionCompileError(f"indicator parameter is invalid: {exc}") from exc
    safe_params: list[tuple[str, int | float]] = []
    for key, value in normalized_params.items():
        safe_value = _safe_number(value)
        if isinstance(safe_value, bool):
            raise ExpressionCompileError("indicator parameters must be numeric")
        safe_params.append((key, safe_value))
    return _Node(kind="indicator", name=indicator, params=tuple(sorted(safe_params)))


def _ast_node(node: ast.AST, allowed_fields: set[str], budget: ExpressionBudget) -> _Node:
    if isinstance(node, ast.Constant):
        return _Node(kind="literal", value=_safe_number(node.value))
    if isinstance(node, ast.Name):
        if node.id not in allowed_fields:
            raise ExpressionCompileError("field is not allowlisted")
        return _Node(kind="field", name=node.id)
    if isinstance(node, ast.BinOp):
        operator_map = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div", ast.Mod: "mod"}
        op = next((name for operator, name in operator_map.items() if isinstance(node.op, operator)), None)
        if op is None:
            raise ExpressionCompileError("operator is not allowlisted")
        return _Node(kind="binary", op=op, children=(_ast_node(node.left, allowed_fields, budget), _ast_node(node.right, allowed_fields, budget)))
    if isinstance(node, ast.UnaryOp):
        operator_map = {ast.UAdd: "positive", ast.USub: "negative", ast.Not: "not"}
        op = next((name for operator, name in operator_map.items() if isinstance(node.op, operator)), None)
        if op is None:
            raise ExpressionCompileError("operator is not allowlisted")
        return _Node(kind="unary", op=op, children=(_ast_node(node.operand, allowed_fields, budget),))
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ExpressionCompileError("chained comparisons are not allowed")
        operator_map = {ast.Eq: "eq", ast.NotEq: "ne", ast.Gt: "gt", ast.GtE: "gte", ast.Lt: "lt", ast.LtE: "lte"}
        op = next((name for operator, name in operator_map.items() if isinstance(node.ops[0], operator)), None)
        if op is None:
            raise ExpressionCompileError("operator is not allowlisted")
        return _Node(kind="compare", op=op, children=(_ast_node(node.left, allowed_fields, budget), _ast_node(node.comparators[0], allowed_fields, budget)))
    if isinstance(node, ast.BoolOp):
        op = "and" if isinstance(node.op, ast.And) else "or" if isinstance(node.op, ast.Or) else None
        if op is None:
            raise ExpressionCompileError("boolean operator is not allowlisted")
        return _Node(kind="boolean", op=op, children=tuple(_ast_node(item, allowed_fields, budget) for item in node.values))
    raise ExpressionCompileError("calls, attributes, subscripts, and other Python syntax are not allowed")


def _tree_stats(root: _Node, budget: ExpressionBudget) -> tuple[tuple[str, ...], tuple[str, ...], tuple[int, ...], int, int]:
    fields: set[str] = set()
    indicators: list[str] = []
    windows: list[int] = []
    count = 0
    maximum = 0

    def visit(node: _Node, depth: int) -> None:
        nonlocal count, maximum
        count += 1
        maximum = max(maximum, depth)
        if count > budget.max_nodes or maximum > budget.max_depth:
            raise ExpressionCompileError("expression exceeds node or depth budget")
        if node.kind == "field" and node.name:
            fields.add(node.name)
        if node.kind == "indicator" and node.name:
            indicators.append(node.name)
            fields.update(_INDICATOR_FIELDS[node.name])
        if node.kind == "rolling" and node.window:
            windows.append(node.window)
        for child in node.children:
            visit(child, depth + 1)

    visit(root, 1)
    return tuple(sorted(fields)), tuple(dict.fromkeys(indicators)), tuple(windows), count, maximum


def compile_expression(
    expression: str | Mapping[str, object],
    *,
    allowed_fields: set[str] | list[str] | tuple[str, ...],
    budget: ExpressionBudget | None = None,
) -> CompiledExpression:
    """Parse and validate text or a safe tree without executing user code."""
    budget = budget or ExpressionBudget()
    fields = _safe_key_set(allowed_fields, "allowed_fields")
    if isinstance(expression, str):
        try:
            parsed = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ExpressionCompileError("expression syntax is invalid") from exc
        root = _ast_node(parsed.body, fields, budget)
    elif isinstance(expression, Mapping):
        root = _mapping_node(expression, fields, budget)
    else:
        raise ExpressionCompileError("expression must be text or a safe mapping")
    summary = _tree_stats(root, budget)
    return CompiledExpression(root=root, fields=summary[0], indicators=summary[1], windows=summary[2], node_count=summary[3], max_depth=summary[4])


def _ordered_positions(frame: pd.DataFrame) -> np.ndarray:
    if "symbol" not in frame or "trade_date" not in frame:
        raise ExpressionEvaluationError("rolling expressions require symbol and trade_date columns")
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    if dates.isna().any():
        raise ExpressionEvaluationError("trade_date contains invalid values")
    return frame.assign(_restricted_date=dates, _restricted_pos=np.arange(len(frame))).sort_values(
        ["symbol", "_restricted_date", "_restricted_pos"], kind="mergesort"
    )["_restricted_pos"].to_numpy()


def _rolling(values: pd.Series, frame: pd.DataFrame, op: str, window: int) -> pd.Series:
    positions = _ordered_positions(frame)
    symbols = frame["symbol"].astype(str).to_numpy()
    ordered_values = np.asarray(values, dtype=float)[positions]
    ordered_symbols = symbols[positions]
    output = np.full(len(frame), np.nan, dtype=float)
    for symbol in pd.unique(ordered_symbols):
        ordered_indices = np.flatnonzero(ordered_symbols == symbol)
        series = pd.Series(ordered_values[ordered_indices])
        rolling = series.rolling(window, min_periods=window)
        calculated = getattr(rolling, op)()
        output[positions[ordered_indices]] = calculated.to_numpy()
    return pd.Series(output, index=frame.index)


def _evaluate_node(node: _Node, frame: pd.DataFrame) -> pd.Series:
    if node.kind == "literal":
        return pd.Series(node.value, index=frame.index, dtype=float if not isinstance(node.value, bool) else bool)
    if node.kind == "field":
        return pd.to_numeric(frame[node.name], errors="coerce")
    if node.kind == "indicator":
        from .indicators import calculate_registered_indicators

        params = dict(node.params)
        columns = {
            "MA": f"ma{params.get('period', 20)}", "EMA": f"ema{params.get('period', 20)}",
            "BOLL": f"boll_mid{params.get('period', 20)}", "RSI": f"rsi{params.get('period', 14)}",
            "MACD": "macd", "KDJ": "k", "ATR": f"atr{params.get('period', 14)}", "OBV": "obv",
            "VWAP": "vwap", "ROC": f"roc{params.get('period', 20)}", "CCI": f"cci{params.get('period', 20)}",
            "DMI": f"adx{params.get('period', 14)}", "BIAS": f"bias{params.get('period', 20)}", "WR": f"wr{params.get('period', 14)}",
            "DONCHIAN": f"donchian_middle{params.get('period', 20)}", "VOL_MA": f"vol_ma{params.get('period', 20)}",
            "VOLUME_RATIO": f"volume_ratio{params.get('period', 20)}",
        }
        if "symbol" not in frame or "trade_date" not in frame:
            raise ExpressionEvaluationError("indicator expressions require symbol and trade_date columns")
        dates = pd.to_datetime(frame["trade_date"], errors="coerce")
        if dates.isna().any():
            raise ExpressionEvaluationError("trade_date contains invalid values")
        output = np.full(len(frame), np.nan, dtype=float)
        indexed = frame.assign(_restricted_date=dates, _restricted_position=np.arange(len(frame)))
        for _, group in indexed.groupby("symbol", sort=False):
            ordered = group.sort_values("_restricted_date", kind="mergesort")
            calculated = calculate_registered_indicators(ordered, [{"key": node.name, "params": params}])
            ordered_positions = ordered["_restricted_position"].to_numpy()
            output[ordered_positions] = pd.to_numeric(calculated[columns[node.name]], errors="coerce").to_numpy()
        return pd.Series(output, index=frame.index, name=columns[node.name])
    if node.kind in {"binary", "compare", "boolean", "unary", "rolling"}:
        values = [_evaluate_node(child, frame) for child in node.children]
    if node.kind == "binary":
        left, right = values
        if node.op == "add": return left + right
        if node.op == "sub": return left - right
        if node.op == "mul": return left * right
        if node.op == "div": return left / right.replace(0, np.nan)
        return left % right.replace(0, np.nan)
    if node.kind == "compare":
        left, right = values
        return {"eq": left == right, "ne": left != right, "gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[node.op].fillna(False).astype(bool)
    if node.kind == "boolean":
        result = values[0].fillna(False).astype(bool)
        for value in values[1:]:
            result = result & value.fillna(False).astype(bool) if node.op == "and" else result | value.fillna(False).astype(bool)
        return result
    if node.kind == "unary":
        value = values[0]
        if node.op == "positive": return +value
        if node.op == "negative": return -value
        return ~value.fillna(False).astype(bool)
    return _rolling(values[0], frame, node.op, node.window)


def evaluate_expression(expression: CompiledExpression, frame: pd.DataFrame, *, budget: ExpressionBudget | None = None) -> pd.Series:
    """Interpret a compiled tree over a frame using only allowlisted operations."""
    if not isinstance(expression, CompiledExpression):
        raise ExpressionEvaluationError("expression must be compiled first")
    budget = budget or ExpressionBudget()
    if len(frame) > budget.max_rows:
        raise ExpressionEvaluationError("frame exceeds expression row budget")
    operations = len(frame) * expression.node_count
    if operations > budget.max_operations:
        raise ExpressionEvaluationError("expression exceeds operation budget")
    missing = sorted(set(expression.fields) - set(frame.columns))
    if missing:
        raise ExpressionEvaluationError(f"frame is missing expression field: {missing[0]}")
    return _evaluate_node(expression.root, frame)
