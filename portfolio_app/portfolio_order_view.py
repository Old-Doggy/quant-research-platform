"""Same-date simulated order quantities with exact cash and reason drilldown."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .research_charts import style_chart,CHART_CONFIG
from .design_tokens import COLOR_TOKENS


SIDES={'BUY':'买入','SELL':'卖出'}
STATUSES={'FILLED':'已成交','PARTIAL':'部分成交','PARTIALLY_FILLED':'部分成交','REJECTED':'未成交'}


def order_table(frame):
    data=frame.copy()
    data['side']=data.side.replace(SIDES);data['status']=data.status.replace(STATUSES)
    columns=dict(symbol='标的',side='方向',effective_date='执行日期',requested_quantity='申请股数',
        filled_quantity='成交股数',remaining_quantity='剩余股数',status='状态',reason='原因',
        price='执行参考价',cash_before='成交前现金',cash_after='成交后现金')
    return data[[c for c in columns if c in data]].rename(columns=columns)


def order_chart(frame):
    labels=[f'{i+1} · {r.symbol} · {SIDES.get(r.side,r.side)}' for i,r in frame.iterrows()]
    custom=[[int(i),r.symbol,r.side,r.status,'—' if pd.isna(r.reason) else r.reason] for i,r in frame.iterrows()]
    fig=go.Figure()
    for key,label,color in [('requested_quantity','申请',COLOR_TOKENS['divider']),('filled_quantity','成交',COLOR_TOKENS['primary'])]:
        fig.add_trace(go.Bar(x=frame[key].tolist(),y=labels,orientation='h',name=label,
            customdata=custom,marker_color=color,width=.3,
            selected=dict(marker=dict(opacity=1)),unselected=dict(marker=dict(opacity=.75)),
            text=[f'{v:,}' for v in frame[key]],textposition='outside',cliponaxis=False,
            hovertemplate='%{y}<br>'+label+' %{x:,.0f} 股<br>%{customdata[4]}<extra></extra>'))
    style_chart(fig,title='申请与成交数量',height=max(260,min(600,160+len(frame)*65)),revision='portfolio-orders')
    fig.update_layout(barmode='group',hovermode='closest',clickmode='event+select',
        margin=dict(l=15,r=64,t=90,b=40))
    fig.update_xaxes(title_text='股',rangemode='tozero',showgrid=True,gridcolor='#E4EAF2')
    fig.update_yaxes(type='category',autorange='reversed',showgrid=False)
    return fig


def render_orders(frame,*,revision):
    if frame.empty:
        st.caption('当日没有调仓订单。')
        return
    frame=frame.reset_index(drop=True)
    display=st.segmented_control('订单展示',['图表','表格'],default='图表',required=True,key='portfolio_order_display')
    pick_key='portfolio_order_pick'
    marker=(revision,len(frame))
    if st.session_state.get('_portfolio_order_marker')!=marker:
        st.session_state['_portfolio_order_marker']=marker
        st.session_state[pick_key]=0
        st.session_state['portfolio_order_page']=0
    if display=='图表':
        page_size=8
        pages=list(range((len(frame)+page_size-1)//page_size))
        page=0
        if len(pages)>1:
            page=st.selectbox('订单图页码',pages,filter_mode=None,
                format_func=lambda p:f'{p+1} / {len(pages)}',key='portfolio_order_page')
        def select_order():
            event=st.session_state.get('portfolio_orders_chart',{})
            for point in event.get('selection',{}).get('points',[]):
                custom=point.get('customdata')
                if isinstance(custom,(list,tuple)) and custom and type(custom[0]) is int and 0<=custom[0]<len(frame):
                    st.session_state[pick_key]=custom[0];break
        fig=order_chart(frame.iloc[page*page_size:(page+1)*page_size]);fig.update_layout(uirevision=f'{revision}-{page}')
        st.plotly_chart(fig,width='stretch',config=CHART_CONFIG,key='portfolio_orders_chart',
            on_select=select_order,selection_mode='points')
    else:
        st.dataframe(order_table(frame),hide_index=True,width='stretch')
    index=st.selectbox('查看订单',list(range(len(frame))),filter_mode=None,key=pick_key,
        format_func=lambda i:f"{i+1} · {frame.iloc[i]['symbol']} · {SIDES.get(frame.iloc[i]['side'],frame.iloc[i]['side'])}")
    row=frame.iloc[index];a,b,c=st.columns(3)
    a.metric('成交 / 申请',f"{row.filled_quantity:,} / {row.requested_quantity:,}")
    price=row.get('price')
    b.metric('执行参考价','—' if price is None or pd.isna(price) else f'{price:,.4f}')
    c.metric('剩余数量',f'{row.remaining_quantity:,}')
    reason=row.get('reason');reason='—' if reason is None or pd.isna(reason) else reason
    st.caption(f"{STATUSES.get(row.status,row.status)} · {reason}")
    if {'cash_before','cash_after'}<=set(row.index):
        st.caption(f'账户现金 {row.cash_before:,.2f} → {row.cash_after:,.2f} 元')
    st.download_button('下载当日订单',order_table(frame).to_csv(index=False).encode('utf-8-sig'),
        'portfolio-orders.csv','text/csv',key='portfolio_orders_csv')
