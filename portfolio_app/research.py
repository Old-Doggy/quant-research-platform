from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math

import pandas as pd

from .research_manifest import build_run_manifest
from .research_integrity import audit_research_input

from portfolio_app.backtest import run_backtest
from portfolio_app.data import build_data_quality_report
from portfolio_app.portfolio import PortfolioResearchResult
from portfolio_app.strategies import build_strategy_config, generate_signal, normalize_strategy_params


@dataclass(frozen=True)
class SingleStockResearchResult:
    frame: pd.DataFrame
    metrics: dict[str, float]
    diagnostics: dict[str, Any]
    trade_events: list[dict[str, object]]
    strategy_config: dict[str, object]


def build_research_diagnostics_frame(result: SingleStockResearchResult) -> pd.DataFrame:
    """Return a compact, presentation-safe diagnostics table."""
    diagnostics = result.diagnostics
    return pd.DataFrame(
        [
            {"诊断项": "信号覆盖率", "值": f"{float(diagnostics['signal_coverage']):.2%}"},
            {"诊断项": "换手次数", "值": f"{float(diagnostics['turnover']):.0f}"},
            {"诊断项": "交易次数", "值": f"{int(diagnostics['trades'])}"},
            {"诊断项": "预热期（根）", "值": f"{int(diagnostics['warmup_bars'])}"},
            {"诊断项": "执行延迟（交易日）", "值": f"{int(diagnostics['execution_lag_days'])}"},
            {"诊断项": "数据质量警告", "值": "；".join(diagnostics["data_quality_warnings"]) or "无"},
        ]
    )


def _normalize_portfolio_weights(
    frames: dict[str, pd.DataFrame],
    target_weights: dict[str, float],
    cash_weight: float,
    missing_leg_policy: str,
) -> tuple[dict[str, float], float]:
    if missing_leg_policy not in {"fail", "preserve_cash", "renormalize"}:
        raise ValueError("unknown missing_leg_policy")
    if not math.isfinite(cash_weight) or any(not math.isfinite(float(weight)) for weight in target_weights.values()):
        raise ValueError("portfolio weights must be finite")
    if cash_weight < 0 or cash_weight > 1:
        raise ValueError("cash_weight must be between 0 and 1")
    if any(float(weight) < 0 for weight in target_weights.values()):
        raise ValueError("weights must be non-negative")
    missing = sorted(set(target_weights) - set(frames))
    if missing and missing_leg_policy == "fail":
        raise ValueError(f"missing portfolio legs: {', '.join(missing)}")
    weights = {symbol: float(weight) for symbol, weight in target_weights.items() if symbol in frames}
    if missing_leg_policy == "renormalize" and missing:
        available_total = sum(weights.values())
        declared_total = sum(float(weight) for weight in target_weights.values())
        if available_total > 0:
            scale = declared_total / available_total
            weights = {symbol: round(weight * scale, 12) for symbol, weight in weights.items()}
    elif missing_leg_policy == "preserve_cash" and missing:
        cash_weight += sum(float(target_weights[symbol]) for symbol in missing)
    total = sum(weights.values()) + cash_weight
    if abs(total - 1.0) > 1e-9:
        raise ValueError("weights and cash_weight must sum to 1")
    if not weights:
        raise ValueError("at least one available weighted leg is required")
    return weights, float(cash_weight)


