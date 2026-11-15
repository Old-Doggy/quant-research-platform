"""Independently reconcile published aggregates without inventing trade history."""
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .local_project_curves import load_project_curve


EXPECTED = {
    'model1': ('base', 'cost_x2'), 'model2': ('local_native_wfo',), 'model3': ('all_oos',),
    'model4': ('t_minus_1_next_open_cost_x2',), 'model5': ('base_wfo', 'stress_cost_x2'),
    'model6': ('cost_x1', 'cost_x2'), 'model7': ('selection_validation', 'latest_local_backtest')}


def audit_published_results(root):
    root = Path(root)
    curves, models = [], []
    for model, scenarios in EXPECTED.items():
        summary = pd.read_csv(root / 'public_evidence' / f'{model}_summary.csv')
        gate = 'review_required' if model in {'model2', 'model6'} else 'historical_evidence'
        models.append(dict(model=model, research_gate=gate, runtime_performance='unavailable',
            summary_sha256=hashlib.sha256((root / 'public_evidence' / f'{model}_summary.csv').read_bytes()).hexdigest()))
        for scenario in scenarios:
            path = root / 'public_evidence/curves' / f'{model}--{scenario}.json'
            row = dict(model=model, scenario=scenario, file=path.name,
                classification='historical_aggregate_only', research_gate=gate,
                execution_revalidation='requires_original_prices_fills_and_event_snapshot')
            if not path.is_file():
                curves.append({**row, 'status': 'missing'})
                continue
            curve = load_project_curve(root, model, scenario)
            if not curve['points']:
                curves.append({**row, 'status': 'invalid_curve'})
                continue
            record = json.loads(path.read_bytes())
            frame = pd.DataFrame(curve['points'])
            values = frame.value.to_numpy()
            prior = np.r_[1., values[:-1]]
            returns = values / prior - 1
            annual = float(values[-1] ** (252 / len(values)) - 1)
            drawdown = float((values / np.maximum.accumulate(np.r_[1., values])[1:] - 1).min())
            risk_free = .02 if model == 'model2' else 0. if model == 'model4' else .03
            if model == 'model4':
                # Source audit records first return as zero while NAV retains day-one P&L.
                returns[0] = 0.
            volatility = float(returns.std(ddof=1) * math.sqrt(252))
            sharpe = float((returns.mean() * 252 - risk_free) / volatility) if volatility else None
            matching = summary.loc[summary.evidence_case.eq(scenario)]
            metrics = matching.iloc[0].to_dict() if len(matching) else record.get('metrics', {})
            computed = dict(annual_return=annual, max_drawdown=drawdown, sharpe=sharpe)
            deltas = {key: value - float(metrics[key]) for key, value in computed.items()
                      if key in metrics and value is not None}
            consistent = len(deltas) == 3 and all(abs(delta) <= 2e-6 for delta in deltas.values())
            source_hash = record.get('source_sha256', '')
            consistent &= bool(re.fullmatch('[a-f0-9]{64}', source_hash))
            if len(matching):
                declared = re.findall(r'\d{4}-\d{2}-\d{2}', str(matching.iloc[0]['period']))
                if len(declared) >= 2 and ('至' in str(matching.iloc[0]['period'])):
                    consistent &= declared[:2] == [frame.date.iloc[0], frame.date.iloc[-1]]
            curves.append({**row, 'status': 'reconciled' if consistent else 'mismatch',
                'sessions': len(values), 'start': frame.date.iloc[0], 'end': frame.date.iloc[-1],
                'file_sha256': curve['sha256'], 'source_sha256': source_hash,
                'computed': computed, 'deltas': deltas,
                'definition': dict(annualization=252, risk_free=risk_free, volatility_ddof=1,
                    first_return='zero_source_convention' if model == 'model4' else 'includes_initial_pnl')})
    expected_files = {f'{m}--{s}.json' for m, scenarios in EXPECTED.items() for s in scenarios}
    unexpected = sorted(p.name for p in (root / 'public_evidence/curves').glob('*.json') if p.name not in expected_files)
    return dict(schema_version='historical-audit.v1',
        status='passed' if all(r['status'] == 'reconciled' for r in curves) and not unexpected else 'failed',
        curves=curves, models=models, unexpected_files=unexpected)
