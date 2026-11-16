"""Opening-equity linking of daily accounting P&L components."""
import math

import numpy as np
import pandas as pd


COMPONENTS={'price':('price_pnl','价格变化'),'dividend':('dividend_pnl','现金分红（税前）'),
    'fees':('cost','交易费用'),'cash':('cash_pnl','现金收益'),
    'residual':('contribution_residual_pnl','未分解残差')}


def contribution_period(ledger,*,initial_cash,start,end):
    needed={'trade_date','nav',*(value[0] for value in COMPONENTS.values())}
    if not needed<=set(ledger) or ledger.empty or not math.isfinite(initial_cash) or initial_cash<=0:
        raise ValueError('贡献需要完整账本与正初始权益')
    data=ledger.copy()
    data['trade_date']=pd.to_datetime(data.trade_date,errors='raise')
    if data.trade_date.isna().any() or data.trade_date.duplicated().any() or not data.trade_date.is_monotonic_increasing:
        raise ValueError('贡献账本日期无效')
    if pd.Timestamp(start)>pd.Timestamp(end): raise ValueError('贡献期间倒置')
    values=data[[c[0] for c in COMPONENTS.values()]].copy()
    values['cost']=-values.cost
    expected=data.nav.diff();expected.iloc[0]=data.nav.iloc[0]-initial_cash
    if not np.isfinite(values.to_numpy(dtype=float)).all() or not np.isfinite(data.nav).all() or data.nav.le(0).any():
        raise ValueError('贡献账本数值无效')
    if not np.allclose(values.sum(axis=1),expected,rtol=1e-10,atol=1e-8):
        raise ValueError('贡献分项与权益变化不一致')
    mask=data.trade_date.between(pd.Timestamp(start),pd.Timestamp(end))
    if not mask.any(): raise ValueError('期间没有账本记录')
    first=int(np.flatnonzero(mask.to_numpy())[0])
    base=float(data.nav.iloc[first-1]) if first else float(initial_cash)
    total=float(data.loc[mask,'nav'].iloc[-1]/base-1)
    rows=[dict(kind=kind,label=label,pnl=float(values.loc[mask,field].sum()),
        contribution=float(values.loc[mask,field].sum()/base)) for kind,(field,label) in COMPONENTS.items()]
    return dict(components=pd.DataFrame(rows),total_return=total,base_equity=base,
        method='opening_equity_scaled_daily_pnl.v1',start=str(start),end=str(end),
        residual=float(sum(row['contribution'] for row in rows)-total))