def run_portfolio_research(
    frames: dict[str, pd.DataFrame],
    *,
    strategy_key: str,
    target_weights: dict[str, float],
    cash_weight: float = 0.0,
    transaction_cost: float = 0.001,
    missing_leg_policy: str = "fail",
    params: dict[str, object] | None = None,
    token=None,
) -> PortfolioResearchResult:
    """Run a weighted public portfolio research slice with explicit cash."""
    if not frames:
        raise ValueError("at least one portfolio leg is required")
    from .research_display import check_research_size
    check_research_size(pd.concat(list(frames.values()), ignore_index=True))
    if not math.isfinite(transaction_cost) or transaction_cost < 0:
        raise ValueError("transaction_cost must be non-negative")
    weights, cash_weight = _normalize_portfolio_weights(frames, target_weights, cash_weight, missing_leg_policy)
    integrity = {symbol: audit_research_input(frame) for symbol, frame in frames.items()}
    signalled_results: dict[str, pd.DataFrame] = {}
    events: list[dict[str, object]] = []
    for symbol, leg_frame in frames.items():
        if token:
            token.report(.1 + .6 * len(signalled_results) / len(frames), 'simulation')
        if symbol not in weights:
            continue
        if build_data_quality_report(leg_frame)["status"] != "通过":
            raise ValueError("portfolio data quality requires review")
        dates = pd.DatetimeIndex(pd.to_datetime(leg_frame["trade_date"])).sort_values()
        if signalled_results and not dates.equals(next(iter(signalled_results.values())).index):
            raise ValueError("portfolio calendar mismatch; align sessions explicitly before research")
        leg_frame = leg_frame.sort_values("trade_date").reset_index(drop=True)
        leg_frame['return'] = leg_frame.close.pct_change()
        signalled = generate_signal(leg_frame, strategy_key, params=params)
        result, _ = run_backtest(signalled, transaction_cost=0.0)
        signalled_results[symbol] = result.set_index("trade_date")
        for event in result.attrs.get("trade_events", []):
            enriched = dict(event)
            enriched["portfolio_leg"] = symbol
            for identifier in ("event_id", "order_id", "fill_id"):
                if enriched.get(identifier):
                    enriched[identifier] = f"{symbol}-{enriched[identifier]}"
            events.append(enriched)
    returns = pd.concat({symbol: result["return"] for symbol, result in signalled_results.items()}, axis=1, sort=False).sort_index().fillna(0.0)
    positions = pd.concat({symbol: result["position"] for symbol, result in signalled_results.items()}, axis=1, sort=False).sort_index()
    contribution = pd.DataFrame(index=returns.index)
    for symbol, weight in weights.items():
        target = positions[symbol].astype(float) * weight
        turnover = target.diff().abs().fillna(target.abs())
        contribution[symbol] = target * returns[symbol] - turnover * transaction_cost
    daily_return = contribution.sum(axis=1)
    portfolio = pd.DataFrame({"trade_date": daily_return.index, "daily_return": daily_return.to_numpy()})
    portfolio["equity"] = (1 + portfolio["daily_return"]).cumprod()
    portfolio["drawdown"] = portfolio["equity"] / portfolio["equity"].cummax().clip(lower=1.0) - 1
    portfolio["gross_exposure"] = positions.mul(pd.Series(weights)).abs().sum(axis=1).to_numpy()
    portfolio["cash_weight"] = 1.0 - portfolio["gross_exposure"]
    portfolio["active_symbols"] = positions.ne(0).sum(axis=1).to_numpy()
    portfolio["benchmark_equity"] = (1 + returns.mul(pd.Series(weights)).sum(axis=1)).cumprod().to_numpy()
    metrics = {
        "total_return": float(portfolio["equity"].iloc[-1] - 1),
        "observations": int(len(portfolio)),
        "max_drawdown": float(portfolio["drawdown"].min()),
        "trades": int(sum(positions[symbol].diff().abs().fillna(positions[symbol].abs()).gt(0).sum() for symbol in weights)),
    }
    annual_return = float(portfolio["equity"].iloc[-1] ** (252 / max(len(portfolio), 1)) - 1)
    annual_volatility = float(portfolio["daily_return"].std(ddof=0) * (252 ** 0.5))
    metrics["annual_return"] = annual_return
    metrics["annual_volatility"] = annual_volatility
    metrics["sharpe"] = float(portfolio["daily_return"].mean()) * 252 / annual_volatility if annual_volatility > 0 else None
    metrics["symbols"] = len(weights)
    metrics["event_count"] = len(events)
    portfolio.attrs["trade_events"] = sorted(events, key=lambda item: (item["effective_date"], item["event_id"]))
    attribution = contribution.reset_index(names="trade_date")
    return PortfolioResearchResult(
        frame=portfolio,
        attribution=attribution,
        trade_events=portfolio.attrs["trade_events"],
        weights=weights,
        cash_weight=cash_weight,
        diagnostics={"metrics": metrics, "missing_leg_policy": missing_leg_policy,
            'integrity': integrity,
            'run_manifest': build_run_manifest(
                frame=pd.concat([f.assign(symbol=s) for s, f in frames.items()], ignore_index=True),
                engine_id='weighted-leg-close-proxy.v1', features={'strategy': strategy_key},
                labels={'kind': 'none'}, execution={'policy': 'lagged_signal_close_to_close_proxy'},
                parameters={'weights': weights, 'cash_weight': cash_weight,
                            'strategy': normalize_strategy_params(strategy_key, params)},
                cost={'turnover': transaction_cost}, evaluation='fixed_parameter_proxy',
                processing={'missing_leg_policy': missing_leg_policy, 'version': 1})},
    )


def _warmup_bars(strategy_key: str, params: dict[str, object]) -> int:
    if strategy_key == "trend":
        return int(params["slow_window"])
    if strategy_key == "mean_reversion":
        return int(params["lookback_window"])
    if strategy_key == "quality_momentum":
        return int(params["momentum_window"])
    return 0


def _date_bound(value: object | None, label: str) -> pd.Timestamp | None:
    if value is None:
        return None
    result = pd.Timestamp(value)
    if pd.isna(result):
        raise ValueError(f"{label} is invalid")
    return result.normalize()


