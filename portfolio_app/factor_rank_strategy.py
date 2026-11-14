"""Causal long-only factor selection using the shared simulated cash account."""
from __future__ import annotations

import pandas as pd

from .factor_compute import compute_basic_factors
from .portfolio_recipe import PortfolioRecipe
from .portfolio_workspace import run_portfolio_workspace
from .research_result_cache import build_data_fingerprint


def factor_target_schedule(frame, draft, *, cash_weight=.1):
    selection = draft['selection']
    if selection['direction'] != 'long':
        raise ValueError('only long factor selection is supported by the cash account')
    top_k = selection['top_k']
    if type(top_k) is not int or top_k < 1:
        raise ValueError('top_k must be positive')
    frequency = selection['rebalance_frequency']
    if frequency not in {'daily', 'weekly', 'monthly'} or not 0 <= cash_weight <= 1:
        raise ValueError('invalid factor rebalance or cash weight')
    factor = draft['source']['factor_id']
    values = compute_basic_factors(frame, {factor})
    column = factor.split('.', 1)[-1]
    symbols = sorted(frame.symbol.unique())
    weights = dict.fromkeys(symbols, 0.)
    schedule, prior_bucket = {}, None
    for date, cross_section in values.groupby('trade_date', sort=True):
        bucket = str(date) if frequency == 'daily' else str(date.to_period('W' if frequency == 'weekly' else 'M'))
        if bucket != prior_bucket:
            valid = cross_section.dropna(subset=[column]).sort_values([column, 'symbol'], ascending=[False, True])
            selected = set(valid.head(top_k).symbol)
            weights = {s: (1-cash_weight)/len(selected) if s in selected else 0. for s in symbols}
            prior_bucket = bucket
        schedule[date.date().isoformat()] = dict(weights)
    return schedule


def run_factor_strategy(frame, draft, *, spec, cash_weight=.1, initial_cash=100000., token=None):
    if draft['source']['data_version'] != build_data_fingerprint(frame):
        raise ValueError('factor source data version changed; recreate the draft')
    symbols = sorted(frame.symbol.unique())
    common = set.intersection(*(set(group.trade_date) for _, group in frame.groupby('symbol')))
    aligned = frame.loc[frame.trade_date.isin(common)].copy()
    if aligned.empty:
        raise ValueError('no common sessions for factor strategy')
    schedule = factor_target_schedule(aligned, draft, cash_weight=cash_weight)
    frequency = draft['selection']['rebalance_frequency']
    rebalance_sessions, prior_bucket = set(), None
    for date in sorted(schedule):
        bucket = date if frequency == 'daily' else str(pd.Timestamp(date).to_period('W' if frequency == 'weekly' else 'M'))
        if bucket != prior_bucket:
            rebalance_sessions.add(date)
        prior_bucket = bucket
    recipe = PortfolioRecipe('factor-rank', {s:(1-cash_weight)/len(symbols) for s in symbols},
        cash_weight, {}, {}, 100, .01, 'fail')
    source = {**draft['source'], 'selection': draft['selection'],
        'alignment': 'explicit_common_sessions', 'excluded_rows': len(frame)-len(aligned)}
    return run_portfolio_workspace({s:aligned.loc[aligned.symbol.eq(s)].copy() for s in symbols},
        recipe=recipe, spec=spec, strategy_key='factor_rank', initial_cash=initial_cash,
        token=token, target_schedule=schedule, factor_source=source, rebalance_sessions=rebalance_sessions)
