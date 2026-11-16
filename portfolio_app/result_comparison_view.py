"""Saved-run selection and honest period/basis comparison."""
import streamlit as st

from .result_comparison import compare_projections,comparison_curve
from .result_history import result_projection,WORKSPACES
from .research_charts import CHART_CONFIG
from .research_diagnostics import show_safe_error


def render_result_comparison(store,records):
    by_id={r['task_id']:r for r in records}
    label=lambda key:f"{WORKSPACES.get(by_id[key]['workspace'],by_id[key]['workspace'])} · {by_id[key]['created_at'][:19]} · {key[:8]}"
    selected=st.multiselect('选择比较结果（最多4项）',list(by_id),max_selections=4,
        format_func=label,key='result_compare_selection')
    if len(selected)<2:
        st.caption('选择2至4次有净值曲线的运行，按各自原始日期比较。')
        return
    try:
        projections={key:result_projection(store.load(key)) for key in selected}
        result=compare_projections(projections)
    except Exception as exc:
        show_safe_error(exc,operation='archive')
        st.caption('所选记录需要完整净值与回撤；因子IC记录请在因子页比较。')
        return
    result['curves']={label(key):curve for key,curve in result['curves'].items()}
    display=st.segmented_control('比较展示',['图表','表格'],default='图表',key='result_compare_display')
    if display=='图表':
        st.plotly_chart(comparison_curve(result),width='stretch',config=CHART_CONFIG,key='result_compare_curve')
    else:
        combined=[]
        for name,curve in result['curves'].items():
            combined.append(curve.assign(run=name))
        import pandas as pd
        st.dataframe(pd.concat(combined,ignore_index=True),hide_index=True,width='stretch')
    st.caption('各曲线保持原始日期和初始净值，未截成交集或重新归一。')
    if not result['same_dates']:
        st.caption('研究日期不同，区间指标分别列示，不计算相对排名。')
    if not result['same_basis']:
        st.caption('数据或计算口径不同或未完整记录，收益差不能单独归因于策略参数。')
    summary=result['summary'].copy()
    summary['run']=summary.run.map(label)
    st.dataframe(summary.rename(columns=dict(run='运行',start='起始',end='结束',sessions='交易日数',
        total_return='区间收益',max_drawdown='最大回撤',sharpe='夏普比率')),
        hide_index=True,width='stretch',column_config={'区间收益':st.column_config.NumberColumn(format='percent'),
            '最大回撤':st.column_config.NumberColumn(format='percent')})
    st.download_button('下载比较指标',summary.to_csv(index=False).encode('utf-8-sig'),
        'experiment-comparison.csv','text/csv',key='result_compare_csv')
    with st.expander('参数与数据版本差异'):
        st.json({key:dict(parameters=projections[key]['parameters'],manifest=projections[key]['manifest'])
            for key in selected},expanded=False)
