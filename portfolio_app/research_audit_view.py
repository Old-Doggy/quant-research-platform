"""Small local audit and comparison views, with no private public projection."""
from __future__ import annotations

import copy
import json
import math

import pandas as pd
import streamlit as st

from .research_manifest import compare_run_manifests, export_run_manifest, valid_manifest
from .research_charts import build_comparison_chart, CHART_CONFIG


_COMPARISON_METRICS = (
    ("total_return", "区间收益"),
    ("max_drawdown", "最大回撤"),
    ("total_cost", "累计费用"),
    ("trades", "交易次数"),
    ("turnover", "区间换手"),
    ("sharpe", "夏普"),
)

_COMPARISON_FIELD_LABELS = {
    'data': '输入数据', 'period': '评估期间', 'cost': '成本', 'engine': '计算引擎',
    'runtime': '运行环境', 'label': '标签', 'execution': '执行规则',
    'processing': '数据处理', 'evaluation': '评估方式', 'universe': '标的集合',
    'manifest': '清单有效性',
}


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def build_run_comparison_rows(records, selected):
    """Build an ordered, first-run-baseline comparison projection.

    This is presentation data only. It never ranks runs and leaves a metric
    unknown when either side does not provide a finite numeric value.
    """
    if not selected:
        return []
    baseline = records[selected[0]].get("metrics", {})
    rows = []
    for index, run_id in enumerate(selected):
        record = records[run_id]
        metrics = record.get("metrics", {})
        row = {"运行": run_id, "研究": record.get("label", "未命名"), "基准": "是" if index == 0 else "否"}
        for key, label in _COMPARISON_METRICS:
            value = metrics.get(key)
            row[label] = float(value) if _finite_number(value) else None
            if index == 0:
                row[f"{label}变化"] = None
            else:
                base = baseline.get(key)
                row[f"{label}变化"] = (float(value) - float(base)
                    if _finite_number(value) and _finite_number(base) else None)
        rows.append(row)
    return rows


def build_run_comparison_differences(records, selected):
    """Return readable comparison differences without exposing fingerprints."""
    if len(selected) < 2:
        return []
    manifests = [records[key].get('manifest', {}) for key in selected]
    comparison = compare_run_manifests(manifests)
    differences = []
    for item in comparison['differences']:
        differences.append({
            '差异项': _COMPARISON_FIELD_LABELS.get(item['field'], item['field']),
            '说明': item['reason'],
            '状态': '不可直接比较',
        })
    return differences


def register_run(*, run_id, label, manifest, metrics, public_mode):
    if public_mode or not valid_manifest(manifest):
        return
    records = dict(st.session_state.get('research_manifest_records', {}))
    records[str(run_id)] = dict(label=label, manifest=copy.deepcopy(manifest),
        metrics={key: float(value) for key, value in metrics.items()
                 if key in {'total_return', 'max_drawdown', 'sharpe', 'total_cost',
                            'trades', 'turnover'}
                 and _finite_number(value)})
    # This is a session inspection tray, not persistent storage or a cache.
    st.session_state['research_manifest_records'] = dict(list(records.items())[-50:])


def render_run_audit(manifest, *, integrity, public_mode, key='run_audit'):
    if public_mode:
        st.caption('运行清单仅供本地核验；公开摘要不包含私有数据、参数或指纹。')
        return
    with st.expander('运行清单与信息时点'):
        if integrity.get('status') != 'DECLARED_TIMING_CHECKED':
            st.warning('信息时点未核验：输入缺少完整的历史可用时点；数值可复现不等于通过真实市场 PIT。')
        else:
            st.info('已检查所声明的可用时点；未声明字段与原始来源仍需复核。')
        for limitation in integrity.get('limitations', []):
            st.caption(limitation)
        local = export_run_manifest(manifest, mode='private_local', local_access=True)
        st.caption('清单记录 Python、依赖版本、输入与计算定义指纹；不保存原始私有参数。')
        st.json(local, expanded=False)
        st.download_button('下载本地运行清单', json.dumps(local, ensure_ascii=False, indent=2),
                           'run-manifest-local.json', mime='application/json', key=key + '_download')


def render_run_comparison(*, public_mode):
    st.subheader('运行口径核对')
    if public_mode:
        st.info('完整研究清单只在本地可比较；脱敏摘要不能用来直接排名。')
        return
    from .research_task_view import session_runner
    journal = session_runner(public_mode=False).journal
    with st.expander('任务记录与中断恢复'):
        st.caption('重启后仅恢复任务状态，不自动加载计算对象。中断任务请重新显式运行；已下载归档保留完整结果。')
        try:
            history = journal.records() if journal else []
        except Exception as exc:
            from .research_diagnostics import show_safe_error
            show_safe_error(exc, operation='journal')
            history = []
        if history:
            st.dataframe(pd.DataFrame(history).drop(columns=['key_id']), hide_index=True, width='stretch')
        else:
            st.caption('尚无本地任务记录。')
    records = st.session_state.get('research_manifest_records', {})
    st.caption('当前会话的已运行结果；刷新不保证保留，请先下载。核对不重新运行研究。')
    if not records:
        st.info('先在策略或组合页运行研究，再到这里核对。')
    selected = st.multiselect('选择研究记录', list(records), default=list(records)[-4:],
        format_func=lambda value: f"{records[value]['label']} · {value}", key='audit_selected_runs', filter_mode=None)
    if not selected:
        return
    comparison = compare_run_manifests([records[key]['manifest'] for key in selected])
    if comparison['ranking_allowed']:
        st.success('所选记录的比较口径一致；可进一步评估结果，系统不自动择优。')
    else:
        st.warning('口径不一致：禁止直接排名。以下保留输入顺序，并排查看差异。')
        st.dataframe(pd.DataFrame(build_run_comparison_differences(records, selected)),
                     hide_index=True, width='stretch')
    rows = []
    for key in selected:
        item = records[key]
        m = item['manifest']
        rows.append({'记录': key, '研究': item['label'], **item['metrics'],
            '评估期间': json.dumps(m['basis']['period'], ensure_ascii=False),
            **{f'{field} 指纹': m['basis'][field][:12] for field in ('data', 'cost', 'engine', 'label', 'execution')}})
    with st.expander('运行清单、期间与指纹明细', expanded=False):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    st.subheader('指标变化（以第一条记录为基准）')
    st.caption('缺失指标显示为未知，不参与自动排名；变化值只用于核对所选运行之间的差异。')
    metric_rows = pd.DataFrame(build_run_comparison_rows(records, selected))
    values_tab, changes_tab = st.tabs(['指标数值', '相对基准变化'])
    identity = ['运行', '研究', '基准']
    with values_tab:
        for key, label in [('total_return','区间收益'), ('max_drawdown','最大回撤')]:
            values = metric_rows[label]
            if values.notna().any():
                st.plotly_chart(build_comparison_chart(
                    [f"{i+1} · {records[k]['label']}" for i,k in enumerate(selected)],
                    [(label, values)], title=label), width='stretch', config=CHART_CONFIG,
                    key=f'run_compare_{key}')
        st.dataframe(metric_rows[[*identity, *[label for _, label in _COMPARISON_METRICS]]],
            hide_index=True, width='stretch')
    with changes_tab:
        st.dataframe(metric_rows[[*identity, *[f'{label}变化' for _, label in _COMPARISON_METRICS]]],
            hide_index=True, width='stretch')
