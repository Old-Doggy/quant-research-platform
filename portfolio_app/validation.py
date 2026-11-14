from __future__ import annotations

import pandas as pd

from portfolio_app.backtest import run_backtest
from portfolio_app.strategies import generate_signal, normalize_strategy_params
from .research_integrity import (audit_research_input, assert_causal_prefix,
                                 temporal_split, check_fit_scope)
from .research_manifest import build_run_manifest


def walk_forward_report(
    frame: pd.DataFrame,
    strategy_key: str,
    *,
    train_bars: int = 252,
    test_bars: int = 63,
    params: dict[str, object] | None = None,
    transaction_cost: float = 0.001,
) -> pd.DataFrame:
    """Run fixed-parameter rolling OOS slices without using future test rows."""
    if train_bars < 1 or test_bars < 1:
        raise ValueError("train_bars and test_bars must be positive")
    if transaction_cost < 0:
        raise ValueError("transaction_cost must be non-negative")
    source = frame.sort_values("trade_date", kind="stable").reset_index(drop=True).copy()
    audit_research_input(source)
    normalized = normalize_strategy_params(strategy_key, params)
    rows = []
    cursor = train_bars
    while cursor + test_bars <= len(source):
        train = source.iloc[cursor - train_bars:cursor].copy()
        test = source.iloc[cursor:cursor + test_bars].copy()
        # Signal generation uses the train tail as feature warm-up, but metrics
        # are calculated only on the future test dates.
        context = pd.concat([train.tail(max(train_bars, 260)), test], ignore_index=True)
        signalled = generate_signal(context, strategy_key, params=normalized)
        test_signal = signalled.tail(len(test)).copy()
        _, metrics = run_backtest(test_signal, transaction_cost=transaction_cost)
        rows.append({
            "窗口": len(rows) + 1,
            "训练开始": train["trade_date"].iloc[0].strftime("%Y-%m-%d"),
            "训练截止": train["trade_date"].iloc[-1].strftime("%Y-%m-%d"),
            "测试开始": test["trade_date"].iloc[0].strftime("%Y-%m-%d"),
            "测试截止": test["trade_date"].iloc[-1].strftime("%Y-%m-%d"),
            "测试收益": metrics["total_return"], "年化收益": metrics["annual_return"],
            "夏普": metrics["sharpe"], "最大回撤": metrics["max_drawdown"], "交易次数": metrics["trades"],
        })
        cursor += test_bars
    return pd.DataFrame(rows, columns=["窗口", "训练开始", "训练截止", "测试开始", "测试截止", "测试收益", "年化收益", "夏普", "最大回撤", "交易次数"])


