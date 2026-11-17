"""Holdings versus trailing CNY turnover, with explicit unavailable rows."""
import plotly.graph_objects as go
import streamlit as st

from .portfolio_capacity import capacity_report
from .research_charts import style_chart,CHART_CONFIG
from .design_tokens import COLOR_TOKENS


STATUS={'available':'可计算','missing_input':'未保存输入','unknown_units':'金额单位未核验',
    'missing_amount':'缺成交额','short_window':'历史不足20日','incomplete_window':'窗口内缺成交额',
    'zero_liquidity':'窗口成交额为零'}
LABELS=dict(symbol='证券',market_value='持仓市值（元）',window_start='窗口起日',window_end='窗口止日',
    observed_sessions='有效日数',average_amount='前20日日均成交额（元）',daily_budget='每日参考额度（元）',
    holding_to_daily_amount='持仓/日均成交额',estimated_sessions='参考消化天数',status='状态')


def capacity_chart(report,*,revision):
    rows=report.loc[report.status.eq('available')].sort_values('estimated_sessions',ascending=False)
    fig=go.Figure(go.Bar(x=rows.estimated_sessions.tolist(),y=rows.symbol.tolist(),orientation='h',
        marker_color=COLOR_TOKENS['primary'],width=.45,text=['<0.01' if 0<v<.01 else f'{v:.2f}' for v in rows.estimated_sessions],
        textposition='outside',cliponaxis=False,
        customdata=rows[['market_value','average_amount','daily_budget','window_start','window_end']].values.tolist(),
        hovertemplate='%{y}<br>参考消化 %{x:.4g} 天<br>持仓 %{customdata[0]:,.2f} 元<br>日均成交额 %{customdata[1]:,.2f} 元<br>每日参考额度 %{customdata[2]:,.2f} 元<br>%{customdata[3]} → %{customdata[4]}<extra></extra>'))
    style_chart(fig,title='持仓与成交额容量',height=max(280,130+len(rows)*38),revision=revision)
    fig.update_layout(showlegend=False,hovermode='closest',margin=dict(l=15,r=65,t=60,b=40))
    fig.update_xaxes(title_text='参考消化天数',rangemode='tozero',showgrid=True,gridcolor='#E4EAF2')
    maximum=float(rows.estimated_sessions.max()) if len(rows) else 0.
    fig.update_xaxes(range=[0,maximum*1.18 if maximum>0 else .1])
    fig.update_yaxes(autorange=False,range=[max(1.2,len(rows)-.5),-.7],showgrid=False,type='category',dtick=1)
    return fig


def render_capacity(result,sources,*,date,revision):
    if sources is None:
        st.caption('此历史结果未保存成交额输入；新研究运行后可查看容量。')
        return
    positions=result.positions.loc[result.positions.trade_date.eq(date)]
    if positions.empty:
        st.caption('所选日期没有证券持仓。')
        return
    rate=st.selectbox('每日参考成交额占比',[.01,.05,.1],index=1,filter_mode=None,
        format_func=lambda v:f'{v:.0%}',key='portfolio_capacity_rate')
    try:
        report=capacity_report(positions,sources,sessions=result.inputs['sessions'],date=date,participation_rate=rate)
    except ValueError:
        st.error('成交额输入校验失败，请核对该次研究的数据版本。')
        return
    st.caption('使用所选日期之前20个研究交易日，不含当日；零成交额计入均值，缺值不补零。')
    display=st.segmented_control('容量展示',['图表','表格'],default='图表',required=True,key='portfolio_capacity_display')
    table=report.copy()
    table['status']=table.status.replace(STATUS)
    table=table.rename(columns=LABELS)
    available=report.status.eq('available')
    if display=='图表' and available.any():
        plotted=report.loc[available].sort_values('estimated_sessions',ascending=False)
        page=0
        if len(plotted)>10:
            count=(len(plotted)+9)//10
            if st.session_state.get('portfolio_capacity_page',0)>=count:
                st.session_state['portfolio_capacity_page']=0
            page=st.selectbox('容量图页码',list(range(count)),filter_mode=None,
                format_func=lambda p:f'{p+1} / {count}',key='portfolio_capacity_page')
        st.plotly_chart(capacity_chart(plotted.iloc[page*10:(page+1)*10],revision=f'{revision}-{rate}-{page}'),
            width='stretch',config=CHART_CONFIG,key='portfolio_capacity_chart')
    elif display=='表格':
        st.dataframe(table,hide_index=True,width='stretch')
    if not available.all():
        st.caption('未绘制：'+'；'.join(f'{r.symbol} · {STATUS[r.status]}' for r in report.loc[~available].itertuples()))
    st.caption('参考消化天数 = 持仓市值 ÷ 每日参考额度；仅衡量历史流动性，不估计冲击成本或承诺成交。')
    st.download_button('下载容量明细',table.to_csv(index=False).encode('utf-8-sig'),
        'portfolio-capacity.csv','text/csv',key='portfolio_capacity_csv')
