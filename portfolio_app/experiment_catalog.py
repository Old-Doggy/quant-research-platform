"""Metadata filters and descriptive risk/return points for saved runs."""
import numpy as np
import pandas as pd

from .result_history import WORKSPACES


def filter_records(records, *, query='', workspace=None):
    terms = query.casefold().split()
    return [dict(row) for row in records if (not workspace or row['workspace']==workspace)
        and all(term in ' '.join([row['task_id'], row['workspace'],
            WORKSPACES.get(row['workspace'], row['workspace']), row['created_at']]).casefold() for term in terms)]


def experiment_points(projections):
    rows, omitted = [], []
    for task_id, projection in projections.items():
        curve = projection.get('curve')
        try:
            if curve is None or curve.empty:
                raise ValueError('no curve')
            dates = pd.to_datetime(curve.trade_date, errors='raise')
            nav = pd.to_numeric(curve.nav, errors='raise')
            drawdown = pd.to_numeric(curve.drawdown, errors='raise')
            if (dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing
                    or not np.isfinite(nav).all() or nav.le(0).any()
                    or not np.isfinite(drawdown).all() or drawdown.gt(1e-8).any() or drawdown.lt(-1).any()):
                raise ValueError('invalid curve')
            rows.append(dict(task_id=task_id, total_return=float(nav.iloc[-1]-1),
                max_drawdown=float(drawdown.min()), start=dates.min().date().isoformat(),
                end=dates.max().date().isoformat(), sessions=len(curve)))
        except (ValueError, TypeError, AttributeError, KeyError):
            omitted.append(task_id)
    return pd.DataFrame(rows), omitted