def _neighborhood(strategy_key: str, params: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    base = normalize_strategy_params(strategy_key, params)
    if strategy_key == "trend":
        pairs = [(max(5, int(base["fast_window"]) - 5), int(base["slow_window"])),
                 (int(base["fast_window"]), int(base["slow_window"])),
                 (min(60, int(base["fast_window"]) + 5), int(base["slow_window"]))]
        pairs = list(dict.fromkeys(pairs))
        return [(f"fast={fast},slow={slow}", normalize_strategy_params(strategy_key, {**base, "fast_window": fast, "slow_window": slow})) for fast, slow in pairs if fast < slow]
    if strategy_key == "mean_reversion":
        values = list(dict.fromkeys([max(10, int(base["lookback_window"]) - 5), int(base["lookback_window"]), min(120, int(base["lookback_window"]) + 5)]))
        return [(f"lookback={value}", normalize_strategy_params(strategy_key, {**base, "lookback_window": value})) for value in values]
    values = list(dict.fromkeys([max(20, int(base["momentum_window"]) - 10), int(base["momentum_window"]), min(200, int(base["momentum_window"]) + 10)]))
    return [(f"momentum={value}", normalize_strategy_params(strategy_key, {**base, "momentum_window": value})) for value in values]


def sensitivity_report(
    frame: pd.DataFrame,
    strategy_key: str,
    *,
    params: dict[str, object] | None = None,
    transaction_cost: float = 0.001,
    slippage_bps: tuple[int, ...] = (0, 5, 10),
) -> pd.DataFrame:
    audit_research_input(frame)
    if any(int(value) < 0 for value in slippage_bps):
        raise ValueError("slippage_bps cannot be negative")
    rows = []
    for label, candidate in _neighborhood(strategy_key, params or {}):
        signalled = generate_signal(frame, strategy_key, params=candidate)
        for bps in slippage_bps:
            # Slippage is an explicit additional per-turnover cost in this
            # presentation report; it does not claim a full market-impact model.
            _, metrics = run_backtest(signalled, transaction_cost=transaction_cost + int(bps) / 10000)
            rows.append({"参数": label, "额外滑点bp": int(bps), "区间收益": metrics["total_return"],
                         "年化收益": metrics["annual_return"], "夏普": metrics["sharpe"],
                         "最大回撤": metrics["max_drawdown"], "交易次数": metrics["trades"]})
    return pd.DataFrame(rows)


def locked_validation_report(frame, strategy_key, *, params=None, transaction_cost=.001, horizon=5, token=None):
    """Fixed-parameter diagnostics with a locked test, not a retrained WFO.

    Neighborhood/cost diagnostics and deterministic negative controls use only
    validation sessions. No best parameter is selected. Test windows use the
    user-specified parameters and full causal history for indicator warm-up.
    """
    if not pd.notna(transaction_cost) or not 0 <= transaction_cost < 1:
        raise ValueError('transaction_cost must be finite and between zero and one')
    source = frame.sort_values('trade_date', kind='stable').reset_index(drop=True).copy()
    source['trade_date'] = pd.to_datetime(source.trade_date)
    if source.trade_date.duplicated().any():
        raise ValueError('fixed-parameter OOS requires one symbol and unique sessions')
    integrity = audit_research_input(source)
    normalized = normalize_strategy_params(strategy_key, params)
    prefix = assert_causal_prefix(source, lambda f: generate_signal(f, strategy_key, params=normalized)['signal'])
    split = temporal_split(source.trade_date, horizon=horizon)
    validation_indices = split['validation']
    validation_end = max(validation_indices) + 1
    # Generate using all past prices, then score only validation sessions.
    # Starting exposure is zero at each scoring boundary, with costs reapplied.
    rows = []
    for label, candidate in _neighborhood(strategy_key, normalized):
        if token:
            token.report(.2, 'validation')
        signals = generate_signal(source.iloc[:validation_end], strategy_key, params=candidate)
        for bps in (0, 5, 10):
            if token:
                token.checkpoint()
            _, metrics = run_backtest(signals.iloc[validation_indices].copy(),
                transaction_cost=transaction_cost + bps / 10000, execution_policy='next_day_close')
            rows.append({'参数': label, '额外滑点bp': bps, '区间收益': metrics['total_return'],
                         '最大回撤': metrics['max_drawdown'], 'scope': 'validation_only'})
    sensitivity = pd.DataFrame(rows)
    controls = []
    base = generate_signal(source.iloc[:validation_end], strategy_key, params=normalized)
    for name in ('all_cash', 'lagged_signal_5'):
        if token:
            token.report(.6, 'validation')
        control = base.copy()
        control['signal'] = 0 if name == 'all_cash' else base.signal.shift(5).fillna(0)
        _, metrics = run_backtest(control.iloc[validation_indices].copy(), transaction_cost=transaction_cost,
                                  execution_policy='next_day_close')
        controls.append(dict(control=name, total_return=metrics['total_return'], scope='validation_only'))
    oos = []
    test_indices = split['test']
    for offset in range(0, len(test_indices), 63):
        if token:
            token.report(.7 + .2 * offset / len(test_indices), 'validation')
        indices = test_indices[offset:offset + 63]
        signals = generate_signal(source.iloc[:max(indices) + 1], strategy_key, params=normalized)
        _, metrics = run_backtest(signals.iloc[indices].copy(), transaction_cost=transaction_cost,
                                  execution_policy='next_day_close')
        oos.append(dict(window=len(oos) + 1, start=str(source.trade_date.iloc[min(indices)].date()),
            end=str(source.trade_date.iloc[max(indices)].date()), observations=len(indices),
            total_return=metrics['total_return'], max_drawdown=metrics['max_drawdown']))
    attempts = len(sensitivity) + len(controls) + len(oos)
    scope = check_fit_scope(split, fit_sessions=[], tune_sessions=[], attempts=attempts)
    manifest = build_run_manifest(frame=source, engine_id='fixed-parameter-validation.v1',
        features={'strategy': strategy_key}, labels={'horizon': horizon},
        execution={'policy': 'next_day_close', 'window_initial_position': 0},
        parameters=normalized, cost={'turnover': transaction_cost, 'extra_bps': [0, 5, 10]},
        evaluation='fixed_parameter_oos', processing={'split': split, 'version': 1})
    return dict(method='fixed_parameter_oos', fit_performed=False,
        run_manifest=manifest,
        test_used_for_selection=False, selected_parameters=None, attempts=attempts,
        split=split, fit_scope=scope, validation_sensitivity=sensitivity,
        negative_controls=pd.DataFrame(controls), rolling_oos=pd.DataFrame(oos),
        statistics='descriptive_only_no_iid_t_test', integrity=integrity, prefix=prefix,
        limitations=['无训练器；训练段仅作为历史上下文，不执行拟合或自动选优。',
            '所有评分窗口独立从空仓开始；窗口收益不能拼成连续资金账户。',
            '负对照只作诊断，不是随机显著性检验；重叠收益不默认独立 t 检验。'])
