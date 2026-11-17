"""Session-accurate validation timeline and bounded parameter-cell drilldown."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .research_charts import style_chart,CHART_CONFIG


LABELS={'train':'历史上下文','validation':'验证段','test':'锁定测试段','purge':'边界剔除',
    'embargo':'隔离区','tail':'标签未成熟'}
COLORS={'train':'#91A8C9','validation':'#0D858D','test':'#2864D7','purge':'#D1D9E5',
    'embargo':'#AFB9CC','tail':'#E5EAF1'}


def validation_segments(sessions,split):
    dates=pd.DatetimeIndex(sessions)
    if dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError('验证时间线需要有序且唯一的日期')
    horizon=split['horizon_sessions'];n=len(dates)
    if type(horizon) is not int or horizon<1 or not split.get('test_locked'):
        raise ValueError('验证区间缺少有效隔离长度或测试锁定')
    labels=['']*n
    for name in ('train','validation','test'):
        indices=split[name]
        if (not indices or any(type(i) is not int or not 0<=i<n for i in indices)
                or indices!=list(range(indices[0],indices[-1]+1))):
            raise ValueError('验证区间必须连续且有效')
        for i in indices:
            if labels[i]: raise ValueError('验证区间重叠')
            labels[i]=name
    first=split['train'][-1]+1;second=split['validation'][-1]+1
    if (split['train'][0]!=0 or split['validation'][0]!=first+2*horizon
            or split['test'][0]!=second+2*horizon or split['test'][-1]!=n-horizon-1):
        raise ValueError('验证区间与边界隔离不符')
    for offset in (first,second):
        for i in range(offset,offset+horizon): labels[i]='purge'
        for i in range(offset+horizon,offset+2*horizon): labels[i]='embargo'
    for i in range(n-horizon,n): labels[i]='tail'
    rows=[];start=0
    for end in range(1,n+1):
        if end==n or labels[end]!=labels[start]:
            kind=labels[start]
            rows.append(dict(kind=kind,label=LABELS[kind],start=dates[start].date().isoformat(),
                end=dates[end-1].date().isoformat(),sessions=end-start,offset=start))
            start=end
    return pd.DataFrame(rows)


def timeline_chart(segments):
    fig=go.Figure();shown=set()
    for row in segments.itertuples():
        fig.add_trace(go.Bar(x=[row.sessions],y=['研究区间'],base=[row.offset],orientation='h',
            name=row.label,legendgroup=row.kind,showlegend=row.kind not in shown,
            marker_color=COLORS[row.kind],width=.45,
            customdata=[[row.start,row.end,row.sessions]],
            hovertemplate=row.label+'<br>%{customdata[0]} → %{customdata[1]}<br>%{customdata[2]} 个交易日<extra></extra>'))
        shown.add(row.kind)
    style_chart(fig,height=200,revision='validation-timeline-'+segments.iloc[0].start)
    fig.update_layout(barmode='overlay',hovermode='closest',margin=dict(l=16,r=25,t=62,b=40),
        legend=dict(font=dict(size=13),y=1.12))
    scored=segments.loc[segments.kind.isin(['train','validation','test','tail'])]
    fig.update_xaxes(title_text='实际交易日顺序',tickmode='array',tickvals=scored.offset.tolist(),
        ticktext=scored.start.tolist(),range=[-4,int(segments.sessions.sum())+4],
        ticklabeloverflow='allow',showspikes=False)
    fig.update_yaxes(visible=False)
    return fig


def render_timeline(report):
    sessions=report.get('sessions')
    if not sessions:
        st.caption('此历史验证结果未保存完整切分日期。')
        return
    segments=validation_segments(sessions,report['split'])
    st.plotly_chart(timeline_chart(segments),width='stretch',config=CHART_CONFIG,key='validation_timeline')
    st.caption('历史上下文用于指标预热；验证段检查参数与成本，测试段使用预先固定的参数。')
    with st.expander('区间日期与交易日数'):
        table=segments[['label','start','end','sessions']].rename(columns=dict(label='区间',start='开始',end='结束',sessions='交易日数'))
        st.dataframe(table,hide_index=True,width='stretch')
        st.download_button('下载验证区间',table.to_csv(index=False).encode('utf-8-sig'),
            'validation-periods.csv','text/csv',key='validation_periods_csv')


def render_parameter_selection(frame,chart_builder):
    parameters=list(dict.fromkeys(frame['参数']));costs=sorted(frame['额外滑点bp'].unique().tolist())
    for key,options in [('validation_parameter',parameters),('validation_extra_bps',costs)]:
        if st.session_state.get(key) not in options: st.session_state[key]=options[0]
    fig=chart_builder(frame,'sensitivity')
    def select_cell():
        event=st.session_state.get('validation_parameter_heatmap',{})
        for point in event.get('selection',{}).get('points',[]):
            custom=point.get('customdata')
            if isinstance(custom,(list,tuple)) and len(custom)>=2 and custom[0] in parameters and custom[1] in costs:
                st.session_state['validation_parameter']=custom[0]
                st.session_state['validation_extra_bps']=custom[1]
                break
    st.plotly_chart(fig,width='stretch',config=CHART_CONFIG,key='validation_parameter_heatmap',
        on_select=select_cell,selection_mode='points')
    left,right=st.columns([2,1])
    def label(value):
        return value.replace('fast=','快线 ').replace(',slow=',' / 慢线 ').replace('lookback=','回看期 ').replace('momentum=','动量期 ')
    parameter=left.selectbox('查看参数',parameters,format_func=label,key='validation_parameter',filter_mode=None)
    cost=right.selectbox('额外滑点（bp）',costs,key='validation_extra_bps',filter_mode=None)
    row=frame.loc[frame['参数'].eq(parameter)&frame['额外滑点bp'].eq(cost)]
    if len(row)!=1: raise ValueError('参数结果不唯一')
    row=row.iloc[0];a,b=st.columns(2)
    a.metric('验证段收益',f"{row['区间收益']:.2%}")
    b.metric('验证段最大回撤',f"{row['最大回撤']:.2%}")
    st.caption(f'{len(frame)} 个预设组合 · 点击热图定位，不自动挑选参数。')
