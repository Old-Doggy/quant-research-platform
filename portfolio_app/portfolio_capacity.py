"""Trailing observed turnover diagnostics; no execution or impact forecast."""
import math

import numpy as np
import pandas as pd


COLUMNS=['symbol','market_value','window_start','window_end','observed_sessions','average_amount',
         'daily_budget','holding_to_daily_amount','estimated_sessions','status']


def capacity_inputs(frames):
    """Capture only dated turnover from the submitted input, never the current UI."""
    return {s:f[[c for c in ('trade_date','amount') if c in f]].copy(deep=True) for s,f in frames.items()}


def capacity_report(positions,frames,*,sessions,date,window=20,participation_rate=.05):
    if (type(window) is not int or not 2<=window<=252 or isinstance(participation_rate,bool)
            or not isinstance(participation_rate,(int,float)) or not 0<participation_rate<=1):
        raise ValueError('容量窗口或参与率无效')
    dates=pd.to_datetime(pd.Series(sessions),errors='coerce')
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError('容量交易日历无效')
    labels=dates.dt.strftime('%Y-%m-%d').tolist()
    if date not in labels:
        raise ValueError('容量日期不在研究区间')
    expected=labels[max(0,labels.index(date)-window):labels.index(date)]
    if positions.empty:
        return pd.DataFrame(columns=COLUMNS)
    if not {'symbol','market_value'}<=set(positions) or positions.symbol.duplicated().any():
        raise ValueError('容量持仓无效或重复')
    rows=[]
    for position in positions.itertuples():
        if not math.isfinite(position.market_value) or position.market_value<0:
            raise ValueError('容量持仓市值无效')
        row=dict.fromkeys(COLUMNS,np.nan)
        row.update(symbol=position.symbol,market_value=position.market_value,
            window_start=expected[0] if expected else None,window_end=expected[-1] if expected else None,
            observed_sessions=0,status='missing_input')
        frame=frames.get(position.symbol)
        if frame is None:
            rows.append(row);continue
        if frame.attrs.get('field_units',{}).get('amount')!='CNY' or frame.attrs.get('field_units',{}).get('price')!='CNY_per_share':
            row['status']='unknown_units';rows.append(row);continue
        if not {'amount','trade_date'}<=set(frame):
            row['status']='missing_amount';rows.append(row);continue
        source=frame.copy()
        source['date']=pd.to_datetime(source.trade_date,errors='coerce').dt.strftime('%Y-%m-%d')
        if source.date.isna().any() or source.date.duplicated().any():
            raise ValueError('容量成交额日期无效或重复')
        raw=source.set_index('date').amount.reindex(expected)
        amounts=pd.to_numeric(raw,errors='coerce')
        if (raw.map(lambda x:isinstance(x,(bool,np.bool_))).any() or (raw.notna()&amounts.isna()).any()
                or np.isinf(amounts).any() or amounts.dropna().lt(0).any()):
            raise ValueError('容量成交额必须为非负有限金额')
        row['observed_sessions']=int(amounts.notna().sum())
        if len(expected)<window:
            row['status']='short_window'
        elif amounts.isna().any():
            row['status']='incomplete_window'
        else:
            mean=float(amounts.mean())
            if not math.isfinite(mean):
                raise ValueError('容量成交额超出数值范围')
            if mean>0 and mean*participation_rate==0:
                raise ValueError('容量参考额度超出数值范围')
            row.update(average_amount=mean,daily_budget=mean*participation_rate,
                status='available' if mean>0 else 'zero_liquidity')
            if mean>0:
                row.update(holding_to_daily_amount=position.market_value/mean,
                    estimated_sessions=position.market_value/(mean*participation_rate))
                if not all(math.isfinite(row[k]) for k in ('holding_to_daily_amount','estimated_sessions')):
                    raise ValueError('容量比例超出数值范围')
        rows.append(row)
    return pd.DataFrame(rows,columns=COLUMNS)
