"""Auditable strategy drilldown and safe local research archives."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import hashlib
import json
import math
import re
from typing import Any


class StrategyArchiveError(ValueError):
    """Raised when an archive is unsafe, incomplete or tampered with."""


def build_strategy_result_summary(
    metrics: Mapping[str, Any] | None,
    detail_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the small, stable metric set used by the result first screen."""
    metrics = metrics or {}
    detail_summary = detail_summary or {}

    def number(key: str) -> float | None:
        value = metrics.get(key)
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def count(source: Mapping[str, Any], key: str) -> int:
        value = source.get(key, 0)
        try:
            result = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, result)

    return {
        "total_return": number("total_return"),
        "max_drawdown": number("max_drawdown"),
        "trades": count(metrics, "trades"),
        "total_cost": number("total_cost"),
        "signals": count(detail_summary, "signals"),
        "orders": count(detail_summary, "orders"),
        "fills": count(detail_summary, "fills"),
        "rejected_orders": count(detail_summary, "rejected_orders"),
        "sharpe": number("sharpe"),
        "annual_return": number("annual_return"),
    }


def build_strategy_result_payload(
    *,
    metrics: Mapping[str, Any] | None,
    performance: Mapping[str, Any],
    details: Mapping[str, Any],
    strategy_config: Mapping[str, Any],
    research_diagnostics: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
    integrity: Mapping[str, Any],
    limitations: Sequence[str],
    sensitivity: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep all single-stock result views on one validated presentation payload."""
    if not isinstance(performance, Mapping) or not isinstance(details, Mapping):
        raise ValueError("performance and details are required")
    if not limitations:
        raise ValueError("limitations are required")
    return {
        "summary": build_strategy_result_summary(metrics, details.get("summary")),
        "performance": performance,
        "details": details,
        "strategy_config": dict(strategy_config),
        "research_diagnostics": dict(research_diagnostics),
        "run_manifest": dict(run_manifest),
        "integrity": dict(integrity),
        "limitations": [str(item) for item in limitations],
        "sensitivity": [dict(row) for row in (sensitivity or [])],
    }


_PRIVATE_RE = re.compile(r"(?:private|secret|password|token|[A-Za-z]:[\\/]|/home/|/Users/|\\\\)", re.IGNORECASE)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StrategyArchiveError("archive contains non-serializable material") from exc


def _public(value: Any, *, label: str = "payload") -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if _PRIVATE_RE.search(key_text) or _PRIVATE_RE.search(str(item)):
                raise StrategyArchiveError(f"private material is not allowed in {label}")
            result[key_text] = _public(item, label=label)
        return result
    if isinstance(value, (list, tuple)):
        return [_public(item, label=label) for item in value]
    if callable(value):
        raise StrategyArchiveError(f"callable is not allowed in {label}")
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            raise StrategyArchiveError(f"non-finite value is not allowed in {label}")
        if _PRIVATE_RE.search(str(value)):
            raise StrategyArchiveError(f"private material is not allowed in {label}")
        return value
    raise StrategyArchiveError(f"unsupported value in {label}")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def build_strategy_result_details(
    events: Sequence[Mapping[str, Any]],
    *,
    initial_cash: float,
    fills: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Link public event layers and create auditable cash/position snapshots.

    The backtest event stream already contains public ``FILL`` rows.  When a
    settlement adapter has no separate fill payload, those rows are the
    authoritative local fill source.  The explicit ``fills`` argument remains
    available for callers that have a richer settlement record with fees.
    """
    if initial_cash < 0 or not math.isfinite(float(initial_cash)):
        raise ValueError("initial_cash must be non-negative and finite")
    event_rows = [dict(event) for event in events]
    ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for event in event_rows:
        event_id = _text(event.get("event_id"), "event_id")
        if event_id in ids:
            raise ValueError("duplicate event_id")
        ids.add(event_id)
        by_id[event_id] = event
    signals = {event["event_id"]: event for event in event_rows if event.get("event_type") == "SIGNAL"}
    orders = {event.get("order_id"): event for event in event_rows if event.get("event_type") == "ORDER_INTENT" and event.get("order_id")}
    fills_by_id = {event.get("fill_id"): event for event in event_rows if event.get("event_type") == "FILL" and event.get("fill_id")}
    for event in event_rows:
        if event.get("event_type") in {"ORDER_INTENT", "FILL"}:
            order_id = event.get("order_id")
            order = orders.get(order_id)
            if order is None:
                raise ValueError("event order link is missing")
            signal = next((item for item in signals.values() if item.get("symbol") == event.get("symbol") and item.get("side") == event.get("side") and item.get("decision_date") == event.get("decision_date")), None)
            if signal is None:
                raise ValueError("event signal link is missing")
            if event.get("reason_code") != signal.get("reason_code"):
                raise ValueError("event reason does not match signal")
    fill_source = fills if fills is not None else [
        event for event in event_rows if event.get("event_type") == "FILL"
    ]
    fill_rows = [dict(item) for item in fill_source]
    fill_ids: set[str] = set()
    for fill in fill_rows:
        fill_id = _text(fill.get("fill_id"), "fill_id")
        if fill_id in fill_ids:
            raise ValueError("duplicate fill_id")
        fill_ids.add(fill_id)
        if fill.get("order_id") not in orders:
            raise ValueError("fill order link is missing")
        if fill.get("order_id") in orders and orders[fill["order_id"]].get("status") == "REJECTED":
            raise ValueError("rejected order cannot have a fill")
    trades: list[dict[str, Any]] = []
    for order in sorted(orders.values(), key=lambda row: (str(row.get("effective_date", "")), str(row.get("order_id")))):
        signal = next((item for item in signals.values() if item.get("symbol") == order.get("symbol") and item.get("side") == order.get("side") and item.get("decision_date") == order.get("decision_date")), None)
        fill = next((item for item in fill_rows if item.get("order_id") == order.get("order_id")), None)
        trades.append({
            "signal_id": signal.get("event_id") if signal else None,
            "order_id": order.get("order_id"),
            "fill_id": fill.get("fill_id") if fill else None,
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "decision_date": order.get("decision_date"),
            "effective_date": order.get("effective_date"),
            "status": "FILLED" if fill else order.get("status", "PLANNED"),
            "reason_code": signal.get("reason_code") if signal else order.get("reason_code"),
            "reason_text_public": signal.get("reason_text_public") if signal else order.get("reason_text_public", ""),
            "constraint_status": order.get("constraint_status", "NONE"),
            "quantity": fill.get("quantity", order.get("quantity")) if fill else order.get("quantity"),
            "price": fill.get("price") if fill else None,
        })
    cash = float(initial_cash)
    positions: dict[str, int] = {}
    snapshots: list[dict[str, Any]] = []
    for fill in sorted(fill_rows, key=lambda row: (str(row.get("fill_date", "")), str(row.get("fill_id")))):
        quantity = int(fill["quantity"])
        price = float(fill["price"])
        fee = float(fill.get("fee", 0.0))
        symbol = str(fill["symbol"])
        if fill["side"] == "BUY":
            cash -= quantity * price + fee
            positions[symbol] = positions.get(symbol, 0) + quantity
        elif fill["side"] == "SELL":
            if quantity > positions.get(symbol, 0):
                raise ValueError("fill exceeds position")
            cash += quantity * price - fee
            positions[symbol] -= quantity
            if positions[symbol] == 0:
                del positions[symbol]
        else:
            raise ValueError("fill side is invalid")
        if cash < -1e-9:
            raise ValueError("fills exceed cash")
        snapshots.append({"date": str(fill["fill_date"]), "symbol": symbol, "quantity": int(positions.get(symbol, 0)), "cash": round(cash, 12)})
    return {
        "schema_version": "strategy-result-details.v1",
        "summary": {"signals": len(signals), "orders": len(orders), "fills": len(fill_rows), "rejected_orders": sum(order.get("status") == "REJECTED" for order in orders.values())},
        "trades": trades,
        "positions": snapshots,
    }


def create_strategy_archive(
    *,
    strategy: Mapping[str, Any],
    dataset: Mapping[str, Any],
    execution: Mapping[str, Any],
    result: Mapping[str, Any],
    limitations: Sequence[str],
) -> dict[str, Any]:
    """Create a JSON-safe, checksum-protected local archive."""
    if not limitations:
        raise StrategyArchiveError("archive limitations are required")
    payload = {
        "schema_version": "strategy-archive.v1",
        "manifest": {
            "strategy": _public(strategy, label="strategy"),
            "dataset": _public(dataset, label="dataset"),
            "execution": _public(execution, label="execution"),
            "limitations": _public(list(limitations), label="limitations"),
        },
        "result": _public(result, label="result"),
    }
    checksum = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    payload["manifest"]["checksum"] = checksum
    return payload


def load_strategy_archive(archive: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a defensive copy of a local archive."""
    if not isinstance(archive, Mapping) or archive.get("schema_version") != "strategy-archive.v1":
        raise StrategyArchiveError("archive schema is invalid")
    document = copy.deepcopy(dict(archive))
    manifest = document.get("manifest")
    if not isinstance(manifest, Mapping) or not manifest.get("checksum"):
        raise StrategyArchiveError("archive checksum is missing")
    checksum = manifest["checksum"]
    manifest_without_checksum = dict(manifest)
    del manifest_without_checksum["checksum"]
    unsigned = {"schema_version": document["schema_version"], "manifest": manifest_without_checksum, "result": document.get("result")}
    expected = hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
    if checksum != expected:
        raise StrategyArchiveError("archive checksum mismatch")
    _public(unsigned, label="archive")
    return document
