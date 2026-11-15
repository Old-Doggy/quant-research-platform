"""Shared-account portfolio research, synchronized drilldown and scenarios."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import math
from typing import Any

import pandas as pd

from .offline_execution import ExecutionSpec
from .offline_market_rules import AssetRule
from .portfolio_accounting import PortfolioAccountingResult, build_portfolio_accounting
from .portfolio_orders import plan_portfolio_orders
from .portfolio_recipe import PortfolioRecipe, resolve_portfolio_recipe
from .strategies import generate_signal, normalize_strategy_params
from .research_manifest import build_run_manifest
from .research_integrity import audit_research_input
from .strategy_catalog import audit_strategy_input
from .return_series import require_raw_execution_prices, require_action_free_proxy, build_return_series
from .corporate_actions import resolve_frame_actions


ENGINE = "portfolio-workspace.v1.2"
LIMITATIONS = (
    "日频多头离线模拟；订单数量使用决策日收盘价和当时净值。",
    "信号在下一会话成交，卖出优先；余单不自动追单，后续信号重新评估。",
    "合成演示无真实停牌、涨跌停或公司行为，假定可交易；不代表实际市场成交能力。",
    "不自动挑选最优场景；因子归因和行业集中度需另有可信时点数据。",
)


class PortfolioDataError(ValueError):
    """Data cannot support a comparable portfolio run."""


@dataclass(frozen=True)
class PortfolioWorkspaceResult:
    accounting: PortfolioAccountingResult
    positions: pd.DataFrame
    orders: list[dict[str, Any]]
    fills: list[dict[str, Any]]
    inputs: dict[str, Any]
    config: dict[str, Any]
    metrics: dict[str, Any]


def portfolio_data_fingerprint(frames, corporate_actions=()):
    """Identify the exact input snapshot, including changes under the same context."""
    digest = hashlib.sha256()
    from .research_manifest import semantic_hash
    digest.update(semantic_hash([asdict(a) for a in resolve_frame_actions(frames, corporate_actions)]).encode())
    for symbol, frame in sorted(frames.items()):
        digest.update(symbol.encode())
        digest.update(frame.to_csv(index=False, lineterminator="\n").encode())
    return digest.hexdigest()


def _prepare(frames, *, has_actions=False):
    if not frames:
        raise PortfolioDataError("portfolio data is empty")
    prepared, sessions = {}, None
    for symbol in sorted(frames):
        frame = frames[symbol].copy()
        require_raw_execution_prices(frame)
        if not has_actions:
            require_action_free_proxy(frame)
        if frame.empty or not {"trade_date", "open", "high", "low", "close"}.issubset(frame):
            raise PortfolioDataError("missing price fields")
        frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="coerce")
        if frame.trade_date.isna().any() or frame.trade_date.duplicated().any():
            raise PortfolioDataError("invalid sessions")
        frame = frame.sort_values("trade_date").reset_index(drop=True)
        dates = tuple(frame.trade_date.dt.strftime("%Y-%m-%d"))
        if sessions is not None and dates != sessions:
            raise PortfolioDataError("portfolio sessions must match; no missing-return filling")
        for field in ("open", "high", "low", "close"):
            values = pd.to_numeric(frame[field], errors="coerce")
            if not values.map(lambda v: math.isfinite(v) and v > 0).all():
                raise PortfolioDataError("prices must be positive finite numbers")
            frame[field] = values.astype(float)
        if ((frame.high < frame[["open", "close"]].max(axis=1))
                | (frame.low > frame[["open", "close"]].min(axis=1))
                | (frame.high < frame.low)).any():
            raise PortfolioDataError("inconsistent OHLC prices")
        sessions = dates
        frame["return"] = build_return_series(frame)
        prepared[symbol] = frame
    return prepared, sessions


def run_portfolio_workspace(frames, *, recipe: PortfolioRecipe, spec: ExecutionSpec,
                            strategy_key: str, params=None, initial_cash=100000.0, token=None,
                            target_schedule=None, factor_source=None, rebalance_sessions=None,
                            corporate_actions=()):
    from .research_display import check_research_size
    check_research_size(pd.concat(list(frames.values()), ignore_index=True) if frames else pd.DataFrame())
    if token:
        token.report(.05, 'preflight')
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial_cash must be positive finite")
    if any(not math.isfinite(v) or v < 0 for v in (spec.commission_bps, spec.slippage_bps)):
        raise ValueError("cost must be finite and non-negative")
    if spec.fill_model not in {"next_open", "next_close"} or spec.execution_lag_sessions != 1:
        raise ValueError("only next-session open/close is supported")
    if spec.price_field != {"next_open": "open", "next_close": "close"}[spec.fill_model]:
        raise ValueError("execution policy and price field disagree")
    integrity = {symbol: (audit_strategy_input(frame, strategy_key) if target_schedule is None
                         else audit_research_input(frame)) for symbol, frame in frames.items()}
    for frame in frames.values():
        require_raw_execution_prices(frame)
    from .entitlement_ledger import EntitlementBook
    entitlement_book = EntitlementBook(resolve_frame_actions(frames, corporate_actions))
    actions = entitlement_book.actions
    if any(action.symbol not in frames for action in actions):
        raise PortfolioDataError('公司行为证券不在研究范围')
    prepared, sessions = _prepare(frames, has_actions=bool(actions))
    params = normalize_strategy_params(strategy_key, params) if target_schedule is None else {}
    resolved = resolve_portfolio_recipe(recipe, set(prepared))
    if resolved.constraint_status != "within_bounds":
        raise ValueError("resolved weights violate recipe bounds")
    prices = {s: dict(zip(sessions, f.close.astype(float))) for s, f in prepared.items()}
    execution_prices = {s: dict(zip(sessions, f[spec.price_field].astype(float))) for s, f in prepared.items()}
    signals = {s: generate_signal(f, strategy_key, params=params)["signal"].tolist() for s, f in prepared.items()} if target_schedule is None else None
    if target_schedule is not None:
        if set(target_schedule) != set(sessions):
            raise ValueError('factor schedule sessions must match input')
        for weights in target_schedule.values():
            if set(weights) != set(prepared) or any(not math.isfinite(w) or w < 0 for w in weights.values()) or sum(weights.values()) > 1 + 1e-9:
                raise ValueError('invalid factor target weights')
    rules = {s: AssetRule(spec.asset_type, recipe.lot_size, spec.asset_type == "cn_stock") for s in prepared}
    cash, positions = float(initial_cash), {}
    orders, fills, snapshots = [], [], []
    pending = []
    action_lots = {}
    for index, date in enumerate(sessions):
        if token and index % 20 == 0:
            token.report(.1 + .7 * index / len(sessions), 'simulation')
        cash += entitlement_book.open_session(date, positions, action_lots)
        if pending:
            plan = plan_portfolio_orders(pending, sessions=sessions[index - 1:index + 1],
                spec=spec, recipe=recipe, initial_cash=cash, initial_positions=positions,
                prices=execution_prices, rules=rules, allow_partial_fill=True)
            for event in plan.events:
                row = {**asdict(event), 'decision_date': sessions[index - 1]}
                orders.append(row)
                if event.filled_quantity:
                    sign = 1 if event.side == 'BUY' else -1
                    price = event.price * (1 + sign * spec.slippage_bps / 10000)
                    fills.append(dict(fill_id=event.signal_id, decision_date=sessions[index - 1],
                        fill_date=event.effective_date, symbol=event.symbol, side=event.side,
                        quantity=event.filled_quantity, price=price,
                        fee=price * event.filled_quantity * spec.commission_bps / 10000, leg=event.strategy_id))
            cash, positions = plan.cash_after, plan.positions_after
        # Registration uses end-of-session holdings after today's actual fills.
        action_lots = {s: [dict(symbol=s, quantity=q)] for s, q in positions.items()}
        entitlement_book.record_close(date, positions, action_lots)
        pending = []
        if rebalance_sessions is not None and date not in rebalance_sessions:
            continue
        nav = cash + sum(q * prices[s][date] for s, q in positions.items()) + entitlement_book.receivable
        for symbol, weight in resolved.weights.items():
            effective_weight = weight * signals[symbol][index] if target_schedule is None else target_schedule[date][symbol]
            target = int(nav * effective_weight / prices[symbol][date] / recipe.lot_size) * recipe.lot_size
            current = positions.get(symbol, 0)
            delta = target - current
            if not delta or abs(delta * prices[symbol][date] / nav) < recipe.min_rebalance_weight:
                continue
            pending.append(dict(signal_id=f"{symbol}:{date}", strategy_id=symbol, symbol=symbol,
                decision_date=date, side="BUY" if delta > 0 else "SELL", quantity=abs(delta)))
        if pending and index == len(sessions) - 1:
            plan = plan_portfolio_orders(pending, sessions=sessions[index:index + 1],
                spec=spec, recipe=recipe, initial_cash=cash, initial_positions=positions,
                prices=execution_prices, rules=rules, allow_partial_fill=True)
            for event in plan.events:
                row = {**asdict(event), "decision_date": date}
                orders.append(row)
    accounting = build_portfolio_accounting(dates=sessions, prices=prices, fills=fills,
        initial_cash=initial_cash, corporate_actions=actions)
    if token:
        token.checkpoint()
    # Reconstruct daily holdings from actual fills, never from target weights.
    held = {}
    for date in sessions:
        for fill in fills:
            if fill["fill_date"] == date:
                symbol = fill["symbol"]
                held[symbol] = held.get(symbol, 0) + (1 if fill["side"] == "BUY" else -1) * fill["quantity"]
        for symbol, qty in held.items():
            if qty:
                snapshots.append(dict(trade_date=date, symbol=symbol, quantity=qty,
                    close=prices[symbol][date], market_value=qty * prices[symbol][date]))
    ledger = accounting.ledger
    total_return = float(ledger.iloc[-1].nav / initial_cash - 1)
    config = dict(recipe=recipe.to_dict(), execution=asdict(spec), strategy_key=strategy_key,
        params=dict(params or {}), initial_cash=initial_cash,
        corporate_actions=[asdict(action) for action in actions])
    if factor_source is not None:
        config['factor_source'] = factor_source
    inputs = dict(data_sha256=portfolio_data_fingerprint(prepared, actions), sessions=list(sessions), symbols=sorted(prepared),
        missing_symbols=list(resolved.missing_symbols), engine=ENGINE)
    inputs['dataset'] = next(iter(prepared.values())).attrs.get('research_dataset', {})
    inputs['integrity'] = integrity
    inputs['run_manifest'] = build_run_manifest(
        frame=pd.concat([f.assign(symbol=s) for s, f in prepared.items()], ignore_index=True),
        engine_id=ENGINE, features={'strategy': strategy_key, 'parameters': params or {}},
        labels={'kind': 'none'}, execution=asdict(spec), parameters=config,
        cost={'commission_bps': spec.commission_bps, 'slippage_bps': spec.slippage_bps},
        evaluation='fixed_parameter_cash_ledger', processing={'version': ENGINE,
            'sessions': 'exact_common_sessions', 'initial_cash': initial_cash})
    metrics = dict(total_return=total_return, total_cost=float(ledger.cost.sum()),
        max_drawdown=float((pd.Series([initial_cash, *ledger.nav]) / pd.Series([initial_cash, *ledger.nav]).cummax() - 1).min()),
        fills=len(fills), rejected=sum(o["status"] == "REJECTED" for o in orders),
        sharpe=accounting.risk.get("sharpe"))
    return PortfolioWorkspaceResult(accounting, pd.DataFrame(snapshots,
        columns=["trade_date", "symbol", "quantity", "close", "market_value"]), orders, fills, inputs, config, metrics)


def portfolio_drilldown(result, *, date, symbol=None):
    ledger = result.accounting.ledger
    if date not in set(ledger.trade_date):
        raise ValueError("date is outside the run")
    if symbol is not None and symbol not in result.inputs["symbols"]:
        raise ValueError("symbol is outside the run")
    positions = result.positions.loc[result.positions.trade_date.eq(date)].copy()
    contribution = result.accounting.symbol_contribution
    contribution = contribution.loc[contribution.trade_date.eq(date)].copy()
    if symbol is not None:
        positions = positions.loc[positions.symbol.eq(symbol)]
        contribution = contribution.loc[contribution.symbol.eq(symbol)]
    return dict(ledger=ledger.loc[ledger.trade_date.eq(date)].copy(),
        curve=ledger.loc[ledger.trade_date.le(date)].copy(), positions=positions,
        contribution=contribution,
        leg_contribution=result.accounting.leg_contribution.loc[
            result.accounting.leg_contribution.trade_date.eq(date)
        ].copy(),
        orders=[dict(o) for o in result.orders
            if ((o["effective_date"] == date) or
                (o["effective_date"] is None and o.get("decision_date") == date))
            and (symbol is None or o["symbol"] == symbol)])


def portfolio_scenarios(frames, *, recipe, spec, strategy_key, params=None, initial_cash=100000, variants=(), token=None,
                        corporate_actions=()):
    corporate_actions = tuple(corporate_actions)
    rows = []
    names = ["baseline", *(v[0] for v in variants)]
    if len(names) != len(set(names)):
        raise ValueError("duplicate scenario_id")
    for name, axis, value in [("baseline", "baseline", None), *variants]:
        if token:
            token.report(.85, 'scenarios')
        row = dict(scenario_id=name, changed_assumption=axis, comparable=False)
        try:
            candidate_recipe, candidate_spec = recipe, spec
            if axis == "cost":
                candidate_spec = replace(spec, commission_bps=float(value))
            elif axis == "weights":
                if set(value) != set(recipe.target_weights):
                    row.update(status="incomparable", reason="weight scenario changes the declared universe")
                    rows.append(row)
                    continue
                candidate_recipe = replace(recipe, target_weights=dict(value))
            elif axis == "execution":
                candidate_spec = replace(spec, fill_model=value, price_field={"next_open": "open", "next_close": "close"}[value])
            elif axis != "baseline":
                raise ValueError("unknown assumption")
            result = run_portfolio_workspace(frames, recipe=candidate_recipe, spec=candidate_spec,
                strategy_key=strategy_key, params=params, initial_cash=initial_cash, token=token,
                corporate_actions=corporate_actions)
            row.update(status="available", **result.metrics, config=result.config, data_sha256=result.inputs["data_sha256"])
        except (ValueError, KeyError) as exc:
            from .research_diagnostics import capture_error
            failure = capture_error(exc)
            row.update(status="data_blocked" if isinstance(exc, PortfolioDataError) else "failed",
                       reason=failure['message'], error_id=failure['error_id'])
        rows.append(row)
    baseline = rows[0]
    for row in rows:
        row["comparable"] = row["status"] == baseline["status"] == "available" and row["data_sha256"] == baseline["data_sha256"]
        for metric in ("total_return", "max_drawdown", "total_cost"):
            row[f"delta_{metric}"] = row[metric] - baseline[metric] if row["comparable"] else math.nan
    return pd.DataFrame(rows)
