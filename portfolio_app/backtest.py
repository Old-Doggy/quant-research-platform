from __future__ import annotations

import numpy as np
import pandas as pd

from portfolio_app.contracts import TradeEvent


def extract_trade_events(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Convert executed position changes into linked order and fill events."""
    if frame is None or frame.empty or "position" not in frame:
        return []

    events: list[dict[str, object]] = []
    previous_position = 0
    previous_row: pd.Series | None = None
    order_number = 0
    for _, row in frame.iterrows():
        position = int(row.get("position", 0) or 0)
        if position == previous_position:
            previous_row = row
            continue
        side = "BUY" if position > previous_position else "SELL"
        decision_row = previous_row if previous_row is not None else row
        decision_date = pd.Timestamp(decision_row.get("decision_date", decision_row["trade_date"])).strftime("%Y-%m-%d")
        effective_date = pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d")
        reason_code = str(decision_row.get("reason_code", "position_change"))
        reason_text = str(decision_row.get("reason_text_public", "持仓状态发生变化"))
        evidence = decision_row.get("reason_evidence", {})
        if not isinstance(evidence, dict):
            evidence = {"raw": str(evidence)}
        order_number += 1
        order_id = f"order-{order_number:04d}"
        common = {
            "event_id": f"event-{order_number:04d}",
            "strategy_id": str(row.get("strategy_id", "unknown")),
            "symbol": str(row.get("symbol") or "DEMO"),
            "side": side,
            "decision_date": decision_date,
            "effective_date": effective_date,
            "reason_code": reason_code,
            "reason_text_public": reason_text,
            "evidence": evidence,
            "order_id": order_id,
            "quantity": 1,
            "price": float(row.get("execution_price", row.get("close", 0.0))),
        }
        signal_event = TradeEvent(
            event_id=f"event-{order_number:04d}-signal",
            event_type="SIGNAL",
            status="RECORDED",
            **{key: value for key, value in common.items() if key not in {"event_id", "quantity", "price"}},
        )
        order_event = TradeEvent(
            event_id=f"event-{order_number:04d}-order",
            event_type="ORDER_INTENT",
            status="PLANNED",
            **{key: value for key, value in common.items() if key != "event_id"},
        )
        fill_event = TradeEvent(
            event_id=f"event-{order_number:04d}-fill",
            event_type="FILL",
            fill_id=f"fill-{order_number:04d}",
            fill_date=effective_date,
            status="FILLED",
            **{key: value for key, value in common.items() if key != "event_id"},
        )
        events.extend((signal_event.to_dict(), order_event.to_dict(), fill_event.to_dict()))
        previous_position = position
        previous_row = row
    return events


EXECUTION_POLICIES = {
    "legacy_close_proxy": "滞后一行收盘收益代理（离线研究假设）",
    "next_day_close": "下一交易日收盘（离线研究假设）",
    "next_day_open": "下一交易日开盘（离线研究假设）",
}


def run_backtest(
    frame: pd.DataFrame,
    transaction_cost: float = 0.001,
    *,
    slippage_bps: float = 0.0,
    execution_policy: str = "legacy_close_proxy",
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Run a transparent single-symbol historical research simulation.

    ``execution_policy`` changes the return proxy used by the offline study;
    neither policy represents a live order or a broker fill.
    """
    if transaction_cost < 0:
        raise ValueError("transaction_cost cannot be negative")
    if slippage_bps < 0:
        raise ValueError("slippage_bps cannot be negative")
    if not np.isfinite(transaction_cost) or not np.isfinite(slippage_bps):
        raise ValueError("execution costs must be finite")
    if execution_policy not in EXECUTION_POLICIES:
        raise ValueError(f"unknown execution policy: {execution_policy}")
    result = frame.copy()
    from .return_series import require_action_free_proxy
    require_action_free_proxy(frame)
    if "return" not in result:
        raise ValueError("backtest frame requires return")
    result["position"] = result["signal"].shift(1).fillna(0)
    previous_position = result["position"].shift(1).fillna(0)
    if execution_policy == "next_day_open":
        if "open" not in result:
            raise ValueError("next_day_open requires open")
        open_prices = pd.to_numeric(result["open"], errors="coerce")
        close_prices = pd.to_numeric(result["close"], errors="coerce")
        execution_returns = pd.Series(0.0, index=result.index)
        entering = result["position"].gt(0) & previous_position.le(0)
        holding = result["position"].gt(0) & previous_position.gt(0)
        exiting = result["position"].le(0) & previous_position.gt(0)
        execution_returns.loc[entering] = close_prices.loc[entering] / open_prices.loc[entering] - 1.0
        execution_returns.loc[holding] = close_prices.loc[holding] / close_prices.shift(1).loc[holding] - 1.0
        execution_returns.loc[exiting] = open_prices.loc[exiting] / close_prices.shift(1).loc[exiting] - 1.0
        gross_return = execution_returns
        result["execution_price"] = open_prices
    elif execution_policy in {"next_day_close", "legacy_close_proxy"}:
        close_prices = pd.to_numeric(result["close"], errors="coerce")
        if execution_policy == "next_day_close":
            entering = result["position"].gt(0) & previous_position.le(0)
            holding = result["position"].gt(0) & previous_position.gt(0)
            exiting = result["position"].le(0) & previous_position.gt(0)
            execution_returns = pd.Series(0.0, index=result.index)
            close_to_close = close_prices / close_prices.shift(1) - 1.0
            execution_returns.loc[holding | exiting] = close_to_close.loc[holding | exiting]
            gross_return = execution_returns
        else:
            execution_returns = result["return"].fillna(0)
            gross_return = result["position"] * execution_returns
        result["execution_price"] = result["close"]
    else:
        execution_returns = result["return"].fillna(0)
        gross_return = result["position"] * execution_returns
        result["execution_price"] = result["close"]
    result["execution_return"] = execution_returns
    result["gross_strategy_return"] = gross_return
    turnover = result["position"].diff().abs().fillna(result["position"].abs())
    result["turnover"] = turnover
    result["transaction_cost_amount"] = turnover * transaction_cost
    result["slippage_amount"] = turnover * (float(slippage_bps) / 10000.0)
    result["total_cost_amount"] = result["transaction_cost_amount"] + result["slippage_amount"]
    result["strategy_return"] = result["gross_strategy_return"] - result["total_cost_amount"]
    result["equity"] = (1 + result["strategy_return"]).cumprod()
    result["benchmark_equity"] = (1 + result["return"].fillna(0)).cumprod()
    result["drawdown"] = result["equity"] / result["equity"].cummax().clip(lower=1.0) - 1
    trade_events = extract_trade_events(result)
    metrics = calculate_metrics(result)
    metrics["turnover"] = float(turnover.sum())
    metrics["transaction_cost_total"] = float(result["transaction_cost_amount"].sum())
    metrics["slippage_total"] = float(result["slippage_amount"].sum())
    metrics["total_cost"] = float(result["total_cost_amount"].sum())
    metrics["execution_policy"] = execution_policy
    metrics["execution_policy_label"] = EXECUTION_POLICIES[execution_policy]
    metrics["status"] = "no_trades" if metrics["trades"] == 0 else "ok"
    metrics["event_count"] = len(trade_events)
    result.attrs["trade_events"] = trade_events
    return result, metrics


def calculate_metrics(frame: pd.DataFrame) -> dict[str, float]:
    returns = frame["strategy_return"].fillna(0)
    equity = frame["equity"].fillna(1)
    days = max(len(frame), 1)
    annual_return = float(equity.iloc[-1] ** (252 / days) - 1)
    annual_vol = float(returns.std(ddof=0) * np.sqrt(252))
    sharpe = float(returns.mean()) * 252 / annual_vol if annual_vol > 0 else None
    drawdown = equity / equity.cummax().clip(lower=1.0) - 1
    trades = int(frame["position"].diff().abs().fillna(frame["position"].abs()).gt(0).sum())
    return {
        "total_return": float(equity.iloc[-1] - 1),
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "trades": trades,
        "observations": len(frame),
    }


def run_equal_weight_portfolio(
    frames: dict[str, pd.DataFrame],
    strategy_key: str,
    threshold: float = 1.0,
    transaction_cost: float = 0.001,
    params: dict[str, object] | None = None,
    *, calendar_policy: str = 'strict',
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Backtest an equal-weight portfolio from independently signalled symbols."""
    if not frames:
        raise ValueError("At least one symbol is required")
    if calendar_policy not in {'strict', 'intersection'}:
        raise ValueError('unknown calendar policy')
    alignment = {'policy': calendar_policy, 'excluded_rows': 0}
    if calendar_policy == 'intersection':
        common = set.intersection(*(set(pd.to_datetime(f.trade_date)) for f in frames.values()))
        if not common:
            raise ValueError('portfolio has no common sessions')
        alignment['excluded_rows'] = sum(len(f)-int(pd.to_datetime(f.trade_date).isin(common).sum()) for f in frames.values())
        frames = {symbol: f.loc[pd.to_datetime(f.trade_date).isin(common)].sort_values('trade_date').copy()
                  for symbol, f in frames.items()}
        for f in frames.values():
            f['return'] = f.close.pct_change(fill_method=None)

    daily_returns: list[pd.Series] = []
    positions: list[pd.Series] = []
    returns_by_symbol: dict[str, pd.Series] = {}
    positions_by_symbol: dict[str, pd.Series] = {}
    trade_events: list[dict[str, object]] = []
    for symbol, frame in frames.items():
        from portfolio_app.strategies import generate_signal

        signalled = generate_signal(frame, strategy_key, threshold=threshold, params=params)
        result, _ = run_backtest(signalled, transaction_cost=0.0)
        for event in result.attrs.get("trade_events", []):
            portfolio_event = dict(event)
            portfolio_event["portfolio_leg"] = symbol
            for identifier in ("event_id", "order_id", "fill_id"):
                if portfolio_event.get(identifier):
                    portfolio_event[identifier] = f"{symbol}-{portfolio_event[identifier]}"
            trade_events.append(portfolio_event)
        indexed_result = result.set_index("trade_date")
        symbol_returns = indexed_result["return"].rename(symbol)
        symbol_positions = indexed_result["position"].rename(symbol)
        daily_returns.append(symbol_returns)
        positions.append(symbol_positions)
        returns_by_symbol[symbol] = symbol_returns
        positions_by_symbol[symbol] = symbol_positions

    calendar = daily_returns[0].index
    if calendar.has_duplicates or any(series.index.has_duplicates or not series.index.equals(calendar) for series in daily_returns):
        raise ValueError("portfolio calendar mismatch; align sessions explicitly before research")
    returns = pd.concat(daily_returns, axis=1, sort=False).sort_index()
    position_frame = pd.concat(positions, axis=1, sort=False).sort_index()
    active_count = position_frame.ne(0).sum(axis=1)
    cost_by_symbol = position_frame.diff().abs().fillna(position_frame.abs())
    cost_by_symbol = cost_by_symbol / len(frames) * transaction_cost
    contribution_frame = pd.DataFrame(index=returns.index)
    for symbol in frames:
        contribution_frame[symbol] = (
            returns_by_symbol[symbol].reindex(returns.index).fillna(0)
            * position_frame[symbol].astype(float)
            / len(frames)
            - cost_by_symbol[symbol]
        ).fillna(0)
    portfolio = pd.DataFrame({"daily_return": contribution_frame.sum(axis=1)})
    portfolio["equity"] = (1 + portfolio["daily_return"]).cumprod()
    portfolio["benchmark_equity"] = (1 + returns.mean(axis=1).fillna(0)).cumprod()
    portfolio["active_symbols"] = active_count
    portfolio["gross_exposure"] = position_frame.abs().sum(axis=1) / len(frames)
    portfolio["net_exposure"] = position_frame.sum(axis=1) / len(frames)
    portfolio["cash_weight"] = 1.0 - portfolio["gross_exposure"]
    portfolio["drawdown"] = portfolio["equity"] / portfolio["equity"].cummax().clip(lower=1.0) - 1
    metrics = calculate_portfolio_metrics(portfolio)
    metrics["symbols"] = len(frames)
    metrics["event_count"] = len(trade_events)
    portfolio.attrs["trade_events"] = sorted(trade_events, key=lambda item: (item["effective_date"], item["event_id"]))
    portfolio.attrs["leg_contributions"] = contribution_frame.reset_index(names="trade_date")
    portfolio.attrs["leg_positions"] = position_frame.reset_index(names="trade_date")
    portfolio.attrs['calendar_alignment'] = alignment
    return portfolio.reset_index(names="trade_date"), metrics


def calculate_portfolio_metrics(frame: pd.DataFrame) -> dict[str, float]:
    returns = frame["daily_return"].fillna(0)
    equity = frame["equity"].fillna(1)
    days = max(len(frame), 1)
    annual_return = float(equity.iloc[-1] ** (252 / days) - 1)
    annual_volatility = float(returns.std(ddof=0) * np.sqrt(252))
    drawdown = equity / equity.cummax().clip(lower=1.0) - 1
    return {
        "total_return": float(equity.iloc[-1] - 1),
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": float(returns.mean()) * 252 / annual_volatility if annual_volatility > 0 else None,
        "max_drawdown": float(drawdown.min()),
        "observations": len(frame),
        "symbols": int(frame["active_symbols"].max()),
    }


def compare_symbol_backtests(
    frames: dict[str, pd.DataFrame],
    strategy_key: str,
    threshold: float = 1.0,
    transaction_cost: float = 0.001,
    params: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Return comparable metrics for each symbol in a portfolio selection."""
    from portfolio_app.strategies import generate_signal

    rows: list[dict[str, object]] = []
    for symbol, frame in frames.items():
        signalled = generate_signal(frame, strategy_key, threshold=threshold, params=params)
        _, metrics = run_backtest(signalled, transaction_cost=transaction_cost)
        rows.append({"symbol": symbol, **metrics})
    return pd.DataFrame(rows).sort_values("annual_return", ascending=False).reset_index(drop=True)
