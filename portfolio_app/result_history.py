"""Read-only projections of saved results; arrays retain their original periods."""
import pandas as pd


WORKSPACES = {'strategy': '策略', 'dashboard': '看盘研究', 'portfolio': '组合',
    'factors': '因子', 'factor-strategy': '因子策略', 'strategy-validation': '样本外验证'}


def result_projection(value):
    projection = dict(curve=None, ic=None, metrics=value.get('metrics', {}),
        tables={}, manifest=value.get('run_manifest'), parameters=value.get('research_parameters', {}))
    baseline = value.get('baseline', value.get('result'))
    if baseline is not None and hasattr(baseline, 'accounting'):
        ledger = baseline.accounting.ledger.copy(deep=True)
        initial = float(baseline.config['initial_cash'])
        curve = pd.DataFrame({'trade_date': ledger.trade_date, 'nav': ledger.nav / initial})
        # Include initial equity in peak so day-one costs remain a drawdown.
        curve['drawdown'] = curve.nav / curve.nav.cummax().clip(lower=1.) - 1.
        if 'drawdown' in ledger: curve['drawdown'] = ledger.drawdown
        projection.update(curve=curve, metrics=baseline.metrics,
            manifest=baseline.inputs.get('run_manifest'), parameters=baseline.config)
        projection['tables'] = {'资金账本': ledger, '持仓': baseline.positions.copy(),
            '订单': pd.DataFrame(baseline.orders), '成交': pd.DataFrame(baseline.fills),
            '证券贡献': baseline.accounting.symbol_contribution.copy()}
        if 'scenarios' in value: projection['tables']['场景比较'] = value['scenarios'].copy()
        return projection
    research = value.get('single_stock_research', value.get('portfolio_result'))
    if research is not None:
        frame = research.frame
        curve = frame[['trade_date', 'equity', 'drawdown']].rename(columns={'equity': 'nav'}).copy()
        if 'benchmark_equity' in frame: curve['benchmark_nav'] = frame.benchmark_equity
        projection.update(curve=curve, metrics=getattr(research, 'metrics',
            research.diagnostics.get('metrics', {})), manifest=research.diagnostics.get('run_manifest'),
            parameters=value.get('research_parameters') or getattr(research, 'strategy_config', {}))
        projection['tables'] = {'研究序列': frame.copy(), '交易事件': pd.DataFrame(research.trade_events)}
        return projection
    payload = value.get('result_payload') or {}
    performance = payload.get('performance') or {}
    if performance.get('curve'):
        curve = pd.DataFrame(performance['curve']).rename(columns={'date': 'trade_date'})
        projection['curve'] = curve
        projection['tables']['每日表现'] = curve.copy()
    details = payload.get('details') or {}
    for name, field in (('交易明细', 'trades'), ('持仓快照', 'positions')):
        if details.get(field): projection['tables'][name] = pd.DataFrame(details[field])
    projection['parameters'] = value.get('research_parameters') or payload.get('strategy_config',
        {'strategy': value.get('strategy_key'), 'symbols': value.get('symbols', ())})
    analysis = value.get('analysis') or {}
    if analysis.get('ic_series'):
        projection['ic'] = pd.DataFrame(analysis['ic_series'])
        projection['tables']['IC序列'] = projection['ic'].copy()
        projection['parameters'] = value.get('config', {})
        projection['metrics'] = {'有效IC交易日': value.get('overview', {}).get('valid_ic_sessions')}
    for name, key in (('分组收益', 'group_returns'), ('换手', 'turnover')):
        block = analysis.get(key) or {}
        rows = block.get('daily', block.get('rows'))
        if rows: projection['tables'][name] = pd.DataFrame(rows)
    for name in ('negative_controls', 'rolling_oos', 'validation_sensitivity'):
        if isinstance(value.get(name), pd.DataFrame): projection['tables'][name] = value[name].copy()
    return projection
