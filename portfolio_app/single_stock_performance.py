"""Presentation contract for comparable single-stock research performance."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd
import numpy as np


class PerformanceContractError(ValueError):
    """Raised when a single-stock result cannot be presented safely."""


_REQUIRED = {
    "trade_date", "strategy_return", "return", "position", "equity", "benchmark_equity", "drawdown"
}


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PerformanceContractError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise PerformanceContractError(f"{label} must be finite")
    return result


def build_single_stock_performance(frame: pd.DataFrame, *, transaction_cost: float) -> dict[str, Any]:
    """Build a display-safe curve without repairing or hiding invalid results."""
    cost = _finite(transaction_cost, "transaction_cost")
    if cost < 0:
        raise PerformanceContractError("transaction_cost cannot be negative")
    if frame is None or frame.empty:
        raise PerformanceContractError("result frame is empty")
    missing = sorted(_REQUIRED - set(frame.columns))
    if missing:
        raise PerformanceContractError(f"result frame is missing: {', '.join(missing)}")
    data = frame.copy().reset_index(drop=True)
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    if data["trade_date"].isna().any() or data["trade_date"].duplicated().any():
        raise PerformanceContractError("trade_date must be valid and unique")
    data = data.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    for column in ("strategy_return", "position", "equity", "benchmark_equity", "drawdown"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
        if not np.isfinite(data[column]).all():
            raise PerformanceContractError(f"{column} contains missing or invalid values")
    data["return"] = pd.to_numeric(data["return"], errors="coerce")
    missing_returns = data["return"].isna()
    if missing_returns.any() and (not bool(missing_returns.iloc[0]) or int(missing_returns.sum()) != 1):
        raise PerformanceContractError("return contains missing or invalid values")
    if bool(missing_returns.iloc[0]):
        # The first bar has no prior close. This is the explicit same convention
        # used by the existing backtest, while later gaps remain a hard failure.
        data.loc[0, "return"] = 0.0
    if not np.isfinite(data['return']).all():
        raise PerformanceContractError('return must be finite')
    if (data['strategy_return'] <= -1).any() or (data['return'] <= -1).any():
        raise PerformanceContractError('returns must be greater than -100%')
    for nav, returns in [('equity', 'strategy_return'), ('benchmark_equity', 'return')]:
        if not np.allclose((1 + data[returns]).cumprod(), data[nav], rtol=1e-7, atol=1e-9):
            raise PerformanceContractError(f'{nav} is inconsistent with returns')
    if (data["equity"] <= 0).any() or (data["benchmark_equity"] <= 0).any():
        raise PerformanceContractError("equity and benchmark_equity must be positive")
    expected_drawdown = data["equity"] / data["equity"].cummax().clip(lower=1.0) - 1.0
    if not expected_drawdown.equals(data["drawdown"]):
        if not (expected_drawdown - data["drawdown"]).abs().le(1e-6).all():
            raise PerformanceContractError("drawdown is inconsistent with equity")
    turnover = data["position"].diff().abs().fillna(data["position"].abs())
    daily_cost = turnover * cost
    trade_count = int(turnover.gt(0).sum())
    nav_end = float(data["equity"].iloc[-1])
    benchmark_end = float(data["benchmark_equity"].iloc[-1])
    observations = len(data)
    daily_returns = data["strategy_return"]
    annual_return = nav_end ** (252 / observations) - 1.0
    volatility = float(daily_returns.std(ddof=0) * math.sqrt(252))
    mean_return = float(daily_returns.mean())
    downside = daily_returns.clip(upper=0.0)
    downside_deviation = float((downside.pow(2).mean() ** 0.5) * math.sqrt(252))
    curve = [
        {
            "date": date.strftime("%Y-%m-%d"),
            "nav": float(nav),
            "benchmark_nav": float(benchmark),
            "drawdown": float(drawdown),
            "daily_return": float(daily_return),
            "daily_cost": float(cost_value),
        }
        for date, nav, benchmark, drawdown, daily_return, cost_value in zip(
            data["trade_date"], data["equity"], data["benchmark_equity"], data["drawdown"], data["strategy_return"], daily_cost
        )
    ]
    return {
        "schema_version": "single-stock-performance.v1",
        "status": "available",
        "curve": curve,
        "metrics": {
            "total_return": nav_end - 1.0,
            "benchmark_total_return": benchmark_end - 1.0,
            "annual_return": annual_return,
            "annual_volatility": volatility,
            "sharpe": mean_return * 252 / volatility if volatility > 0 else None,
            "sortino": mean_return * 252 / downside_deviation if downside_deviation > 0 else None,
            "max_drawdown": float(data["drawdown"].min()),
            "trades": trade_count,
            "observations": observations,
            "total_cost": float(daily_cost.sum()),
        },
        "cost_assumption": {"transaction_cost": cost, "basis": "position_turnover_times_rate"},
        "diagnostics": {"empty_trade_state": trade_count == 0, "cost_rows": int(daily_cost.gt(0).sum())},
    }
