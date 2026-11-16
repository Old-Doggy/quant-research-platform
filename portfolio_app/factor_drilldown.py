"""Read-only period statistics and independently checked date cross-sections."""
import math

import numpy as np
import pandas as pd

from .factor_analysis import compute_ic_series


def _series(result):
    frame = pd.DataFrame(result['analysis']['ic_series']).copy()
    if frame.empty:
        return frame
    frame['trade_date'] = pd.to_datetime(frame.trade_date, errors='raise')
    if frame.trade_date.duplicated().any():
        raise ValueError('IC日期重复')
    frame['ic'] = pd.to_numeric(frame.ic, errors='raise')
    frame.loc[frame.status.ne('ok') | ~np.isfinite(frame.ic), 'ic'] = np.nan
    return frame.sort_values('trade_date')


def factor_periods(result):
    series = _series(result)
    rows = []
    if series.empty:
        return pd.DataFrame()
    for period, group in series.groupby(series.trade_date.dt.to_period('Q'), sort=True):
        valid = group.ic.dropna()
        rows.append(dict(period=str(period), sessions=len(group), valid_sessions=len(valid),
            ic_mean=float(valid.mean()) if len(valid) else math.nan,
            ic_std=float(valid.std(ddof=1)) if len(valid) >= 2 else math.nan,
            positive_ratio=float(valid.gt(0).mean()) if len(valid) else math.nan,
            first_date=group.trade_date.min().date().isoformat(),
            last_date=group.trade_date.max().date().isoformat()))
    return pd.DataFrame(rows)


def factor_cross_section(result, session):
    series = _series(result)
    saved = series.loc[series.trade_date.dt.strftime('%Y-%m-%d').eq(session)]
    if len(saved) != 1:
        raise ValueError('未记录该日期的IC')
    detail = pd.DataFrame(result['detail'])
    dates = pd.to_datetime(detail.trade_date, errors='raise').dt.strftime('%Y-%m-%d')
    detail = detail.loc[dates.eq(session)].copy()
    if detail.empty:
        raise ValueError('该日期没有截面记录')
    if detail.symbol.duplicated().any():
        raise ValueError('截面证券重复')
    minimum = int(result['config']['min_assets_per_date'])
    recomputed = compute_ic_series(detail, min_observations=minimum).data.iloc[0]
    stored = saved.iloc[0]
    if (stored.status != recomputed.status or (stored.status == 'ok' and
            not math.isclose(float(stored.ic), float(recomputed.ic), abs_tol=1e-10, rel_tol=1e-10))
            or ('valid_n' in stored and int(stored.valid_n) != int(recomputed.valid_n))):
        raise ValueError('截面重算与保存的IC不一致')
    for field in ('factor', 'forward_label'):
        detail[field] = pd.to_numeric(detail[field], errors='raise')
    detail = detail.loc[np.isfinite(detail.factor) & np.isfinite(detail.forward_label)]
    detail = detail.sort_values(['factor', 'symbol'], kind='stable').reset_index(drop=True)
    detail['factor_rank'] = detail.factor.rank(method='average')
    detail['label_rank'] = detail.forward_label.rank(method='average')
    return dict(frame=detail, ic=float(recomputed.ic) if recomputed.status == 'ok' else None,
        samples=len(detail), status=recomputed.status, session=session)
