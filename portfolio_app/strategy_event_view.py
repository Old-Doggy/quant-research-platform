"""Exact execution-date markers on unit NAV, with linked immutable event rows."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from html import escape

from .design_tokens import COLOR_TOKENS
from .research_charts import CHART_CONFIG,style_chart
from .research_display import envelope_sample
from .stock_view import format_quote_price


def event_chart(performance,trades,*,revision):
    curve=pd.DataFrame(performance.get('curve',[]))
    fig=go.Figure()
    if curve.empty:
        return style_chart(fig,height=390,revision=revision)
    curve['date']=pd.to_datetime(curve['date'],errors='coerce')
    if curve.date.isna().any() or curve.date.duplicated().any():
        raise ValueError('净值日期无效或重复')
    curve=curve.sort_values('date');curve['nav']=pd.to_numeric(curve.nav,errors='coerce')
    shown=envelope_sample(curve,value='nav')
    fig.add_trace(go.Scatter(x=shown.date,y=shown.nav,name='策略净值',mode='lines',
        line=dict(color=COLOR_TOKENS['primary'],width=2),connectgaps=False,
        hovertemplate='策略净值 %{y:.4f}<extra></extra>'))
    nav=curve.set_index('date').nav
    groups=[('买入成交',COLOR_TOKENS['up'],'triangle-up'),
            ('卖出成交',COLOR_TOKENS['down'],'triangle-down'),
            ('未成交',COLOR_TOKENS['benchmark'],'x')]
    for label,color,shape in groups:
        dates=[];values=[];custom=[]
        for index,row in trades.iterrows():
            group=('买入成交' if row['方向']=='买入' else '卖出成交') if row['状态']=='已成交' else '未成交'
            date=pd.to_datetime(row['执行日期'],errors='coerce')
            value=nav.get(date)
            if group!=label or value is None or pd.isna(value):
                continue
            price=row.get('价格')
            custom.append([int(index),row['信号日期'],row['状态'],
                format_quote_price(price),row.get('原因',''),row['方向']])
            dates.append(date);values.append(value)
        if dates:
            fig.add_trace(go.Scatter(x=dates,y=values,name=label,mode='markers',customdata=custom,
                marker=dict(symbol=shape,color=color,size=12,line=dict(color='white',width=1)),
                selected=dict(marker=dict(opacity=1,size=14)),unselected=dict(marker=dict(opacity=.65)),
                hovertemplate='%{x|%Y-%m-%d} · %{customdata[5]}<br>信号日 %{customdata[1]}<br>'
                    '状态 %{customdata[2]}<br>执行价 %{customdata[3]}<br>净值 %{y:.4f}<br>'
                    '%{customdata[4]}<extra></extra>'))
    style_chart(fig,height=390,revision=revision)
    fig.update_layout(hovermode='closest',clickmode='event+select',margin=dict(l=18,r=64,t=55,b=40))
    fig.update_yaxes(title_text='净值',side='right',tickformat='.2f')
    fig.update_xaxes(tickformat='%Y-%m',hoverformat='%Y-%m-%d',nticks=6)
    return fig


def render_strategy_events(performance,trades,*,revision):
    if trades.empty:
        st.info('本次研究没有买卖事件。')
        return
    trades=trades.reset_index(drop=True)
    pick='strategy_event_pick'
    if st.session_state.get('_strategy_event_revision')!=revision:
        st.session_state['_strategy_event_revision']=revision
        st.session_state[pick]=0
        st.session_state['strategy_event_page']=0
    display=st.segmented_control('买卖展示',['图表','表格'],default='图表',required=True,key='strategy_event_display')
    if display=='图表':
        page=0;size=40
        if len(trades)>size:
            page=st.selectbox('事件图页码',list(range((len(trades)+size-1)//size)),filter_mode=None,
                format_func=lambda i:f'{i+1} / {(len(trades)+size-1)//size}',key='strategy_event_page')
        def choose_event():
            points=st.session_state.get('strategy_event_chart',{}).get('selection',{}).get('points',[])
            for point in points:
                custom=point.get('customdata')
                if isinstance(custom,(list,tuple)) and custom and type(custom[0]) is int and 0<=custom[0]<len(trades):
                    st.session_state[pick]=custom[0];break
        fig=event_chart(performance,trades.iloc[page*size:(page+1)*size],revision=f'{revision}-{page}')
        st.plotly_chart(fig,width='stretch',config=CHART_CONFIG,key='strategy_event_chart',
            on_select=choose_event,selection_mode='points')
        count=sum(len(t.x) for t in fig.data[1:])
        st.caption(f'本页 {count} 个事件有对应净值坐标；完整记录保留在表格与下载中。点击标记查看明细。')
    else:
        st.dataframe(trades,hide_index=True,width='stretch')
    index=st.selectbox('查看买卖事件',list(range(len(trades))),filter_mode=None,key=pick,
        format_func=lambda i:f"{i+1} · {trades.iloc[i]['执行日期']} · {trades.iloc[i]['方向']} · {trades.iloc[i]['状态']}")
    row = trades.iloc[index]
    fields = [(label, format_quote_price(value) if label == '价格' else '—' if pd.isna(value) else str(value))
              for label, value in row.items() if label != '原因']
    st.html('<dl class="quant-inline-details" aria-label="事件详情">' + ''.join(
        f'<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>' for label, value in fields
    ) + '</dl>')
    if pd.notna(row.get('原因')) and row.get('原因'):
        st.caption(str(row['原因']))
    st.download_button('下载买卖事件',trades.to_csv(index=False).encode('utf-8-sig'),
        'strategy-events.csv','text/csv',key='strategy_event_csv')
