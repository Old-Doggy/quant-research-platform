"""Explainable signal previews and conservative position-state evaluation."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any

import pandas as pd

from .strategy_rules import CompiledStrategyRules, evaluate_strategy_rules


class PositionRuleError(ValueError):
    """Raised when position and exit rules are incomplete or unsafe."""


@dataclass(frozen=True)
class SignalPreview:
    all_signals: tuple[dict[str, Any], ...]
    visible_signals: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


def _dates(frame: pd.DataFrame) -> pd.Series:
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    if dates.isna().any():
        raise ValueError("trade_date contains invalid values")
    return dates.dt.normalize()


def _rule_fields(node: Mapping[str, Any]) -> list[str]:
    fields: list[str] = []
    kind = node.get("type")
    if kind == "threshold" or kind == "rank":
        fields.append(str(node["field"]))
    elif kind == "cross":
        for side in (node["left"], node["right"]):
            if side.get("kind") == "field":
                fields.append(str(side["name"]))
            else:
                fields.append("close")
    elif kind == "logic":
        for child in node["conditions"]:
            fields.extend(_rule_fields(child))
    return sorted(set(fields))


def _signal_id(strategy_id: str, symbol: str, date: pd.Timestamp, side: str) -> str:
    return f"signal-{hashlib.sha256(f'{strategy_id}|{symbol}|{date:%Y-%m-%d}|{side}'.encode()).hexdigest()[:16]}"


def build_signal_preview(
    frame: pd.DataFrame,
    rules: CompiledStrategyRules,
    *,
    strategy_id: str,
    execution_lag_sessions: int = 1,
    feature_sources: Mapping[str, Mapping[str, Any]] | None = None,
    display_start: object | None = None,
    display_end: object | None = None,
) -> SignalPreview:
    """Create a stable, explanation-first signal list from complete history."""
    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise ValueError("strategy_id is required")
    if isinstance(execution_lag_sessions, bool) or not isinstance(execution_lag_sessions, int) or execution_lag_sessions < 1:
        raise ValueError("execution_lag_sessions must be a positive integer")
    if frame.empty or not {"symbol", "trade_date"}.issubset(frame.columns):
        raise ValueError("signal frame requires symbol and trade_date")
    ordered = frame.copy()
    ordered["trade_date"] = _dates(ordered)
    ordered = ordered.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    evaluated = evaluate_strategy_rules(rules, ordered)
    sessions = tuple(pd.Timestamp(value) for value in pd.unique(ordered["trade_date"].sort_values()))
    sources = feature_sources or {}
    fields = sorted(set(_rule_fields(rules.buy.to_dict()) + _rule_fields(rules.sell.to_dict())))
    warmup = max((int(node.get("params", {}).get("period", 1)) for node in _indicator_nodes(rules.buy.to_dict()) + _indicator_nodes(rules.sell.to_dict())), default=1) - 1
    records: list[dict[str, Any]] = []
    for position, row in ordered.iterrows():
        date = pd.Timestamp(row["trade_date"])
        for side, active in (("BUY", bool(evaluated.loc[position, "buy"])), ("SELL", bool(evaluated.loc[position, "sell"]))):
            if not active:
                continue
            session_index = sessions.index(date)
            effective = sessions[session_index + execution_lag_sessions] if session_index + execution_lag_sessions < len(sessions) else None
            evidence_sources = [sources.get(field, {}).get("source", "unknown") for field in fields]
            available_at = [sources.get(field, {}).get("available_at", "unknown") for field in fields]
            records.append({
                "signal_id": _signal_id(strategy_id, str(row["symbol"]), date, side),
                "strategy_id": strategy_id,
                "symbol": str(row["symbol"]),
                "side": side,
                "decision_date": date.strftime("%Y-%m-%d"),
                "effective_date": effective.strftime("%Y-%m-%d") if effective is not None else None,
                "reason_code": "buy_rule_true" if side == "BUY" else "sell_rule_true",
                "reason_text_public": "买入规则满足" if side == "BUY" else "卖出规则满足",
                "evidence": {"fields": fields, "source": evidence_sources[0] if len(set(evidence_sources)) == 1 else evidence_sources, "available_at": available_at[0] if len(set(available_at)) == 1 else available_at, "warmup_complete": position >= warmup},
            })
    encoded = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    visible = records
    start = pd.Timestamp(display_start).normalize() if display_start is not None else None
    end = pd.Timestamp(display_end).normalize() if display_end is not None else None
    if start is not None and end is not None and start > end:
        raise ValueError("display_start cannot be after display_end")
    if start is not None or end is not None:
        visible = [item for item in records if (start is None or pd.Timestamp(item["decision_date"]) >= start) and (end is None or pd.Timestamp(item["decision_date"]) <= end)]
    return SignalPreview(tuple(records), tuple(visible), {"warmup_sessions": max(warmup, 0), "history_fingerprint": fingerprint, "history_rows": len(ordered)})


def _indicator_nodes(node: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if node.get("type") == "cross":
        for operand in (node["left"], node["right"]):
            if operand.get("kind") == "indicator":
                result.append(dict(operand))
    elif node.get("type") == "logic":
        for child in node["conditions"]:
            result.extend(_indicator_nodes(child))
    return result


def evaluate_position_rules(
    frame: pd.DataFrame,
    *,
    buy_dates: Iterable[object],
    exit_dates: Iterable[object],
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    execution_lag_sessions: int,
) -> pd.DataFrame:
    """Return daily position states; ambiguous OHLC paths remain non-executable."""
    exits = {pd.Timestamp(item).normalize() for item in exit_dates}
    if stop_loss_pct is None and take_profit_pct is None and not exits:
        raise PositionRuleError("an exit rule is required")
    if stop_loss_pct is not None and (not isinstance(stop_loss_pct, (int, float)) or stop_loss_pct <= 0 or stop_loss_pct >= 1):
        raise PositionRuleError("stop_loss must be positive and below one")
    if take_profit_pct is not None and (not isinstance(take_profit_pct, (int, float)) or take_profit_pct <= 0):
        raise PositionRuleError("take_profit must be positive")
    if isinstance(execution_lag_sessions, bool) or not isinstance(execution_lag_sessions, int) or execution_lag_sessions < 1:
        raise PositionRuleError("execution_lag_sessions must be positive")
    result = frame.copy().sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    result["trade_date"] = _dates(result)
    buys = {pd.Timestamp(item).normalize() for item in buy_dates}
    states: list[str] = []
    reasons: list[str] = []
    executable: list[bool] = []
    entry_price: float | None = None
    pending_entry = False
    holding = False
    for _, row in result.iterrows():
        date = pd.Timestamp(row["trade_date"])
        if date in buys and not holding and not pending_entry:
            pending_entry = True
        if pending_entry:
            if date in buys:
                states.append("PENDING_ENTRY")
                reasons.append("buy_signal_pending")
                executable.append(False)
                continue
            pending_entry = False
            holding = True
            entry_price = float(row["close"])
            states.append("HOLD")
            reasons.append("entry_filled")
            executable.append(True)
            continue
        if not holding:
            states.append("FLAT")
            reasons.append("no_position")
            executable.append(True)
            continue
        stop = stop_loss_pct is not None and float(row["low"]) <= entry_price * (1 - float(stop_loss_pct))
        take = take_profit_pct is not None and float(row["high"]) >= entry_price * (1 + float(take_profit_pct))
        if stop and take:
            states.append("EXIT_UNCERTAIN")
            reasons.append("ambiguous_bar_path")
            executable.append(False)
            holding = False
        elif stop:
            states.append("EXIT_STOP_LOSS")
            reasons.append("stop_loss")
            executable.append(True)
            holding = False
        elif take:
            states.append("EXIT_TAKE_PROFIT")
            reasons.append("take_profit")
            executable.append(True)
            holding = False
        elif date in exits:
            states.append("EXIT_EXPLICIT")
            reasons.append("explicit_exit")
            executable.append(True)
            holding = False
        else:
            states.append("HOLD")
            reasons.append("hold")
            executable.append(True)
    result["state"] = states
    result["reason_code"] = reasons
    result["executable"] = pd.Series(executable, dtype=object)
    return result
