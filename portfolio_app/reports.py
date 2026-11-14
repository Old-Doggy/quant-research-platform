from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from portfolio_app.backtest import run_backtest
from portfolio_app.research import run_portfolio_research
from portfolio_app.strategies import STRATEGIES, generate_signal


REPORT_COLUMNS = [
    "strategy_key",
    "strategy_name",
    "window_bars",
    "transaction_cost",
    "observations",
    "total_return",
    "annual_return",
    "annual_volatility",
    "sharpe",
    "max_drawdown",
    "trades",
    "event_count",
]


def _strategy_name(strategy_key: str) -> str:
    for strategy in STRATEGIES:
        if strategy.key == strategy_key:
            return strategy.name
    return strategy_key


def _normalise_scenarios(values: Iterable[float], label: str) -> tuple[float, ...]:
    scenarios = tuple(values)
    if not scenarios:
        raise ValueError(f"{label} must contain at least one scenario")
    if label == "windows" and any(int(value) <= 0 for value in scenarios):
        raise ValueError("windows must be positive")
    if label == "transaction_costs" and any(float(value) < 0 for value in scenarios):
        raise ValueError("transaction_costs cannot be negative")
    return scenarios


def build_robustness_report(
    frame: pd.DataFrame,
    strategy_key: str,
    windows: Iterable[int] = (120, 252, 504),
    transaction_costs: Iterable[float] = (0.0, 0.001, 0.002),
    params: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Run the public demo strategy across fixed history and cost scenarios."""
    windows = tuple(int(value) for value in _normalise_scenarios(windows, "windows"))
    transaction_costs = tuple(float(value) for value in _normalise_scenarios(transaction_costs, "transaction_costs"))
    if frame is None or frame.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)

    rows: list[dict[str, object]] = []
    for window in windows:
        selected = frame.tail(window).copy()
        signalled = generate_signal(selected, strategy_key, params=params)
        for cost in transaction_costs:
            _, metrics = run_backtest(signalled, transaction_cost=cost)
            rows.append(
                {
                    "strategy_key": strategy_key,
                    "strategy_name": _strategy_name(strategy_key),
                    "window_bars": min(window, len(selected)),
                    "transaction_cost": cost,
                    **{column: metrics.get(column, 0.0) for column in REPORT_COLUMNS[4:]},
                }
            )
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def build_robustness_summary(report: pd.DataFrame) -> dict[str, object]:
    """Summarise dispersion and cost sensitivity without selecting a best run."""
    if report is None or report.empty:
        return {
            "scenario_count": 0,
            "annual_return_median": 0.0,
            "annual_return_min": 0.0,
            "annual_return_max": 0.0,
            "max_drawdown_worst": 0.0,
            "cost_sensitivity": 0.0,
            "stability_label": "无有效场景",
        }

    annual = pd.to_numeric(report["annual_return"], errors="coerce").dropna()
    drawdowns = pd.to_numeric(report["max_drawdown"], errors="coerce").dropna()
    cost_groups = report.groupby("transaction_cost")["annual_return"].median().sort_index()
    cost_sensitivity = float(cost_groups.iloc[0] - cost_groups.iloc[-1]) if len(cost_groups) >= 2 else 0.0
    annual_spread = float(annual.max() - annual.min()) if len(annual) else 0.0
    stability_label = "较稳定" if annual_spread <= 0.10 and abs(cost_sensitivity) <= 0.10 else "需复核"
    return {
        "scenario_count": int(len(report)),
        "annual_return_median": float(annual.median()) if len(annual) else 0.0,
        "annual_return_min": float(annual.min()) if len(annual) else 0.0,
        "annual_return_max": float(annual.max()) if len(annual) else 0.0,
        "max_drawdown_worst": float(drawdowns.min()) if len(drawdowns) else 0.0,
        "cost_sensitivity": cost_sensitivity,
        "stability_label": stability_label,
    }


def build_strategy_comparison(
    frame: pd.DataFrame,
    strategy_keys: Iterable[str] = ("trend", "mean_reversion", "quality_momentum"),
    windows: Iterable[int] = (252,),
    transaction_costs: Iterable[float] = (0.001,),
    params_by_strategy: dict[str, dict[str, object]] | None = None,
) -> pd.DataFrame:
    """Compare demo strategies under the same scenario grid."""
    rows: list[dict[str, object]] = []
    for strategy_key in strategy_keys:
        report = build_robustness_report(
            frame,
            strategy_key,
            windows=windows,
            transaction_costs=transaction_costs,
            params=(params_by_strategy or {}).get(strategy_key),
        )
        summary = build_robustness_summary(report)
        rows.append(
            {
                "strategy_key": strategy_key,
                "strategy_name": _strategy_name(strategy_key),
                "annual_return": summary["annual_return_median"],
                "sharpe": float(report["sharpe"].median()) if not report.empty else 0.0,
                "max_drawdown": summary["max_drawdown_worst"],
                "trades": int(report["trades"].median()) if not report.empty else 0,
                "stability_label": summary["stability_label"],
            }
        )
    return pd.DataFrame(rows)


def explain_report_limitations(
    source_kind: str = "synthetic_demo",
    execution_model: str = "next_day_close",
) -> list[str]:
    """Return disclosure-safe limitations for public research reports."""
    limitations = [
        "结果用于研究展示，不构成收益承诺或投资建议。",
        "稳健性场景使用固定历史窗口和交易成本网格，不等同于样本外验证。",
        "未模拟涨跌停、停牌、成交容量、冲击成本和完整市场微观结构。",
    ]
    if source_kind == "synthetic_demo":
        limitations.append("当前数据为合成演示数据，不能代表真实证券历史表现。")
    if execution_model == "next_day_close":
        limitations.append("信号在决策日形成，并按下一交易日收盘口径计算，不代表真实成交价格。")
    return limitations


def build_portfolio_robustness_report(
    frames: dict[str, pd.DataFrame],
    strategy_key: str,
    weight_scenarios: Iterable[dict[str, float]],
    windows: Iterable[int] = (120, 252),
    transaction_costs: Iterable[float] = (0.0, 0.001),
    cash_weight: float = 0.0,
    params_by_strategy: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Evaluate explicit portfolio compositions, windows and cost scenarios."""
    rows: list[dict[str, object]] = []
    for composition_id, weights in enumerate(weight_scenarios, start=1):
        for window in _normalise_scenarios(windows, "windows"):
            selected_frames = {symbol: frame.tail(int(window)).copy() for symbol, frame in frames.items()}
            for cost in _normalise_scenarios(transaction_costs, "transaction_costs"):
                result = run_portfolio_research(
                    selected_frames,
                    strategy_key=strategy_key,
                    target_weights=weights,
                    cash_weight=cash_weight,
                    transaction_cost=float(cost),
                    params=params_by_strategy,
                    missing_leg_policy="fail",
                )
                rows.append(
                    {
                        "composition_id": composition_id,
                        "window_bars": min(int(window), min(len(frame) for frame in selected_frames.values())),
                        "transaction_cost": float(cost),
                        "symbols": len(result.weights),
                        "cash_weight": result.cash_weight,
                        "total_return": result.diagnostics["metrics"]["total_return"],
                        "max_drawdown": result.diagnostics["metrics"]["max_drawdown"],
                        "trades": result.diagnostics["metrics"]["trades"],
                    }
                )
    return pd.DataFrame(rows)
