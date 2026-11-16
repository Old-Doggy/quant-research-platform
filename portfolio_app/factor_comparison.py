"""Actual daily cross-sectional correlations and separate common-date IC correlations."""
from itertools import combinations

import numpy as np
import pandas as pd

from .factor_analysis import compute_ic_series
from .factor_compute import BASIC_FACTOR_SPECS,compute_basic_factors
from .factor_contracts import LabelSpec
from .factor_labels import build_forward_labels
from .factor_stability import _validate,_numeric,_rank_corr
from .research_integrity import audit_research_input


def _pair(left,right,minimum):
    pair=pd.concat([left,right],axis=1).dropna()
    n=len(pair)
    status='insufficient_observations' if n<minimum else 'constant_factor' if any(
        pair.iloc[:,i].nunique()<=1 for i in (0,1)) else 'ok'
    value=_rank_corr(pair.iloc[:,0],pair.iloc[:,1]) if status=='ok' else np.nan
    return dict(correlation=value,common_n=n,status=status)


def compare_factor_values(frame,*,factors,min_assets=3,min_ic_dates=20):
    if (not isinstance(factors,list) or not 2<=len(factors)<=6 or len(set(factors))!=len(factors)
            or any(not isinstance(f,str) for f in factors)):
        raise ValueError('比较需要2至6个不同实际因子')
    if any(type(n) is not int or n<2 for n in (min_assets,min_ic_dates)):
        raise ValueError('共同证券数和IC日期数至少为2')
    data=_validate(frame,{'symbol','trade_date','forward_label',*factors})
    for field in [*factors,'forward_label']:
        data[field]=_numeric(data[field],field)
    daily=[]
    for session,group in data.groupby('trade_date',sort=True):
        for left,right in combinations(factors,2):
            daily.append(dict(trade_date=session,left=left,right=right,
                **_pair(group[left],group[right],min_assets)))
    daily=pd.DataFrame(daily)
    cross=[]
    for (left,right),group in daily.groupby(['left','right'],sort=False):
        valid=group.loc[group.status.eq('ok'),'correlation']
        cross.append(dict(left=left,right=right,correlation=valid.mean(),valid_sessions=len(valid),
            common_n=int(group.common_n.sum()),status='ok' if len(valid) else 'no_valid_sessions'))
    ic={factor:compute_ic_series(data,factor_column=factor,min_observations=min_assets).data
        for factor in factors}
    joined=pd.concat({f:part.set_index('trade_date').ic for f,part in ic.items()},axis=1)
    ic_pairs=[dict(left=left,right=right,**_pair(joined[left],joined[right],min_ic_dates))
        for left,right in combinations(factors,2)]
    return dict(values=data,daily=daily,cross_section=pd.DataFrame(cross),
        ic_correlation=pd.DataFrame(ic_pairs),ic_series=joined.reset_index(),factors=list(factors),
        method='spearman',aggregation='equal_weight_valid_daily_cross_sections',
        min_assets=min_assets,min_ic_dates=min_ic_dates)


def comparison_sample(result,*,left,right,session):
    if left==right or any(f not in result['factors'] for f in (left,right)):
        raise ValueError('比较因子不存在或相同')
    data=result['values']
    return data.loc[data.trade_date.eq(pd.Timestamp(session)),['symbol',left,right]].dropna().rename(
        columns={left:'left_value',right:'right_value'}).reset_index(drop=True)


def research_factor_comparison(frame,*,factor_ids,horizon,start,end,min_assets=3):
    specs={s.factor_id:s for s in BASIC_FACTOR_SPECS}
    if (not isinstance(factor_ids,list) or not 2<=len(factor_ids)<=6
            or len(set(factor_ids))!=len(factor_ids) or not set(factor_ids)<=specs.keys()):
        raise ValueError('请选择2至6个已实现的价量因子')
    begin,cutoff=pd.Timestamp(start),pd.Timestamp(end)
    if pd.isna(begin) or pd.isna(cutoff) or begin>cutoff:
        raise ValueError('因子比较日期无效')
    source=frame.loc[pd.to_datetime(frame.trade_date).le(cutoff)].copy()
    audit_research_input(source,feature_fields=tuple(sorted(set().union(
        *(set(specs[f].input_fields) for f in factor_ids)))))
    computed=compute_basic_factors(source,factor_ids=set(factor_ids))
    columns=[f.split('.',1)[1] for f in factor_ids]
    label=LabelSpec(label_id=f'forward-{horizon}d',version='1.0.0',prediction_direction='forward_return',
        horizon_sessions=horizon,anchor='observation_close',return_convention='close_to_close',
        tail_policy='preserve_missing',overlapping=True,available_at_policy='future_session_close')
    labels=build_forward_labels(source,label).data
    values=computed[['symbol','trade_date',*columns]].merge(
        labels[['symbol','trade_date','forward_label']],on=['symbol','trade_date'],validate='one_to_one')
    values=values.loc[values.trade_date.between(begin,cutoff)]
    result=compare_factor_values(values,factors=columns,min_assets=min_assets)
    return {**result,'factor_ids':list(factor_ids),'horizon':horizon,'start':start,'end':end}