def run_single_stock_research(
    frame: pd.DataFrame,
    *,
    strategy_key: str,
    params: dict[str, object] | None = None,
    start_date: object | None = None,
    end_date: object | None = None,
    transaction_cost: float = 0.001,
    token=None,
) -> SingleStockResearchResult:
    """Run a reproducible, public single-stock research slice.

    Signals are computed on the complete supplied history before the requested
    date window is selected. This preserves warm-up behavior and prevents the
    visible window from changing the feature history.
    """
    if frame is None or frame.empty:
        raise ValueError("research frame is empty")
    from .research_display import check_research_size
    check_research_size(frame)
    if not math.isfinite(transaction_cost) or transaction_cost < 0:
        raise ValueError("transaction_cost must be non-negative")
    start = _date_bound(start_date, "start_date")
    end = _date_bound(end_date, "end_date")
    if start is not None and end is not None and start > end:
        raise ValueError("start_date cannot be after end_date")

    if token:
        token.report(.1, 'preflight')
    integrity = audit_research_input(frame)
    normalized_params = normalize_strategy_params(strategy_key, params)
    source = frame.copy()
    source["trade_date"] = pd.to_datetime(source["trade_date"], errors="coerce")
    if source["trade_date"].isna().any():
        raise ValueError("research frame contains invalid trade_date values")
    source = source.sort_values("trade_date", kind="stable").reset_index(drop=True)
    if build_data_quality_report(source)["status"] != "通过":
        raise ValueError("research data quality requires review before simulation")
    if 'symbol' in source and source.symbol.nunique() != 1:
        raise ValueError('single stock research requires exactly one symbol')
    source['return'] = source.close.pct_change()
    signalled = generate_signal(source, strategy_key, params=normalized_params)
    if token:
        token.report(.5, 'simulation')
    selected = signalled
    if start is not None:
        selected = selected.loc[selected["trade_date"] >= start]
    if end is not None:
        selected = selected.loc[selected["trade_date"] <= end]
    selected = selected.copy().reset_index(drop=True)
    if selected.empty:
        raise ValueError("research date window contains no rows")
    # Buy-and-hold starts at the first visible close, not the previous window's close.
    selected['return'] = selected.close.pct_change(fill_method=None)

    result_frame, metrics = run_backtest(
        selected,
        transaction_cost=transaction_cost,
        execution_policy="next_day_close",
    )
    events = list(result_frame.attrs.get("trade_events", []))
    if token:
        token.report(.85, 'archive')
    quality = build_data_quality_report(selected)
    signal_coverage = float(selected["signal"].ne(0).mean()) if len(selected) else 0.0
    turnover = float(result_frame["position"].diff().abs().fillna(result_frame["position"].abs()).sum())
    warnings: list[str] = []
    if quality.get("status") != "通过":
        warnings.append("数据质量检查需要复核")
    if len(selected) <= _warmup_bars(strategy_key, normalized_params):
        warnings.append("样本长度不超过策略预热期")
    diagnostics: dict[str, Any] = {
        "signal_coverage": signal_coverage,
        "turnover": turnover,
        "trades": int(metrics.get("trades", 0)),
        "warmup_bars": _warmup_bars(strategy_key, normalized_params),
        "execution_lag_days": int(build_strategy_config(strategy_key)["execution_lag_days"]),
        "execution_policy": str(metrics["execution_policy"]),
        "execution_policy_label": str(metrics["execution_policy_label"]),
        "data_quality_warnings": warnings,
        "data_quality": quality,
        "date_start": result_frame["trade_date"].min().strftime("%Y-%m-%d"),
        "date_end": result_frame["trade_date"].max().strftime("%Y-%m-%d"),
    }
    diagnostics['integrity'] = integrity
    diagnostics['run_manifest'] = build_run_manifest(
        frame=source, engine_id='single-stock-close-proxy.v1',
        features={'strategy': strategy_key, 'parameters': normalized_params},
        labels={'kind': 'none'}, execution={'policy': str(metrics['execution_policy'])},
        parameters=normalized_params, cost={'turnover': float(transaction_cost)},
        evaluation='fixed_parameter', processing={'version': 'single-stock.v1',
            'evaluation_period': {'start': diagnostics['date_start'], 'end': diagnostics['date_end']}})
    result_frame.attrs["trade_events"] = events
    return SingleStockResearchResult(
        frame=result_frame,
        metrics=metrics,
        diagnostics=diagnostics,
        trade_events=events,
        strategy_config={
            **build_strategy_config(strategy_key),
            "parameters": normalized_params,
            "execution_policy": str(metrics["execution_policy"]),
            "execution_policy_label": str(metrics["execution_policy_label"]),
        },
    )
