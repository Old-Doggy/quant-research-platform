"""Select one durable run and inspect its saved charts without recomputing."""
import json
import math

import streamlit as st

from .research_charts import build_performance_chart, build_ic_chart, CHART_CONFIG
from .research_diagnostics import show_safe_error
from .result_history import result_projection, WORKSPACES
from .result_store import ResultStore
from .state_paths import state_root


def render_result_history(*, public_mode):
    if public_mode:
        st.caption('已保存研究结果在本地模式查看。')
        return
    try:
        store = ResultStore(state_root() / 'research_results')
        records = store.records()
    except Exception as exc:
        show_safe_error(exc, operation='archive')
        return
    if not records:
        st.info('还没有保存结果。在策略、组合或因子页运行研究后，会自动出现在这里。')
        return
    mode=st.segmented_control('实验视图',['单次结果','多次比较'],default='单次结果',key='result_history_mode')
    if mode=='多次比较':
        from .result_comparison_view import render_result_comparison
        render_result_comparison(store,records)
        return
    st.caption('保存结果 · 选择一次运行，查看当次曲线、指标与明细。')
    by_id = {r['task_id']: r for r in records}
    from datetime import datetime
    from zoneinfo import ZoneInfo
    def label(task_id):
        row = by_id[task_id]
        instant = datetime.fromisoformat(row['created_at']).astimezone(ZoneInfo('Asia/Shanghai'))
        return f"{WORKSPACES.get(row['workspace'], row['workspace'])} · {instant:%Y-%m-%d %H:%M:%S} · {task_id[:8]}"
    selected = st.selectbox('选择已保存研究', list(by_id), format_func=label,
        key='saved_result_selected', filter_mode=None)
    try:
        value = store.load(selected)
        projection = result_projection(value)
    except Exception as exc:
        show_safe_error(exc, operation='archive')
        st.caption('这条记录未通过读取检查，可选择其他记录。')
        return
    metrics = projection['metrics']
    origin = value.get('data_mode')
    if origin in ('seeded_demo', 'synthetic'):
        st.caption('合成示例 · 非真实证券数据')
    elif origin:
        st.caption({'local_market': '本地行情', 'file_import': '文件导入'}.get(origin, '本地研究数据'))
    labels = {'total_return': ('区间收益', True), 'max_drawdown': ('最大回撤', True),
        'sharpe': ('夏普比率', False), 'fills': ('成交笔数', False), 'trades': ('交易次数', False),
        '有效IC交易日': ('有效IC交易日', False)}
    available = [(k, v) for k, v in labels.items() if isinstance(metrics.get(k), (int, float))
        and math.isfinite(float(metrics[k]))][:4]
    if available:
        for column, (key, (name, percent)) in zip(st.columns(len(available)), available):
            column.metric(name, f'{metrics[key]:.2%}' if percent else
                (f'{metrics[key]:,.0f}' if key in ('trades', 'fills', '有效IC交易日') else f'{metrics[key]:,.2f}'))
    display = st.segmented_control('展示方式', ['图表', '表格'], default='图表',
        selection_mode='single', key='saved_result_display')
    curve, ic = projection['curve'], projection['ic']
    dated = curve if curve is not None else ic
    if dated is not None and not dated.empty:
        st.caption(f"{str(dated.trade_date.min())[:10]} — {str(dated.trade_date.max())[:10]} · {len(dated):,} 个交易日")
    if display == '图表':
        if curve is not None and not curve.empty:
            st.plotly_chart(build_performance_chart(curve, nav='nav',
                benchmark='benchmark_nav' if 'benchmark_nav' in curve else None,
                revision=selected), width='stretch', config=CHART_CONFIG, key='saved_result_curve')
        elif ic is not None and not ic.empty:
            st.plotly_chart(build_ic_chart(ic, revision=selected),
                width='stretch', config=CHART_CONFIG, key='saved_result_ic')
        else:
            st.caption('这次运行没有保存连续曲线，可在表格中查看已有明细。')
    tables = projection['tables']
    if display == '表格' or (curve is None and ic is None):
        if tables:
            name = st.selectbox('明细', list(tables), filter_mode=None, key='saved_result_table')
            frame = tables[name]
            st.dataframe(frame, hide_index=True, width='stretch')
            st.download_button('下载这张表', frame.to_csv(index=False).encode('utf-8-sig'),
                file_name='saved-result-table.csv', mime='text/csv', key='saved_result_csv')
        else:
            st.caption('这次运行未保存表格明细。')
    with st.expander('本次参数与运行记录'):
        st.json(projection['parameters'], expanded=False)
        if projection['manifest']:
            st.download_button('下载运行清单', json.dumps(projection['manifest'], ensure_ascii=False, indent=2),
                file_name='saved-run-manifest.json', mime='application/json', key='saved_result_manifest')
        st.caption('这里读取保存内容；重新计算需要原始输入和相同的数据、算法版本。')
        if value.get('replay'):
            if st.button('重新计算并核对', key='saved_result_replay'):
                try:
                    from .result_replay import replay_saved
                    with st.spinner('核对保存输入与计算结果…'):
                        report = replay_saved(store, selected)
                    if report['kind']=='factor_comparison':
                        st.success(f"{report['sessions']:,} 个交易日、{report['rows']:,} 条实际因子记录与相关性结果一致。")
                    elif report['kind'] == 'factor':
                        st.success(f"{report['sessions']:,} 个交易日、{report['rows']:,} 条截面记录一致；IC、分组收益与换手一致。")
                    else:
                        st.success(f"{report['sessions']:,} 个交易日逐点一致，指标与 {report['trade_events']:,} 条交易记录一致。")
                except Exception as exc:
                    show_safe_error(exc, operation='replay')
