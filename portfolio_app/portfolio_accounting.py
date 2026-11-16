"""Unified portfolio ledger, attribution, and risk diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

import pandas as pd


class PortfolioAccountingError(ValueError):
    """Raised when a portfolio accounting input cannot be reconciled."""


@dataclass(frozen=True)
class PortfolioAccountingResult:
    ledger: pd.DataFrame
    symbol_contribution: pd.DataFrame
    leg_contribution: pd.DataFrame
    factor_contribution: pd.DataFrame
    risk: dict[str, Any]
    diagnostics: dict[str, Any]


def _date_table(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(str(value) for value in values)
    if not result or tuple(sorted(set(result))) != result:
        raise PortfolioAccountingError("dates must be a non-empty sorted unique table")
    return result


def _finite(value: Any, label: str, *, positive: bool = False, non_negative: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioAccountingError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise PortfolioAccountingError(f"{label} must be finite")
    if positive and number <= 0:
        raise PortfolioAccountingError(f"{label} must be positive")
    if non_negative and number < 0:
        raise PortfolioAccountingError(f"{label} must be non-negative")
    return number


def _price(prices: Mapping[str, Any], symbol: str, date: str) -> float:
    if symbol not in prices or not isinstance(prices[symbol], Mapping) or date not in prices[symbol]:
        raise PortfolioAccountingError(f"missing price for {symbol} on {date}")
    return _finite(prices[symbol][date], f"price for {symbol} on {date}", positive=True)


def _fill(fill: Mapping[str, Any], dates: tuple[str, ...], seen: set[str]) -> dict[str, Any]:
    if not isinstance(fill, Mapping):
        raise PortfolioAccountingError("fill must be a mapping")
    fill_id = str(fill.get("fill_id", "")).strip()
    if not fill_id or fill_id in seen:
        raise PortfolioAccountingError("duplicate or empty fill_id")
    seen.add(fill_id)
    date = str(fill.get("fill_date", ""))
    symbol = str(fill.get("symbol", "")).strip()
    side = str(fill.get("side", "")).upper()
    quantity = fill.get("quantity")
    if date not in dates or not symbol:
        raise PortfolioAccountingError("fill symbol or date is invalid")
    if side not in {"BUY", "SELL"}:
        raise PortfolioAccountingError("fill side is invalid")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise PortfolioAccountingError("fill quantity must be a positive integer")
    return {"fill_id": fill_id, "fill_date": date, "symbol": symbol, "side": side,
            "quantity": quantity, "price": _finite(fill.get("price"), "fill price", positive=True),
            "fee": _finite(fill.get("fee", 0), "fill fee", non_negative=True),
            "leg": str(fill.get("leg", "")).strip() or symbol}


def build_portfolio_accounting(
    *, dates: Iterable[str], prices: Mapping[str, Any], fills: Iterable[Mapping[str, Any]],
    initial_cash: float, benchmark_returns: Mapping[str, float] | None = None,
    cash_returns: Mapping[str, float] | None = None,
    factor_pnl: Mapping[str, Mapping[str, float]] | None = None,
    factor_source: str | None = None,
    industry_by_symbol: Mapping[str, str] | None = None,
    industry_pit_available: bool = False, annualization_sessions: int = 252,
    risk_window: int | None = None,
    corporate_actions=(),external_flows=(),
) -> PortfolioAccountingResult:
    """Build a single cash-accounted offline portfolio result."""
    dates = _date_table(dates)
    from .cashflow_returns import normalize_flows,account_returns
    external_flows=normalize_flows(external_flows,dates)
    flows_by_day={day:0. for day in dates}
    for flow in external_flows: flows_by_day[flow['session']]+=flow['amount']
    starting_cash = _finite(initial_cash, "initial_cash", non_negative=True)
    if not isinstance(annualization_sessions, int) or annualization_sessions <= 0:
        raise PortfolioAccountingError("annualization_sessions must be positive")
    if risk_window is not None and (not isinstance(risk_window, int) or risk_window <= 0):
        raise PortfolioAccountingError("risk_window must be positive")
    seen: set[str] = set()
    normalized = [_fill(item, dates, seen) for item in fills]
    by_date = {date: [] for date in dates}
    for item in normalized:
        by_date[item["fill_date"]].append(item)
    benchmark_returns = benchmark_returns or {}
    cash_returns = cash_returns or {}
    factor_pnl = factor_pnl or {}
    if factor_pnl and not factor_source:
        raise PortfolioAccountingError("factor_source is required when factor_pnl is supplied")
    for date, value in benchmark_returns.items():
        _finite(value, f"benchmark return on {date}")
    for date, value in cash_returns.items():
        _finite(value, f"cash return on {date}")

    cash = starting_cash
    from .entitlement_ledger import EntitlementBook
    entitlements = EntitlementBook(corporate_actions)
    positions: dict[str, int] = {}
    previous_cash = starting_cash
    previous_nav = starting_cash
    # Lots preserve leg ownership and cost basis for the contribution tables.
    lots: dict[str, list[dict[str, Any]]] = {}
    realized_by_symbol: dict[str, float] = {}
    realized_by_leg: dict[str, float] = {}
    previous_symbol_pnl: dict[str, float] = {}
    previous_leg_pnl: dict[str, float] = {}
    previous_income: dict[str,float] = {}
    ledger_rows: list[dict[str, Any]] = []
    symbol_rows: list[dict[str, Any]] = []
    leg_rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []

    for index, date in enumerate(dates):
        external_flow=flows_by_day[date]
        cash+=external_flow
        return_base=previous_nav+external_flow
        if cash < -1e-9 or return_base<=0:
            raise PortfolioAccountingError('出金超过可用现金或期初权益非正')
        cash_pnl = 0.0
        if index > 0:
            cash_rate = _finite(cash_returns.get(date, 0.0), f"cash return on {date}")
            cash_pnl = previous_cash * cash_rate
            cash += cash_pnl
        cash += entitlements.open_session(date, positions, lots)
        fees = 0.0
        turnover = 0.0
        for item in by_date[date]:
            symbol, leg, qty, price = item["symbol"], item["leg"], item["quantity"], item["price"]
            _price(prices, symbol, date)
            notional = qty * price
            fees += item["fee"]
            turnover += notional
            lots.setdefault(leg, [])
            if item["side"] == "BUY":
                if notional + item["fee"] > cash + 1e-9:
                    raise PortfolioAccountingError(f"insufficient cash for fill {item['fill_id']}")
                cash -= notional + item["fee"]
                positions[symbol] = positions.get(symbol, 0) + qty
                lots[leg].append({"symbol": symbol, "quantity": qty, "price": price})
            else:
                if qty > positions.get(symbol, 0):
                    raise PortfolioAccountingError(f"insufficient position for fill {item['fill_id']}")
                if qty > positions.get(symbol, 0) - entitlements.locked_quantities(date).get(symbol, 0):
                    raise PortfolioAccountingError('新增股份尚未上市，可卖数量不足')
                remaining = qty
                leg_lots = lots.get(leg, [])
                symbol_lots = [lot for lot in leg_lots if lot["symbol"] == symbol and int(lot["quantity"]) > 0]
                if sum(int(lot["quantity"]) for lot in symbol_lots) < qty:
                    raise PortfolioAccountingError(f"insufficient leg position for fill {item['fill_id']}")
                realized = 0.0
                for lot in symbol_lots:
                    if remaining == 0:
                        break
                    used = min(remaining, int(lot["quantity"]))
                    realized += used * (price - float(lot["price"]))
                    lot["quantity"] -= used
                    remaining -= used
                lots[leg] = [lot for lot in leg_lots if lot["quantity"] > 0]
                cash += notional - item["fee"]
                positions[symbol] -= qty
                # Fees remain a separate ledger contribution; keep this P&L
                # gross so it is not deducted twice during reconciliation.
                realized_by_symbol[symbol] = realized_by_symbol.get(symbol, 0.0) + realized
                realized_by_leg[leg] = realized_by_leg.get(leg, 0.0) + realized
        values = {
            symbol: quantity * _price(prices, symbol, date)
            for symbol, quantity in positions.items()
            if quantity
        }
        entitlements.record_close(date, positions, lots)
        nav = cash + sum(values.values()) + entitlements.receivable
        if not math.isfinite(nav) or nav <= 0:
            raise PortfolioAccountingError(f"NAV must be positive on {date}")
        daily_pnl = nav - previous_nav - external_flow
        daily_return = daily_pnl / return_base
        symbol_pnl: dict[str, float] = dict(realized_by_symbol)
        for symbol, income in entitlements.income_by_symbol.items():
            symbol_pnl[symbol] = symbol_pnl.get(symbol, 0.) + income
        symbols_with_lots = {lot["symbol"] for lots_for_leg in lots.values() for lot in lots_for_leg}
        for symbol in symbols_with_lots:
            symbol_pnl[symbol] = symbol_pnl.get(symbol, 0.0) + sum(
                int(lot["quantity"]) * (_price(prices, lot["symbol"], date) - float(lot["price"]))
                for lots_for_symbol in lots.values() for lot in lots_for_symbol if lot["symbol"] == symbol
            )
        leg_pnl: dict[str, float] = dict(realized_by_leg)
        for leg, income in entitlements.income_by_leg.items():
            leg_pnl[leg] = leg_pnl.get(leg, 0.) + income
        for leg, lots_for_leg in lots.items():
            leg_pnl[leg] = leg_pnl.get(leg, 0.0) + sum(int(lot["quantity"]) * (_price(prices, lot["symbol"], date) - float(lot["price"])) for lot in lots_for_leg)
        for symbol, pnl in symbol_pnl.items():
            delta = pnl - previous_symbol_pnl.get(symbol, 0.0)
            dividend=entitlements.income_by_symbol.get(symbol,0.)-previous_income.get(symbol,0.)
            if abs(delta) > 1e-15 or abs(dividend)>1e-15:
                symbol_rows.append({"trade_date": date, "symbol": symbol, "pnl": float(pnl),
                    'daily_pnl':delta,'price_pnl':delta-dividend,'dividend_pnl':dividend,
                    "contribution": delta / return_base, "kind": "symbol"})
        for leg, pnl in leg_pnl.items():
            delta = pnl - previous_leg_pnl.get(leg, 0.0)
            if abs(delta) > 1e-15:
                leg_rows.append({"trade_date": date, "leg": leg, "pnl": float(pnl), "contribution": delta / return_base})
        factor_values = factor_pnl.get(date, {})
        factor_total = 0.0
        for factor, value in factor_values.items():
            number = _finite(value, f"factor P&L for {factor}")
            factor_total += number
            factor_rows.append({"trade_date": date, "factor": str(factor), "pnl": number, "contribution": number / return_base})
        residual = daily_pnl - factor_total
        symbol_delta=sum(pnl-previous_symbol_pnl.get(symbol,0.) for symbol,pnl in symbol_pnl.items())
        dividend_pnl=sum(entitlements.income_by_symbol.values())-sum(previous_income.values())
        price_pnl=symbol_delta-dividend_pnl
        contribution_residual=daily_pnl-symbol_delta-cash_pnl+fees
        ledger_rows.append({
            "trade_date": date, "cash": cash, "positions_value": sum(values.values()), "nav": nav,
            'receivables': entitlements.receivable,
            "daily_return": daily_return, "cash_weight": cash / nav, "gross_exposure": sum(values.values()) / nav,
            'daily_pnl':daily_pnl,'previous_equity':previous_nav,'price_pnl':price_pnl,'dividend_pnl':dividend_pnl,
            'external_flow':external_flow,'return_base':return_base,
            'price_contribution':price_pnl/return_base,
            'dividend_contribution':dividend_pnl/return_base,
            'contribution_residual_pnl':contribution_residual,
            'contribution_residual':contribution_residual/return_base,
            "net_exposure": sum(values.values()) / nav, "turnover_notional": turnover,
            "turnover": turnover / previous_nav if previous_nav else 0.0, "cost": fees,
            "cash_contribution": cash_pnl / return_base, "cash_pnl": cash_pnl,
            "cost_contribution": -fees / return_base,
            "benchmark_return": float(benchmark_returns[date]) if date in benchmark_returns else math.nan,
            "cash_return": float(cash_returns[date]) if date in cash_returns else math.nan,
            "factor_residual_pnl": residual if factor_values else math.nan,
            "factor_residual_contribution": residual / return_base if factor_values else math.nan,
            "reconciliation_delta": nav - cash - sum(values.values()) - entitlements.receivable,
        })
        previous_cash, previous_nav = cash, nav
        previous_symbol_pnl, previous_leg_pnl = dict(symbol_pnl), dict(leg_pnl)
        previous_income=dict(entitlements.income_by_symbol)

    ledger = pd.DataFrame(ledger_rows)
    performance=account_returns(dates=dates,nav=ledger.nav.tolist(),initial_cash=starting_cash,external_flows=external_flows)
    ledger['unit_nav']=performance['unit_nav']
    ledger['drawdown']=ledger.unit_nav/ledger.unit_nav.cummax().clip(lower=1.)-1
    symbols = pd.DataFrame(symbol_rows, columns=["trade_date", "symbol", "pnl",'daily_pnl','price_pnl','dividend_pnl', "contribution", "kind"])
    legs = pd.DataFrame(leg_rows, columns=["trade_date", "leg", "pnl", "contribution"])
    factors = pd.DataFrame(factor_rows, columns=["trade_date", "factor", "pnl", "contribution"])
    totals = symbols.groupby("trade_date")["contribution"].sum() if not symbols.empty else pd.Series(dtype=float)
    leg_totals = legs.groupby("trade_date")["contribution"].sum() if not legs.empty else pd.Series(dtype=float)
    ledger_totals = ledger.set_index("trade_date")["cash_contribution"] + ledger.set_index("trade_date")["cost_contribution"]
    contribution_status = "reconciled"
    for date, expected in ledger.set_index("trade_date")["daily_return"].dropna().items():
        actual = float(totals.get(date, 0.0)) + float(ledger_totals.get(date, 0.0))
        leg_actual = float(leg_totals.get(date, 0.0)) + float(ledger_totals.get(date, 0.0))
        if not (math.isclose(actual, float(expected), abs_tol=1e-8)
                and math.isclose(leg_actual, float(expected), abs_tol=1e-8)):
            contribution_status = "partial"
            break
    factor_dates = {str(date) for date in factor_pnl}
    required_factor_dates = set(dates[1:])
    factor_status = "unavailable" if not factor_pnl else (
        "available"
        if factor_dates.issuperset(required_factor_dates)
        and all(
            abs(float(row["factor_residual_pnl"])) <= 1e-8
            for row in ledger.to_dict("records")
            if str(row["trade_date"]) in required_factor_dates
        )
        else "partial"
    )
    required_benchmark_dates = set(dates[1:] or dates)
    covered_benchmark_dates = required_benchmark_dates.intersection(benchmark_returns)
    benchmark_status = "unavailable"
    if covered_benchmark_dates:
        benchmark_status = "available" if covered_benchmark_dates == required_benchmark_dates else "partial"
    diagnostics = {
        "nav_status": "reconciled" if ledger["reconciliation_delta"].abs().max() <= 1e-9 else "mismatch",
        "contribution_status": contribution_status,
        "factor_status": factor_status,
        "factor_source": factor_source,
        "benchmark_status": benchmark_status,
        'corporate_action_events': entitlements.events,
        'dividend_tax': 'gross_before_tax' if any(a.action_type == 'cash_dividend' for a in entitlements.actions) else 'not_applied',
        'external_flows':external_flows,'performance':performance,
    }
    risk = _risk(ledger, positions, prices, annualization_sessions, risk_window, industry_by_symbol, industry_pit_available)
    return PortfolioAccountingResult(ledger, symbols, legs, factors, risk, diagnostics)


def _risk(ledger: pd.DataFrame, positions: Mapping[str, int], prices: Mapping[str, Any], annualization: int, window: int | None, industries: Mapping[str, str] | None, pit: bool) -> dict[str, Any]:
    returns = ledger["daily_return"].dropna()
    if len(returns) > 1 and abs(float(returns.iloc[0])) <= 1e-15:
        returns = returns.iloc[1:]
    if window is not None:
        returns = returns.tail(window)
    last = ledger["trade_date"].iloc[-1]
    values = {symbol: qty * _price(prices, symbol, last) for symbol, qty in positions.items() if qty}
    total = sum(values.values())
    weights = [value / total for value in values.values()] if total else []
    historical_exposure = bool((ledger["gross_exposure"] > 0).any())
    result: dict[str, Any] = {"status": "available" if historical_exposure and len(returns) >= 2 else "unavailable", "observations": int(len(returns)) if historical_exposure else 0, "annualization_sessions": annualization, "window": window, "concentration_hhi": sum(w * w for w in weights) if weights else None, "industry_concentration_status": "unavailable_pit"}
    if pit and industries:
        if any(symbol not in industries for symbol in values):
            result["industry_concentration_status"] = "incomplete"
        elif total:
            grouped: dict[str, float] = {}
            for symbol, value in values.items():
                grouped[industries[symbol]] = grouped.get(industries[symbol], 0.0) + value / total
            result["industry_concentration"] = sum(w * w for w in grouped.values())
            result["industry_concentration_status"] = "available"
    if historical_exposure and len(returns) >= 2:
        mean = float(returns.mean())
        daily_vol = float(returns.std(ddof=0))
        vol = daily_vol * math.sqrt(annualization)
        daily_downside = math.sqrt(float((returns.clip(upper=0).pow(2).sum()) / len(returns)))
        # Anchor the selected return window before its first observation so
        # first-day fees and losses remain part of the drawdown calculation.
        curve = pd.Series([1.0, *(1.0 + returns).cumprod().tolist()])
        result.update({"annual_volatility": vol, "sharpe": mean * math.sqrt(annualization) / daily_vol if daily_vol else None, "sortino": mean * math.sqrt(annualization) / daily_downside if daily_downside else None, "max_drawdown": float((curve / curve.cummax() - 1).min())})
    return result
