from __future__ import annotations

import numpy as np
import pandas as pd


def run_backtest(frame: pd.DataFrame, transaction_cost: float = 0.001) -> tuple[pd.DataFrame, dict[str, float]]:
    """Run a transparent next-day execution backtest for one symbol."""
    result = frame.copy()
    result["position"] = result["signal"].shift(1).fillna(0)
    result["strategy_return"] = result["position"] * result["return"].fillna(0)
    turnover = result["position"].diff().abs().fillna(result["position"].abs())
    result["strategy_return"] -= turnover * transaction_cost
    result["equity"] = (1 + result["strategy_return"]).cumprod()
    result["benchmark_equity"] = (1 + result["return"].fillna(0)).cumprod()
    metrics = calculate_metrics(result)
    return result, metrics


def calculate_metrics(frame: pd.DataFrame) -> dict[str, float]:
    returns = frame["strategy_return"].fillna(0)
    equity = frame["equity"].fillna(1)
    days = max(len(frame), 1)
    annual_return = float(equity.iloc[-1] ** (252 / days) - 1)
    annual_vol = float(returns.std(ddof=0) * np.sqrt(252))
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0.0
    drawdown = equity / equity.cummax() - 1
    trades = int(frame["position"].diff().abs().fillna(frame["position"].abs()).gt(0).sum())
    return {
        "total_return": float(equity.iloc[-1] - 1),
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown.min()),
        "trades": trades,
        "observations": len(frame),
    }


def run_equal_weight_portfolio(
    frames: dict[str, pd.DataFrame],
    strategy_key: str,
    threshold: float = 1.0,
    transaction_cost: float = 0.001,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Backtest an equal-weight portfolio from independently signalled symbols."""
    if not frames:
        raise ValueError("At least one symbol is required")

    daily_returns: list[pd.Series] = []
    positions: list[pd.Series] = []
    for symbol, frame in frames.items():
        from portfolio_app.strategies import generate_signal

        signalled = generate_signal(frame, strategy_key, threshold=threshold)
        result, _ = run_backtest(signalled, transaction_cost=0.0)
        daily_returns.append(result.set_index("trade_date")["return"].rename(symbol))
        positions.append(result.set_index("trade_date")["position"].rename(symbol))

    returns = pd.concat(daily_returns, axis=1).sort_index()
    position_frame = pd.concat(positions, axis=1).sort_index().fillna(0)
    active_count = position_frame.ne(0).sum(axis=1)
    gross_return = returns.where(position_frame.ne(0)).mean(axis=1).fillna(0)
    turnover = position_frame.diff().abs().fillna(position_frame.abs()).sum(axis=1)
    turnover = turnover.div(active_count.replace(0, 1))
    portfolio = pd.DataFrame({"daily_return": gross_return - turnover * transaction_cost})
    portfolio["equity"] = (1 + portfolio["daily_return"]).cumprod()
    portfolio["benchmark_equity"] = (1 + returns.mean(axis=1).fillna(0)).cumprod()
    portfolio["active_symbols"] = active_count
    metrics = calculate_portfolio_metrics(portfolio)
    metrics["symbols"] = len(frames)
    return portfolio.reset_index(names="trade_date"), metrics


def calculate_portfolio_metrics(frame: pd.DataFrame) -> dict[str, float]:
    returns = frame["daily_return"].fillna(0)
    equity = frame["equity"].fillna(1)
    days = max(len(frame), 1)
    annual_return = float(equity.iloc[-1] ** (252 / days) - 1)
    annual_volatility = float(returns.std(ddof=0) * np.sqrt(252))
    drawdown = equity / equity.cummax() - 1
    return {
        "total_return": float(equity.iloc[-1] - 1),
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": annual_return / annual_volatility if annual_volatility > 0 else 0.0,
        "max_drawdown": float(drawdown.min()),
        "observations": len(frame),
        "symbols": int(frame["active_symbols"].max()),
    }


def compare_symbol_backtests(
    frames: dict[str, pd.DataFrame],
    strategy_key: str,
    threshold: float = 1.0,
    transaction_cost: float = 0.001,
) -> pd.DataFrame:
    """Return comparable metrics for each symbol in a portfolio selection."""
    from portfolio_app.strategies import generate_signal

    rows: list[dict[str, object]] = []
    for symbol, frame in frames.items():
        signalled = generate_signal(frame, strategy_key, threshold=threshold)
        _, metrics = run_backtest(signalled, transaction_cost=transaction_cost)
        rows.append({"symbol": symbol, **metrics})
    return pd.DataFrame(rows).sort_values("annual_return", ascending=False).reset_index(drop=True)
