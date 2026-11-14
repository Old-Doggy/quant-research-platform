"""Daily historical research results for the local project detail view only."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd


def validate_curve(frame, date, *, nav=None, returns=None, initial_value=None):
    dates = pd.to_datetime(frame[date].astype(str), errors='coerce', format='mixed')
    values = pd.to_numeric(frame[nav if nav else returns], errors='coerce').astype(float)
    if (frame.empty or dates.isna().any() or dates.duplicated().any()
            or not dates.is_monotonic_increasing or not np.isfinite(values).all()):
        raise ValueError('Invalid daily dates or values')
    rets = pd.to_numeric(frame[returns], errors='coerce').astype(float) if returns else None
    if rets is not None and (not np.isfinite(rets).all() or (rets <= -1).any()):
        raise ValueError('Invalid daily returns')
    if nav:
        if (values <= 0).any():
            raise ValueError('NAV must be positive')
        # Recover the pre-first-session capital, retaining the first day's P&L.
        baseline = initial_value if initial_value is not None else (values.iloc[0] / (1 + rets.iloc[0]) if rets is not None else values.iloc[0])
        values = values / baseline
        if rets is not None and not np.allclose(values.pct_change().iloc[1:], rets.iloc[1:], atol=2e-6, rtol=2e-5):
            raise ValueError('NAV and daily returns disagree')
    else:
        values = (1 + rets).cumprod()
    dd = values / values.cummax().clip(lower=1) - 1
    return [dict(date=d.strftime('%Y-%m-%d'), value=float(v), drawdown=float(r))
            for d, v, r in zip(dates, values, dd)]


def load_project_curve(root, model_id, layer):
    # Published bundles contain aggregate results; private source trees are optional.
    if model_id not in {f'model{i}' for i in range(1, 8)} or not layer.replace('_', '').isalnum():
        return dict(status='unavailable', points=[], source='', sha256='')
    published = Path(root) / 'public_evidence' / 'curves' / f'{model_id}--{layer}.json'
    if published.is_file():
        try:
            content = published.read_bytes()
            record = json.loads(content)
            if record['model'] != model_id or record['scenario'] != layer:
                raise ValueError('Curve identifier mismatch')
            frame = pd.DataFrame(record['points'])
            checked = validate_curve(frame, 'date', nav='value', initial_value=1.)
            if not np.allclose(frame.drawdown, [p['drawdown'] for p in checked], atol=1e-12):
                raise ValueError('Published drawdown mismatch')
            return dict(status='available', points=checked, source=published.name,
                        sha256=sha256(content).hexdigest(), first_day_included=True,
                        **({'metrics': record['metrics']} if 'metrics' in record else {}))
        except (ValueError, KeyError, TypeError, OSError):
            return dict(status='missing_or_invalid', points=[], source='', sha256='')
    """Explicit model/scenario mapping; never substitute a different cost or run."""
    base = 'data/output/'
    specs = {
        ('model1', 'base'): (base+'model1_formal_cost_stress_20260507/model1_stress_base_daily_curve.csv', 'nav', 'daily_return'),
        ('model1', 'cost_x2'): (base+'model1_formal_cost_stress_20260507/model1_stress_cost_x2_daily_curve.csv', 'nav', 'daily_return'),
        ('model3', 'all_oos'): (base+'model3_vaa_formal_audit_full/model3_vaa_wfo_daily_returns.csv', 'nav', 'daily_ret'),
        ('model4', 't_minus_1_next_open_cost_x2'): (base+'model4_cb_execution_audit/model4_cb_t_minus_1_next_open_cost2p0x_daily.csv', 'nav', 'daily_return'),
        ('model5', 'base_wfo'): (base+'model5_pead_formal_audit/20260507_215750/model5_wfo_daily_returns.csv', None, 'daily_ret'),
        ('model5', 'stress_cost_x2'): (base+'model5_pead_formal_audit/20260507_215750/stress_cost_x2_daily_returns.csv', None, 'daily_ret'),
        ('model6', 'cost_x1'): (base+'model6_locked_validation_raw/model6_locked_candidate_daily_curves.csv', 'equity', 'daily_ret'),
        ('model6', 'cost_x2'): (base+'model6_locked_validation_raw/model6_locked_candidate_daily_curves.csv', 'equity', 'daily_ret'),
        ('model7', 'selection_validation'): ('模型7/output/daily_target_generation/20260429_211353/small_model2_top4_equal_top5_cap12_ind45_reb10_daily_curve.csv', 'equity', 'daily_ret'),
        ('model7', 'latest_local_backtest'): ('模型7/output/latest/small_model2_top4_equal_top5_cap12_ind45_reb10_daily_curve.csv', 'equity', 'daily_ret'),
    }
    empty = dict(status='unavailable', points=[], source='', sha256='')
    if (model_id, layer) == ('model2', 'local_native_wfo'):
        folder = Path(root) / '股票库筛选/output/model2_global_gate_2018_base32_3x3'
        try:
            # Replay the recorded annual choices against real per-parameter daily P&L.
            content = (folder / 'model2_global_pool_curves.csv').read_bytes()
            folds_bytes = (folder / 'model2_10_trend_low_drawdown_wfo_folds.csv').read_bytes()
            curves = pd.read_csv(BytesIO(content))
            curves = curves.loc[curves.pool_id.eq('10_trend_low_drawdown')].copy()
            curves['date'] = pd.to_datetime(curves.trade_date.astype(str), format='mixed')
            pieces = []
            for fold in pd.read_csv(BytesIO(folds_bytes)).to_dict('records'):
                part = curves.loc[curves.date.dt.year.eq(int(fold['test_year'])) & curves.param.eq(fold['chosen_param'])].sort_values('date')
                if part.empty or not np.isclose((1+part.daily_ret).prod()**(252/len(part))-1, fold['oos_annual'], atol=1e-8):
                    raise ValueError('WFO fold does not match saved diagnostics')
                pieces.append(part)
            points = validate_curve(pd.concat(pieces), 'date', returns='daily_ret')
            metrics_bytes = (folder / 'model2_global_pool_decision_table.csv').read_bytes()
            metrics = pd.read_csv(BytesIO(metrics_bytes))
            matched = metrics.loc[metrics.pool_id.eq('10_trend_low_drawdown')].iloc[0]
            calculated = points[-1]['value'] ** (252 / len(points)) - 1
            if not np.isclose(calculated, matched.wfo_annual, atol=1e-8):
                raise ValueError('Rebuilt WFO differs from recorded aggregate')
            return dict(status='available',points=points,source='model2_global_pool_curves.csv + model2_10_trend_low_drawdown_wfo_folds.csv',
                sha256=sha256(content+folds_bytes+metrics_bytes).hexdigest(),first_day_included=True,
                metrics=dict(annual_return=float(matched.wfo_annual),sharpe=float(matched.wfo_sharpe),max_drawdown=float(matched.wfo_max_drawdown)))
        except (OSError, ValueError, KeyError, pd.errors.ParserError):
            return {**empty,'status':'missing_or_invalid'}
    spec = specs.get((model_id, layer))
    if spec is None:
        return empty
    relative, nav, returns = spec
    try:
        content = (Path(root) / relative).read_bytes()
        frame = pd.read_csv(BytesIO(content))
        if model_id == 'model6':
            frame = frame.loc[pd.to_numeric(frame.cost_multiplier).eq(1 if layer == 'cost_x1' else 2)]
        points = validate_curve(frame, 'trade_date', nav=nav, returns=returns,
                                initial_value=1.0 if nav == 'nav' else None)
    except (OSError, ValueError, KeyError, pd.errors.ParserError):
        return {**empty, 'status': 'missing_or_invalid'}
    return dict(status='available', points=points, source=Path(relative).name,
                sha256=sha256(content).hexdigest(), first_day_included=True)
