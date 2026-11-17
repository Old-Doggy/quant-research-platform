"""Daily turnover cost and its arithmetic accumulation, sharing full exports."""
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from .design_tokens import COLOR_TOKENS
from .research_charts import CHART_CONFIG,style_chart
from .research_display import envelope_sample,render_paged_table


def cost_series(performance):
    data=pd.DataFrame(performance.get('curve',[]))
    if data.empty:
        return data
    if not {'date','daily_cost','daily_return','nav'}<=set(data):
        raise ValueError('成本记录字段不完整')
    data=data[['date','daily_cost','daily_return','nav']].copy()
    data['date']=pd.to_datetime(data.date,errors='coerce')
    if data.date.isna().any() or data.date.duplicated().any():
        raise ValueError('成本日期缺失或重复')
    for field in ['daily_cost','daily_return','nav']:
        if data[field].map(lambda v:isinstance(v,(bool,np.bool_))).any():
            raise ValueError('成本或收益数值无效')
        data[field]=pd.to_numeric(data[field],errors='coerce')
        if not np.isfinite(data[field]).all():
            raise ValueError('成本或收益数值缺失或无效')
    if data.daily_cost.lt(0).any() or data.nav.le(0).any():
        raise ValueError('成本或净值范围无效')
    data=data.sort_values('date').reset_index(drop=True)
    data['cumulative_cost']=data.daily_cost.cumsum()
    total=performance.get('metrics',{}).get('total_cost')
    if total is not None and not math.isclose(float(total),float(data.daily_cost.sum()),rel_tol=1e-10,abs_tol=1e-12):
        raise ValueError('日成本合计与结果指标不一致')
    return data


def cost_table(data):
    table=data.copy()
    table['date']=table.date.dt.strftime('%Y-%m-%d')
    return table.rename(columns=dict(date='日期',daily_cost='日成本',daily_return='日收益',nav='净值',
        cumulative_cost='累计换手成本'))


def cost_chart(data,*,revision):
    shown=envelope_sample(data,value='cumulative_cost')
    monthly=len(data)>600
    bars=data.set_index('date').daily_cost.resample('MS').sum(min_count=1) if monthly else data.set_index('date').daily_cost
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.55,.45],vertical_spacing=.13)
    label='月度换手成本' if monthly else '每日换手成本'
    fig.add_trace(go.Bar(x=bars.index,y=bars.values,name=label,marker_color=COLOR_TOKENS['primary'],
        width=(20 if monthly else 2)*86400000,
        hovertemplate=label+' %{y:.3%}<extra></extra>'),row=1,col=1)
    fig.add_trace(go.Scatter(x=shown.date,y=shown.cumulative_cost,name='累计换手成本',mode='lines',
        line=dict(color=COLOR_TOKENS['research'],width=2,shape='hv'),connectgaps=False,
        hovertemplate='累计换手成本 %{y:.3%}<extra></extra>'),row=2,col=1)
    style_chart(fig,height=400,revision=revision)
    fig.data[1].update(xaxis='x')
    fig.update_layout(hoversubplots='axis',bargap=.2,margin=dict(l=18,r=80,t=52,b=38))
    fig.update_yaxes(tickformat='.2%',side='right',rangemode='tozero')
    fig.update_yaxes(title_text='月成本' if monthly else '日成本',row=1,col=1)
    fig.update_yaxes(title_text='累计成本',row=2,col=1)
    fig.update_xaxes(matches=None,anchor='y2',showticklabels=True,tickformat='%Y-%m',nticks=6,
        unifiedhovertitle=dict(text='%{x|%Y-%m-%d}'),row=1,col=1)
    fig.update_xaxes(matches='x',showticklabels=False,row=2,col=1)
    return fig


def render_strategy_costs(performance,*,revision):
    data=cost_series(performance)
    if data.empty:
        st.info('没有可核对的成本记录。')
        return
    display=st.segmented_control('成本展示',['图表','表格'],default='图表',required=True,key='strategy_cost_display')
    table=cost_table(data)
    if display=='图表':
        st.plotly_chart(cost_chart(data,revision=revision),width='stretch',config=CHART_CONFIG,key='strategy_cost_chart')
        if len(data)>600:
            st.caption('长区间按月汇总成本柱；每日记录保留在表格和下载中。')
    else:
        render_paged_table(table,key='strategy_costs')
    st.caption('日成本 = 持仓换手 × 设定费率；累计值为各日成本率相加。收益和净值已扣成本。')
    st.download_button('下载每日成本',table.to_csv(index=False).encode('utf-8-sig'),
        'strategy-costs.csv','text/csv',key='strategy_cost_csv')
