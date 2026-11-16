"""Lazy experiment scatter and durable task status without raw error messages."""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .experiment_catalog import experiment_points
from .research_charts import style_chart, CHART_CONFIG
from .research_diagnostics import show_safe_error
from .result_history import result_projection, WORKSPACES


def render_task_status(root):
    from .research_runtime import TaskJournal
    from .research_diagnostics import _safe_row, _MESSAGES
    path = Path(root)/'workbench_tasks'/'tasks.sqlite'
    if not path.exists():
        st.caption('还没有任务记录。')
        return
    try:
        records = TaskJournal(path).records(limit=100)
    except Exception as exc:
        show_safe_error(exc, operation='journal')
        return
    selection = st.segmented_control('任务范围', ['全部', '失败或中断'], default='失败或中断', key='experiment_task_scope')
    if selection == '失败或中断':
        records = [r for r in records if r['status'] in ('failed','interrupted')]
    if not records:
        st.caption('没有符合条件的任务记录。')
        return
    names = dict(succeeded='已完成', failed='失败', interrupted='已中断', cancelled='已取消', running='进行中')
    rows = []
    for record in records:
        failure = _safe_row(record['failure']) if record.get('failure') else None
        rows.append(dict(任务=record['task_id'],状态=names[record['status']],
            更新时间=pd.Timestamp(record['updated'], unit='s', tz='UTC').tz_convert('Asia/Shanghai').isoformat(),
            结果已保存=record['result_available'],
            原因=_MESSAGES[failure['code']][0] if failure else ('进程结束，未保存结果' if record['status']=='interrupted' else ''),
            建议=_MESSAGES[failure['code']][1] if failure else '',
            诊断编号=failure['error_id'] if failure else ''))
    table = pd.DataFrame(rows)
    st.dataframe(table, hide_index=True, width='stretch')
    st.download_button('下载任务记录', table.to_csv(index=False).encode('utf-8-sig'),
        'experiment-task-status.csv', 'text/csv', key='experiment_tasks_csv')
    st.caption('失败任务保留原记录；返回对应研究页检查参数后重新运行。')


def render_experiment_scatter(store, records):
    projections, unreadable = {}, []
    for record in records:
        try:
            projections[record['task_id']] = result_projection(store.load(record['task_id']))
        except Exception:
            unreadable.append(record['task_id'])
    points, omitted = experiment_points(projections)
    if unreadable or omitted:
        st.caption(f'未绘制 {len(unreadable)} 条无法读取、{len(omitted)} 条无有效净值的记录。')
    if points.empty:
        st.caption('当前记录没有可绘制的净值与回撤。')
        return
    by_id = {r['task_id']:r for r in records}
    points['workspace'] = points.task_id.map(lambda key:WORKSPACES.get(by_id[key]['workspace'],by_id[key]['workspace']))
    figure = go.Figure(go.Scatter(x=(-points.max_drawdown).tolist(),y=points.total_return.tolist(),mode='markers',
        customdata=points[['task_id','workspace','start','end','sessions']].values.tolist(),
        marker=dict(color='#2864D7',size=11,opacity=.7,line=dict(color='white',width=1)),
        hovertemplate='%{customdata[1]} · %{customdata[0]}<br>%{customdata[2]} — %{customdata[3]}<br>区间收益 %{y:.2%}<br>最大回撤幅度 %{x:.2%}<extra></extra>'))
    style_chart(figure,title='已保存研究 · 收益与回撤',height=390)
    figure.update_xaxes(title_text='最大回撤幅度',tickformat='.1%',rangemode='tozero')
    figure.update_yaxes(title_text='各自区间收益',tickformat='.1%')
    figure.update_layout(clickmode='event+select')
    def select_run():
        selected=st.session_state.get('experiment_scatter',{}).get('selection',{}).get('points',[])
        if selected:
            identity=selected[0].get('customdata',[None])[0]
            if identity in by_id:
                st.session_state['saved_result_selected']=identity
                st.session_state['result_history_mode']='单次结果'
    st.plotly_chart(figure,width='stretch',config=CHART_CONFIG,key='experiment_scatter',
        on_select=select_run,selection_mode='points')
    st.caption('点击一个点打开原结果。各点保留原研究期间与口径，详细差异可在多次比较中核对。')
    with st.expander('散点数据'):
        st.dataframe(points,hide_index=True,width='stretch')
        st.download_button('下载散点数据',points.to_csv(index=False).encode('utf-8-sig'),
            'experiment-risk-return.csv','text/csv',key='experiment_scatter_csv')
