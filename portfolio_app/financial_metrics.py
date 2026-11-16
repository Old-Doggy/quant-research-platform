"""Additive cash/profit metrics use explicit report basis and known units."""
import math

from .financial_query import financial_asof


ADDITIVE_FIELDS={
    'income':frozenset({'total_revenue','revenue','n_income','n_income_attr_p'}),
    'cashflow':frozenset({'n_cashflow_act','n_cashflow_inv_act','n_cash_flows_fnc_act'}),
}


def cumulative_flow_metric(store, *, endpoint, symbol, field, as_of, calendar, mode='ttm', unit, provider='tushare'):
    if endpoint not in ADDITIVE_FIELDS or field not in ADDITIVE_FIELDS[endpoint]:
        raise ValueError('该字段不是可累加利润或现金流，不能按累计报表算TTM')
    if unit!='CNY':
        raise ValueError('需先核验所选财务字段为人民币元，不能猜测单位')
    if mode not in {'ttm','single_quarter'}:
        raise ValueError('财务转换仅支持TTM或单季度')
    options=dict(endpoint=endpoint,symbol=symbol,as_of=as_of,calendar=calendar,report_type='1',provider=provider)
    current=financial_asof(store,**options)
    if current is None:
        return dict(status='unavailable',value=None,reason='no_available_report',inputs=[])
    period=current['period']
    year=int(period[:4])
    terms=[(1,current)]
    required=[]
    if mode=='ttm' and period[5:]!='12-31':
        required=[(1,f'{year-1}-12-31'),(-1,f'{year-1}'+period[4:])]
    elif mode=='single_quarter' and period[5:]!='03-31':
        previous={'06-30':'03-31','09-30':'06-30','12-31':'09-30'}[period[5:]]
        required=[(-1,f'{year}-{previous}')]
    for sign,needed in required:
        report=financial_asof(store,period=needed,**options)
        if report is None:
            return dict(status='unavailable',value=None,reason='missing_required_period',period=period,
                missing_period=needed,inputs=[r['report_version'] for _,r in terms])
        terms.append((sign,report))
    value=0.
    for sign,report in terms:
        number=report.get(field)
        if number is None or not math.isfinite(float(number)):
            return dict(status='unavailable',value=None,reason='missing_required_value',period=period,
                missing_period=report['period'],inputs=[r['report_version'] for _,r in terms])
        value+=sign*float(number)
    return dict(status='available',value=value,unit=unit,period=period,as_of=as_of,mode=mode,
        definition='cumulative-current-plus-prior-annual-minus-prior-same-quarter.v1' if mode=='ttm'
            else 'cumulative-current-minus-prior-quarter.v1',
        inputs=[dict(coefficient=sign,period=r['period'],report_version=r['report_version'],artifact_id=r['artifact_id'],
            available_at=r['available_at']) for sign,r in terms],pit_coverage='forward_observation_only')
