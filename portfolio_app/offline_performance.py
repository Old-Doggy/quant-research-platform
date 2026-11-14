"""Performance, NAV reconciliation and Stage 28 truth fixtures."""
from __future__ import annotations

import math
from typing import Any, Mapping

from .offline_ledger import FillEvent, LedgerState, apply_fill
from .offline_market_rules import CompanyAction, apply_company_action


def build_daily_nav(
    state: LedgerState,
    *,
    prices: Mapping[str, float],
    price_status: Mapping[str, str],
    tradable: Mapping[str, bool] | None = None,
    as_of: str,
) -> dict[str, Any]:
    tradable = tradable or {}
    values: dict[str, float] = {}
    stale: list[str] = []
    executable: list[str] = []
    for symbol, quantity in state.positions.items():
        if symbol not in prices or symbol not in price_status or prices[symbol] is None:
            raise ValueError(f"missing price for {symbol}")
        price = float(prices[symbol])
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"invalid price for {symbol}")
        status = price_status[symbol]
        if status not in {"fresh", "stale"}:
            raise ValueError(f"missing price for {symbol}")
        values[symbol] = quantity * price
        if status == "stale":
            stale.append(symbol)
        elif bool(tradable.get(symbol, False)):
            executable.append(symbol)
    positions_value = float(sum(values.values()))
    nav = float(state.cash) + positions_value
    payload = {
        "as_of": as_of,
        "cash": float(state.cash),
        "positions_value": positions_value,
        "nav": nav,
        "gross_exposure": positions_value,
        "net_exposure": positions_value,
        "position_values": values,
        "executable_symbols": sorted(executable),
        "diagnostics": {"stale_valuation_symbols": sorted(stale), "fees": float(state.total_fees)},
    }
    payload["reconciliation_delta"] = payload["nav"] - (payload["cash"] + payload["positions_value"])
    return payload


def reconcile_nav(nav: Mapping[str, Any]) -> dict[str, Any]:
    delta = float(nav.get("reconciliation_delta", float("nan")))
    return {"status": "reconciled" if math.isfinite(delta) and abs(delta) <= 1e-9 else "mismatch", "delta": delta}


def calculate_performance_metrics(nav_rows: list[Mapping[str, Any]], *, annualization_sessions: int = 252) -> dict[str, Any]:
    if not isinstance(annualization_sessions, int) or annualization_sessions <= 0:
        raise ValueError("annualization_sessions must be positive")
    values = [float(row["nav"]) for row in nav_rows]
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("NAV values must be positive finite numbers")
    if len(values) < 2:
        return {"observations": 0, "total_return": None, "annual_return": None, "annual_volatility": None, "sharpe": None, "sortino": None, "max_drawdown": None}
    returns = [current / previous - 1.0 for previous, current in zip(values, values[1:])]
    total_return = values[-1] / values[0] - 1.0
    annual_return = (values[-1] / values[0]) ** (annualization_sessions / len(returns)) - 1.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    volatility = math.sqrt(variance) * math.sqrt(annualization_sessions)
    downside = [min(value, 0.0) ** 2 for value in returns]
    downside_deviation = math.sqrt(sum(downside) / len(downside)) * math.sqrt(annualization_sessions)
    running = values[0]
    max_drawdown = 0.0
    for value in values:
        running = max(running, value)
        max_drawdown = min(max_drawdown, value / running - 1.0)
    return {
        "observations": len(returns),
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": volatility,
        "sharpe": (mean * annualization_sessions / volatility) if volatility > 0 else None,
        "sortino": (mean * annualization_sessions / downside_deviation) if downside_deviation > 0 else None,
        "max_drawdown": max_drawdown,
    }


def run_stage28_truth_exit() -> dict[str, Any]:
    """Run small deterministic checks for the complete Stage 28 semantics."""
    from .offline_execution import ExecutionSpec, allocate_session_capacity, calculate_post_entry_return

    bars = {
        "2024-01-05": {"open": 100.0, "close": 100.0},
        "2024-01-08": {"open": 120.0, "close": 132.0},
        "2024-01-09": {"open": 125.0, "close": 144.0},
    }
    spec = ExecutionSpec("truth-next-open", "open", "next_open", 0.0, 0.0, "cn_stock")
    jump_return = calculate_post_entry_return(bars, sessions=tuple(bars), decision_date="2024-01-05", spec=spec)
    state = LedgerState(initial_cash=1_000.0)
    rejected_state, rejected = apply_fill(state, FillEvent("f-reject", "o-reject", "600000.SH", "BUY", 100, 20.0, "2024-01-08"), commission_bps=0.0)
    capacity = allocate_session_capacity(orders=({"order_id": "partial", "quantity": 300},), session_volume=1_000, participation_rate=0.2, lot_size=100, allow_partial_fill=True)
    dividend_state, dividend = apply_company_action(LedgerState(initial_cash=1_000.0, positions={"600000.SH": 100}), CompanyAction("div-truth", "cash_dividend", "600000.SH", "2024-01-08", cash_per_share=0.5))
    checks = {
        "jump_excludes_pre_entry_return": math.isclose(jump_return, 0.10),
        "rejected_fill_preserves_state": rejected.accepted is False and rejected_state == state,
        "partial_fill_has_remaining": capacity.orders[0]["filled_quantity"] == 200 and capacity.orders[0]["remaining_quantity"] == 100,
        "dividend_reconciles_cash": dividend["cash_credit"] == 50.0 and dividend_state.cash == 1_050.0,
    }
    return {"fixture_kind": "stage28_offline_truth_fixture", "checks": checks, "jump_return": jump_return}
