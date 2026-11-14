from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from portfolio_app.backtest import EXECUTION_POLICIES, run_backtest
from portfolio_app.strategies import generate_signal, normalize_strategy_params


SENSITIVITY_COLUMNS = [
    "scenario_id", "scenario_count", "baseline_scenario_id", "is_baseline",
    "changed_assumption", "assumption_change", "research_only", "status",
    "transaction_cost", "slippage_bps", "execution_policy", "execution_policy_label",
    "observations", "trades", "turnover", "total_return", "annual_return", "sharpe",
    "max_drawdown", "transaction_cost_component", "slippage_component", "total_cost",
    "delta_total_return", "delta_annual_return", "delta_sharpe", "delta_max_drawdown",
    "delta_total_cost",
]


def _values(values: Iterable[float], label: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result:
        raise ValueError(f"{label} must contain at least one scenario")
    if any(not np.isfinite(value) for value in result):
        raise ValueError(f"{label} must contain finite values")
    return result


def _scenario_definitions(
    transaction_cost: float,
    transaction_costs: Iterable[float],
    slippage_bps: Iterable[float],
    execution_policies: Iterable[str],
) -> list[dict[str, object]]:
    costs = _values(transaction_costs, "transaction_costs")
    slips = _values(slippage_bps, "slippage_bps")
    if not np.isfinite(float(transaction_cost)) or transaction_cost < 0:
        raise ValueError("transaction_cost cannot be negative")
    if any(value < 0 for value in costs):
        raise ValueError("transaction_costs cannot be negative")
    if any(value < 0 for value in slips):
        raise ValueError("slippage_bps cannot be negative")
    policies = tuple(str(value) for value in execution_policies)
    if not policies:
        raise ValueError("execution_policies must contain at least one scenario")
    unknown = sorted(set(policies) - set(EXECUTION_POLICIES))
    if unknown:
        raise ValueError(f"unknown execution policy: {unknown[0]}")

    scenarios: list[dict[str, object]] = [{
        "scenario_id": "baseline",
        "changed_assumption": "baseline",
        "assumption_change": "基准场景：不改变研究假设",
        "transaction_cost": float(transaction_cost),
        "slippage_bps": 0.0,
        "execution_policy": "next_day_close",
        "is_baseline": True,
    }]
    for value in dict.fromkeys(costs):
        if value != transaction_cost:
            scenarios.append({
                "scenario_id": f"transaction-cost-{value:g}",
                "changed_assumption": "transaction_cost",
                "assumption_change": f"单次换手成本 {transaction_cost:.6f} → {value:.6f}",
                "transaction_cost": value,
                "slippage_bps": 0.0,
                "execution_policy": "next_day_close",
                "is_baseline": False,
            })
    for value in dict.fromkeys(slips):
        if value != 0:
            scenarios.append({
                "scenario_id": f"slippage-bps-{value:g}",
                "changed_assumption": "slippage_bps",
                "assumption_change": f"额外滑点 {0:.0f}bp → {value:.0f}bp",
                "transaction_cost": float(transaction_cost),
                "slippage_bps": value,
                "execution_policy": "next_day_close",
                "is_baseline": False,
            })
    for policy in dict.fromkeys(policies):
        if policy != "next_day_close":
            scenarios.append({
                "scenario_id": f"execution-policy-{policy}",
                "changed_assumption": "execution_policy",
                "assumption_change": f"执行政策 next_day_close → {policy}",
                "transaction_cost": float(transaction_cost),
                "slippage_bps": 0.0,
                "execution_policy": policy,
                "is_baseline": False,
            })
    return scenarios


def _invalid_frame(frame: pd.DataFrame | None) -> bool:
    if frame is None or frame.empty:
        return True
    required = {"trade_date", "open", "high", "low", "close", "return"}
    if not required.issubset(frame.columns):
        return True
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    prices = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    return dates.isna().any() or not np.isfinite(prices.to_numpy(dtype=float)).all()


def build_single_stock_sensitivity_report(
    frame: pd.DataFrame,
    strategy_key: str,
    *,
    params: dict[str, object] | None = None,
    transaction_cost: float = 0.001,
    transaction_costs: Iterable[float] = (0.0, 0.001, 0.002),
    slippage_bps: Iterable[float] = (0.0, 5.0, 10.0),
    execution_policies: Iterable[str] = ("next_day_close",),
    start_date: object | None = None,
    end_date: object | None = None,
) -> pd.DataFrame:
    """Compare one-factor-at-a-time offline execution assumptions.

    The function never ranks scenarios or labels one as optimal. It records
    the baseline and relative changes so a reviewer can see what changed.
    """
    scenarios = _scenario_definitions(transaction_cost, transaction_costs, slippage_bps, execution_policies)
    count = len(scenarios)
    baseline_id = "baseline"
    prepared: pd.DataFrame | None = None
    invalid_status = _invalid_frame(frame)
    if not invalid_status:
        normalized = normalize_strategy_params(strategy_key, params)
        prepared = generate_signal(frame.copy(), strategy_key, params=normalized)
        start = pd.Timestamp(start_date).normalize() if start_date is not None else prepared["trade_date"].min()
        end = pd.Timestamp(end_date).normalize() if end_date is not None else prepared["trade_date"].max()
        if pd.isna(start) or pd.isna(end) or start > end:
            raise ValueError("sensitivity date window is invalid")
        prepared = prepared.loc[prepared["trade_date"].between(start, end)].copy().reset_index(drop=True)
        if prepared.empty:
            invalid_status = True

    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        row = {
            **scenario,
            "scenario_count": count,
            "baseline_scenario_id": baseline_id,
            "research_only": True,
            "execution_policy_label": EXECUTION_POLICIES[scenario["execution_policy"]],
        }
        if invalid_status:
            row["status"] = "invalid_data"
            row.update({column: np.nan for column in SENSITIVITY_COLUMNS if column not in row})
            rows.append(row)
            continue
        _, metrics = run_backtest(
            prepared,
            transaction_cost=float(scenario["transaction_cost"]),
            slippage_bps=float(scenario["slippage_bps"]),
            execution_policy=str(scenario["execution_policy"]),
        )
        row.update({
            "status": str(metrics["status"]),
            "observations": int(metrics["observations"]),
            "trades": int(metrics["trades"]),
            "turnover": float(metrics["turnover"]),
            "total_return": float(metrics["total_return"]),
            "annual_return": float(metrics["annual_return"]),
            "sharpe": float(metrics["sharpe"]) if metrics['sharpe'] is not None else np.nan,
            "max_drawdown": float(metrics["max_drawdown"]),
            "transaction_cost_component": float(metrics["transaction_cost_total"]),
            "slippage_component": float(metrics["slippage_total"]),
            "total_cost": float(metrics["total_cost"]),
        })
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=SENSITIVITY_COLUMNS)
    baseline = result.loc[result["is_baseline"]].iloc[0]
    for metric in ("total_return", "annual_return", "sharpe", "max_drawdown", "total_cost"):
        result[f"delta_{metric}"] = pd.to_numeric(result[metric], errors="coerce") - float(baseline[metric])
    return result.reindex(columns=SENSITIVITY_COLUMNS)
