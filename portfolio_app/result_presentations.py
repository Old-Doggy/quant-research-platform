"""Chart-first views with the original numeric records one click away."""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from .research_charts import style_chart, build_comparison_chart, CHART_CONFIG
from .stock_view import build_stock_quote_table, quote_previous_closes
from .design_tokens import COLOR_TOKENS
from .stock_view import price_precision as quote_precision


def display_mode(key):
    return st.segmented_control('展示方式', ['chart', 'table'],
        format_func=lambda x: {'chart':'图形', 'table':'表格'}[x],
        default='chart', required=True, key=key)


def build_quote_chart(frame, *, activity='vol', limit=12):
    data = frame.sort_values('trade_date').copy()
    previous = quote_previous_closes(data)
    change = data.close / previous - 1
    data = data.tail(limit)
    change = change.loc[data.index]
    dates = pd.to_datetime(data.trade_date).dt.strftime('%Y-%m-%d')
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.19, row_heights=[.66,.34])
    custom = data[['open','high','low','close']].to_numpy()
    colors = [COLOR_TOKENS['up' if v > 0 else 'down' if v < 0 else 'benchmark'] for v in change]
    precision = quote_precision(frame.low.min())
    labels = {len(change)-1}
    if change.notna().any():
        positional = change.reset_index(drop=True)
        labels.update({positional.idxmin(), positional.idxmax()})
    fig.add_trace(go.Scatter(x=dates, y=change, name='周期涨跌幅', mode='markers+text',
        marker=dict(color=colors,size=9,line=dict(color='#fff',width=1.5)),
        text=[f'{v:+.2%}' if i in labels and pd.notna(v) else '' for i,v in enumerate(change)],
        textposition=['top center' if v >= 0 else 'bottom center' for v in change],
        textfont=dict(size=14,color=colors),cliponaxis=False,customdata=custom,
        hovertemplate='涨跌幅 %{y:+.2%}<br>' + ' · '.join(
            f'{label} %{{customdata[{i}]:.{precision}f}}' for i, label in enumerate(('开', '高', '低', '收'))
        ) + '<extra></extra>'),row=1,col=1)
    for date, value, color in zip(dates, change, colors):
        if pd.notna(value):
            fig.add_shape(type='line',x0=date,x1=date,y0=0,y1=value,
                line=dict(color=color,width=2),layer='below',row=1,col=1)
    activity_label = {'vol':'成交量', 'amount':'成交额', 'turnover_rate':'换手率'}[activity]
    if activity in data:
        values=pd.to_numeric(data[activity],errors='coerce')
        fig.add_trace(go.Bar(x=dates, y=values, width=.28,
            name=activity_label, marker=dict(color=['#A4BCDE']*(len(data)-1)+['#447ACB'],cornerradius=3),
            hovertemplate=activity_label+' %{y:,.2f}'+('%' if activity=='turnover_rate' else '（源单位）')+'<extra></extra>'),row=2,col=1)
    style_chart(fig,title='近期交易概览',height=430,revision='quotes-'+activity)
    fig.update_layout(showlegend=False,margin=dict(l=24,r=76,t=86,b=40),
        title=dict(font=dict(size=18)),hoversubplots='axis')
    extent=max(float(change.abs().max()) if change.notna().any() else 0,.001)*1.65
    fig.update_xaxes(type='category',tickangle=0,nticks=6,
        tickvals=dates.iloc[::2],ticktext=pd.to_datetime(data.trade_date).dt.strftime('%m-%d').iloc[::2])
    fig.update_yaxes(tickformat='+.1%',range=[-extent,extent],row=1,col=1,
        title_text='',side='right',zeroline=True,zerolinecolor='#A4B5CE',zerolinewidth=1,
        gridcolor='#EFF3F8',nticks=4)
    fig.update_yaxes(title_text='',side='right',rangemode='tozero',nticks=3,gridcolor='#EFF3F8',row=2,col=1)
    for text,y in [('周期涨跌幅',1.08),(activity_label+('（%）' if activity=='turnover_rate' else ' · 源单位'),.30)]:
        fig.add_annotation(text=text,x=0,y=y,xref='paper',yref='paper',showarrow=False,
            xanchor='left',font=dict(size=14,color='#52637B'))
    if len(fig.data)>1:
        fig.data[1].update(xaxis='x')
    fig.update_xaxes(matches=None,anchor='y2',showticklabels=True,row=1,col=1)
    fig.update_xaxes(matches='x',showticklabels=False,row=2,col=1)
    return fig


