"""Explicit session-opening external capital flows, TWR and unique-sign-change XIRR."""
import math
from datetime import date


def parse_flow_text(text):
    """One ISO date and signed CNY amount per line, with stable local IDs."""
    result=[]
    if not isinstance(text,str) or len(text)>10000:
        raise ValueError('出入金文本无效或过长')
    for index,line in enumerate(text.splitlines()):
        if not line.strip(): continue
        parts=line.replace('，',',').split(',')
        if len(parts)!=2: raise ValueError('每行填写日期,金额')
        day,number=(p.strip() for p in parts)
        if date.fromisoformat(day).isoformat()!=day: raise ValueError('出入金日期需要YYYY-MM-DD')
        amount=float(number)
        if not math.isfinite(amount) or amount==0: raise ValueError('出入金金额必须非零且有限')
        result.append(dict(flow_id=f'capital-line-{index+1}',session=day,amount=amount,timing='session_open'))
    if len(result)>100: raise ValueError('出入金最多100条')
    return result


def normalize_flows(flows,dates):
    seen=set();result=[]
    for flow in flows:
        if not isinstance(flow,dict) or set(flow)!={'flow_id','session','amount','timing'}:
            raise ValueError('出入金需要身份、交易日、金额和明确时点')
        identifier=flow['flow_id'];amount=flow['amount']
        if (not isinstance(identifier,str) or not identifier.strip() or identifier in seen
                or flow['session'] not in dates or flow['timing']!='session_open'
                or type(amount) not in (int,float) or not math.isfinite(amount) or amount==0):
            raise ValueError('出入金身份、日期、金额或时点无效')
        seen.add(identifier)
        result.append(dict(flow))
    return result


def _money_weighted(dates,nav,initial,flows):
    amounts={dates[0]:-initial}
    for flow in flows:
        amounts[flow['session']]=amounts.get(flow['session'],0.)-flow['amount']
    amounts[dates[-1]]=amounts.get(dates[-1],0.)+nav[-1]
    ordered=[(day,value) for day,value in sorted(amounts.items()) if value!=0]
    if len(ordered)<2:
        return None,'insufficient_duration'
    signs=[value>0 for _,value in ordered]
    if sum(a!=b for a,b in zip(signs,signs[1:]))!=1:
        return None,'multiple_sign_changes'
    origin=date.fromisoformat(dates[0])
    times=[(date.fromisoformat(day)-origin).days/365. for day,_ in ordered]
    # Solve in log(1+r); finite bracket deliberately limits extreme annualized IRR.
    def value(lograte):
        exponents=[-lograte*t for t in times]
        scale=max(exponents)
        return sum(amount*math.exp(exponent-scale) for (_,amount),exponent in zip(ordered,exponents))
    low,high=-20.,20.
    flo,fhi=value(low),value(high)
    if flo*fhi>0: return None,'no_root_in_supported_range'
    for _ in range(160):
        middle=(low+high)/2
        fm=value(middle)
        if fm==0: low=high=middle;break
        if flo*fm<=0: high=middle
        else: low=middle;flo=fm
    return math.expm1((low+high)/2),'available'


def account_returns(*,dates,nav,initial_cash,external_flows=()):
    dates=list(dates);nav=list(nav)
    if (not dates or len(dates)!=len(nav) or dates!=sorted(set(dates))
            or type(initial_cash) not in (int,float) or not math.isfinite(initial_cash) or initial_cash<=0):
        raise ValueError('收益需要有序日期、正初始权益与对应估值')
    for day in dates:
        if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:
            raise ValueError('收益日期无效')
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in nav):
        raise ValueError('账户估值必须为正有限数值')
    flows=normalize_flows(external_flows,dates)
    by_day={day:0. for day in dates}
    for flow in flows: by_day[flow['session']]+=flow['amount']
    previous=initial_cash;units=1.;returns=[];series=[]
    for day,equity in zip(dates,nav):
        base=previous+by_day[day]
        if base<=0: raise ValueError('出入金后期初权益必须为正')
        rate=equity/base-1
        units*=1+rate
        returns.append(rate);series.append(units);previous=equity
    annual,status=_money_weighted(dates,nav,initial_cash,flows)
    return dict(time_weighted_return=units-1,unit_nav=series,daily_returns=returns,
        money_weighted_annual=annual,money_weighted_status=status,external_flow_total=sum(by_day.values()),
        policy='session_open_flows_before_performance.v1',money_weighted_day_count='ACT/365',
        money_weighted_initial_date=dates[0],money_weighted_final_date=dates[-1])