def render_recent_quotes(frame, *, key, table=None, price_precision=None):
    if display_mode(key) == 'table':
        config = {name: st.column_config.NumberColumn(format=f'%.{price_precision}f')
                  for name in ('开盘', '最高', '最低', '收盘')} if price_precision is not None else None
        st.dataframe(build_stock_quote_table(frame) if table is None else table, width='stretch',
                     hide_index=True, column_config=config)
        return
    options=[col for col in ['vol','amount','turnover_rate'] if col in frame and frame[col].notna().any()]
    if not options:
        options=['vol']
    activity=st.segmented_control('活跃度指标',options,format_func=lambda x:{'vol':'成交量','amount':'成交额','turnover_rate':'换手率'}[x],
        default=options[0],required=True,key=key+'_activity')
    st.plotly_chart(build_quote_chart(frame,activity=activity),width='stretch',config=CHART_CONFIG)


def validation_table(frame):
    data=frame.rename(columns={'window':'窗口','start':'开始日期','end':'结束日期','observations':'交易日',
        'total_return':'区间收益','max_drawdown':'最大回撤','control':'对照方案','scope':'评分区间','额外滑点bp':'额外滑点（bp）'}).copy()
    for col in ['评分区间','对照方案','参数']:
        if col in data:
            data[col]=data[col].replace({'validation_only':'验证段','all_cash':'全现金','lagged_signal_5':'信号延迟 5 日'},regex=False)
            if col=='参数':
                data[col]=data[col].str.replace('fast=','快线 ',regex=False).str.replace(',slow=',' / 慢线 ',regex=False).str.replace('lookback=','回看期 ',regex=False).str.replace('momentum=','动量期 ',regex=False)
    return data


def build_validation_chart(frame, kind):
    data=validation_table(frame)
    if kind=='sensitivity':
        pivot=data.pivot(index='参数',columns='额外滑点（bp）',values='区间收益')
        fig=go.Figure(go.Heatmap(x=[f'+{n} bp' for n in pivot.columns],y=pivot.index,z=pivot.to_numpy(),
            text=pivot.map(lambda v:f'{v:.2%}').to_numpy(),texttemplate='%{text}',textfont=dict(size=16),
            colorscale=[[0,'#E9F0FB'],[1,'#2864D7']],showscale=False,xgap=5,ygap=5,
            hovertemplate='%{y}<br>额外滑点 %{x}<br>区间收益 %{z:.2%}<extra></extra>'))
        # Scatter cells receive point-selection events; Heatmap alone cannot emit them.
        fig.add_trace(go.Scatter(x=[f'+{value} bp' for value in data['额外滑点（bp）']],y=data['参数'],mode='markers',
            marker=dict(size=36,opacity=0),showlegend=False,
            customdata=frame[['参数','额外滑点bp','区间收益']].values.tolist(),
            hovertemplate='%{y}<br>额外滑点 %{x}<br>区间收益 %{customdata[2]:.2%}<extra></extra>'))
        style_chart(fig,title='参数与交易成本敏感性',height=340)
        fig.update_layout(hovermode='closest',clickmode='event+select');fig.update_xaxes(side='top',showspikes=False)
        fig.update_yaxes(autorange='reversed',showgrid=False,dtick=1)
        return fig
    labels=([f"窗口 {r['窗口']} · {r['开始日期']} → {r['结束日期']}" for _,r in data.iterrows()]
        if kind=='oos' else data['对照方案'].tolist())
    series=[('区间收益',data['区间收益'].tolist())]
    if '最大回撤' in data: series.append(('最大回撤',data['最大回撤'].tolist()))
    return build_comparison_chart(labels,series,title='测试窗口表现' if kind=='oos' else '验证段负对照')


def render_validation_results(report):
    from .research_help import help_link
    from .validation_view import render_timeline,render_parameter_selection
    render_timeline(report)
    def explain():
        st.write(f"{report['attempts']} 次预设诊断；purge / embargo 各 {report['split']['horizon_sessions']} 个会话。")
        for text in report['limitations']:st.write(text)
    help_link('验证方法',explain,key='locked_validation_method')
    tabs=st.tabs(['测试窗口','参数与成本','负对照'],key='locked_validation_tab',on_change='rerun')
    for tab,kind,field in zip(tabs,['oos','sensitivity','controls'],['rolling_oos','validation_sensitivity','negative_controls']):
        if not tab.open: continue
        with tab:
            frame=report[field]
            if frame.empty:
                st.info('当前区间暂无结果。');continue
            if display_mode('locked_view_'+kind)=='chart':
                if kind=='sensitivity': render_parameter_selection(frame,build_validation_chart)
                else: st.plotly_chart(build_validation_chart(frame,kind),width='stretch',config=CHART_CONFIG)
            else:
                st.dataframe(validation_table(frame),hide_index=True,width='stretch',column_config={
                    col:st.column_config.NumberColumn(format='percent') for col in ['区间收益','最大回撤']})
            if kind=='oos':st.caption('每个窗口独立从空仓开始，展示该窗口收益与最大回撤。')
