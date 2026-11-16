"""Explicit factor job UI using the existing research service and audit gate."""
from __future__ import annotations
from portfolio_app.research_help import help_link

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .research_charts import build_turnover_chart, build_ic_chart, style_chart, CHART_CONFIG
from .factor_compute import BASIC_FACTOR_SPECS
from .factor_research_archive import save_factor_archive
from .factor_research_job import FactorResearchJobService
from .factor_workspace import FactorResearchConfig
from .research_audit_view import register_run, render_run_audit
from .research_jobs import JobStatus
from .research_manifest import semantic_hash
from .research_result_cache import build_data_fingerprint
from .research_task_view import background_task, previous_result_selected
from .research_display import envelope_sample, render_paged_table, check_research_size, prepared_download
from .ui_copy import format_count, format_percent, format_research_status


def factor_export_result(result):
    """Keep the legacy JSON ZIP contract free of internal replay arrays."""
    return {k: v for k, v in result.items() if k != 'replay'}


def _finite_numbers(values):
    output = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            output.append(number)
    return output


def _last_finite(rows, value_key):
    for row in reversed(rows):
        try:
            value = float(row.get(value_key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return None


def build_factor_research_summary(result):
    """Build the small, explanatory summary shown before factor detail tabs.

    This is a presentation projection only. It reads the existing result
    payload and never changes factor, label, grouping or return semantics.
    """
    result = result if isinstance(result, dict) else {}
    overview = result.get("overview") if isinstance(result.get("overview"), dict) else {}
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    integrity = result.get("integrity") if isinstance(result.get("integrity"), dict) else {}
    ic_rows = analysis.get("ic_series") if isinstance(analysis.get("ic_series"), list) else []
    ic_values = _finite_numbers(row.get("ic") for row in ic_rows if isinstance(row, dict))
    groups = analysis.get("group_returns") if isinstance(analysis.get("group_returns"), dict) else {}
    cumulative = groups.get("cumulative") if isinstance(groups.get("cumulative"), list) else []
    group_rows = [row for row in cumulative if isinstance(row, dict) and row.get("portfolio_type") != "long_short_daily_spread"]
    quantiles = _finite_numbers(row.get("factor_quantile") for row in group_rows)
    top_quantile = int(max(quantiles)) if quantiles else None
    bottom_quantile = int(min(quantiles)) if quantiles else None
    top_rows = [row for row in group_rows if row.get("factor_quantile") == top_quantile]
    bottom_rows = [row for row in group_rows if row.get("factor_quantile") == bottom_quantile]
    turnover = analysis.get("turnover") if isinstance(analysis.get("turnover"), dict) else {}
    turnover_rows = turnover.get("rows") if isinstance(turnover.get("rows"), list) else []
    turnover_values = _finite_numbers(row.get("turnover") for row in turnover_rows if isinstance(row, dict))
    coverage = turnover.get("coverage") if isinstance(turnover.get("coverage"), dict) else {}
    autocorrelation = turnover.get("rank_autocorrelation") if isinstance(turnover.get("rank_autocorrelation"), dict) else {}
    labels = integrity.get("labels") if isinstance(integrity.get("labels"), dict) else {}
    input_integrity = integrity.get("input") if isinstance(integrity.get("input"), dict) else {}

    return {
        "ic": {
            "valid_sessions": int(overview["valid_ic_sessions"]) if overview.get("valid_ic_sessions") is not None else len(ic_values),
            "mean": float(sum(ic_values) / len(ic_values)) if ic_values else None,
            "median": float(pd.Series(ic_values).median()) if ic_values else None,
            "std": float(pd.Series(ic_values).std(ddof=1)) if len(ic_values) >= 2 else None,
            "positive_ratio": float(sum(value > 0 for value in ic_values) / len(ic_values)) if ic_values else None,
        },
        "groups": {
            "top_quantile": top_quantile,
            "bottom_quantile": bottom_quantile,
            "top_cumulative": _last_finite(top_rows, "cumulative_return"),
            "bottom_cumulative": _last_finite(bottom_rows, "cumulative_return"),
            "spread_cumulative": _last_finite(
                [row for row in cumulative if isinstance(row, dict) and row.get("portfolio_type") == "long_short_daily_spread"],
                "cumulative_return",
            ),
        },
        "turnover": {
            "mean": float(sum(turnover_values) / len(turnover_values)) if turnover_values else None,
            "median": float(pd.Series(turnover_values).median()) if turnover_values else None,
            "coverage_ratio": float(coverage["coverage_ratio"]) if coverage.get("coverage_ratio") is not None else None,
            "rank_autocorrelation": float(autocorrelation["mean"]) if autocorrelation.get("mean") is not None else None,
            "valid_pairs": int(autocorrelation.get("valid_pairs") or 0),
        },
        "integrity": {
            "label_horizon": int(labels["horizon_sessions"]) if labels.get("horizon_sessions") is not None else None,
            "incomplete_tail": int(labels.get("incomplete_tail") or 0),
            "pit_status": str(input_integrity.get("status") or "UNKNOWN"),
        },
        "cost": {"status": "not_applied"},
    }


def _factor_metric(value, formatter):
    return formatter(value) if value is not None else "—"


def _render_factor_summary(result, *, show_details=True):
    summary = build_factor_research_summary(result)
    ic = summary["ic"]
    groups = summary["groups"]
    turnover = summary["turnover"]
    integrity = summary["integrity"]
    st.subheader('因子诊断概览')
    metric_row = st.columns(4)
    metric_row[0].metric('有效交易日', format_count(ic['valid_sessions']))
    metric_row[1].metric('IC 均值', _factor_metric(ic['mean'], lambda value: f'{value:.4f}'))
    metric_row[2].metric('IC 波动', _factor_metric(ic['std'], lambda value: f'{value:.4f}'))
    metric_row[3].metric('正 IC 占比', _factor_metric(ic['positive_ratio'], format_percent))
    if show_details:
        _render_factor_boundaries(result, summary)
    return summary


def render_factor_research(frame, *, public_mode):
    keys = ('factor_research_id', 'factor_research_horizon', 'factor_research_groups')
    for key, value in st.session_state.get('_factor_workspace_controls', {}).items():
        if key not in st.session_state:
            st.session_state[key] = value
    try:
        _render_factor_research(frame, public_mode=public_mode)
    finally:
        st.session_state['_factor_workspace_controls'] = {
            key: st.session_state[key] for key in keys if key in st.session_state}


def _render_factor_research(frame, *, public_mode):
    try:
        check_research_size(frame)
    except ValueError as exc:
        st.warning(str(exc))
        return
    st.html('''<style>
      [data-testid="stMainBlockContainer"] h1 {font-size:1.7rem;}
      [data-testid="stMainBlockContainer"] h3 {font-size:1.1rem;}
      @media(max-width:640px){[data-testid="stMainBlockContainer"]{padding:2.8rem .8rem 1rem;}}
    </style>''')
    st.title('因子研究')
    from .research_dataset import dataset_metadata, record_context
    metadata = dataset_metadata(frame)
    record_context(st.session_state, 'factors', frame)
    st.caption(f"{metadata['dataset_id']} / {metadata['version']} · {frame.symbol.nunique()} 个标的")
    settings_column, result_column = st.columns([1, 3.5], gap="large")
    with settings_column:
        st.subheader("研究设置")
        factor_labels = {
            'return_1d':'1日涨跌幅', 'return_5d':'5日涨跌幅', 'return_20d':'20日涨跌幅',
            'return_60d':'60日涨跌幅', 'reversal_5d':'5日反转',
            'realized_volatility_20d':'20日波动率', 'atr_ratio_14d':'14日振幅比例（ATR）',
            'ma_deviation_20d':'20日均线偏离', 'volume_ratio_20d':'20日量比',
            'price_volume_corr_20d':'20日量价相关性',
        }
        names = {spec.factor_id: factor_labels.get(spec.factor_id.removeprefix('basic.'), spec.name)
                 for spec in BASIC_FACTOR_SPECS}
        factor_id = st.selectbox('研究因子', list(names),
                                  format_func=lambda key: names[key],
                                  index=0,
                                  key='factor_research_id', filter_mode=None,
                                  help='检验这个指标能否区分后续涨跌。')
        horizon = st.selectbox('观察未来几天', [1, 5, 10, 20],
            index=1, key='factor_research_horizon',
            filter_mode=None, format_func=lambda value: f'{value} 个交易日',
            help='例如 5 天：比较今天的因子排名与未来 5 个交易日的收益排名。')
        with st.expander('高级设置'):
            quantiles = st.selectbox('分成几组比较', [2, 3],
                index=0, key='factor_research_groups',
                filter_mode=None, help='按因子从低到高分组，比较各组后续表现。')
        start = st.button('运行因子研究', type='primary', key='factor_research_run', width='stretch')
    result_area = result_column.container()
    config = FactorResearchConfig(factor_id=factor_id, dataset_id=metadata['dataset_id'],
        date_start=frame.trade_date.min().date().isoformat(), date_end=frame.trade_date.max().date().isoformat(),
        label_horizon_sessions=horizon, quantiles=quantiles, min_assets_per_date=2,
        max_missing_ratio=.6, disclosure_mode='public_demo' if public_mode else 'private_local')
    identity = semantic_hash({'config': config.to_dict(), 'data': build_data_fingerprint(frame)})
    if 'factor_research_service' not in st.session_state:
        st.session_state['factor_research_service'] = FactorResearchJobService(specs=BASIC_FACTOR_SPECS)
    service = st.session_state['factor_research_service']
    def compute(token):
        job = service.submit(frame, config, token=token)
        if job.status is not JobStatus.SUCCEEDED:
            raise ValueError(job.error or 'factor research blocked')
        result = dict(job.result)
        if not public_mode:
            from .result_replay import factor_replay_inputs
            result['replay'] = factor_replay_inputs(frame, config=config)
            result['data_mode'] = metadata['source_kind']
        return result
    task, computed = background_task(workspace='factors', identity=identity,
        compute=compute, start=start, public_mode=public_mode)
    with result_area:
        if task.get('status') == 'running':
            st.caption(format_research_status('running', phase=task.get('phase') or 'queued'))
        elif task.get('status') == 'succeeded':
            st.caption(format_research_status('succeeded', cache_hit=bool(task.get('cache_hit'))))
        elif task.get('status') == 'cancelled':
            st.info(format_research_status('cancelled'))
        elif task.get('status') == 'failed':
            st.error(format_research_status('failed', recoverable=bool(st.session_state.get('factor_research_current'))))
        if computed is not None:
            st.session_state['factor_research_current'] = (identity, computed)
        saved = st.session_state.get('factor_research_current')
        if not saved:
            st.info('选择因子，点击“运行因子研究”。')
            return
        if saved[0] != identity or task.get('status') in {'failed', 'cancelled'}:
            if saved[0] != identity:
                st.info('配置已改变，上次结果保留；重新运行后查看当前研究。')
            if not previous_result_selected(workspace='factors', marker=(identity, task.get('task_id')),
                                            available=True):
                return
        result = saved[1]
        st.caption(f"{result['config']['date_start']} — {result['config']['date_end']}")
        register_run(run_id=result['run_id'], label='因子研究', manifest=result['run_manifest'],
                     metrics={}, public_mode=public_mode)
        summary = _render_factor_summary(result, show_details=False)
        ic_tab, groups_tab, detail_tab = st.tabs(['IC 与稳定性', '分组表现', '样本与归档'])
        with ic_tab:
            ic = pd.DataFrame(result['analysis']['ic_series'])
            value = 'ic' if 'ic' in ic else 'value'
            if value in ic:
                fig = build_ic_chart(ic, value=value, revision=result['run_id'])
                st.plotly_chart(fig, width='stretch', config=CHART_CONFIG)
            turnover_rows = pd.DataFrame(result['analysis']['turnover']['rows'])
            if not turnover_rows.empty and 'turnover' in turnover_rows:
                st.subheader('高分组成员变化')
                turnover_fig = build_turnover_chart(turnover_rows, revision=result['run_id'])
                st.plotly_chart(turnover_fig, width='stretch', config=CHART_CONFIG)
                autocorrelation_text = _factor_metric(summary['turnover']['rank_autocorrelation'], lambda value: f'{value:.4f}')
                st.caption(f"平均退出 {summary['turnover']['mean']:.1%}" if summary['turnover']['mean'] is not None else '暂无有效换手样本')
                def _explain_240():
                    st.write('蓝线为20个有效交易日的滚动均值。点击图例中的“每日”可查看原始散点；悬停读取日期和值。成员变化表示前一日高分组成员的退出比例。')
                    st.caption(f"排名稳定性 {autocorrelation_text} · 有效配对 {summary['turnover']['valid_pairs']:,} 组")
                help_link('图表说明', _explain_240, key='factor_research_view_help_240')
            with st.expander('每日 IC 明细', expanded=False):
                render_paged_table(ic, key='factor_ic')
        with groups_tab:
            groups = pd.DataFrame(result['analysis']['group_returns']['cumulative'])
            if not groups.empty and {'factor_quantile', 'cumulative_return'}.issubset(groups.columns):
                group_figure = go.Figure()
                descriptive_groups = groups.loc[groups['portfolio_type'].ne('long_short_daily_spread')] if 'portfolio_type' in groups else groups
                group_colors = ['#A9B9CF', '#7C91AF', '#526C93', '#14949B', '#2864D7']
                for index, (quantile, group) in enumerate(descriptive_groups.groupby('factor_quantile', sort=True)):
                    group = envelope_sample(group, value='cumulative_return')
                    group_figure.add_trace(go.Scatter(x=group.trade_date, y=group.cumulative_return, name=f'第 {int(quantile)} 组', mode='lines', connectgaps=False,
                        line=dict(color='#2864D7' if index == descriptive_groups.factor_quantile.nunique()-1 else group_colors[index % len(group_colors)], width=2 if index in {0,4} else 1.6)))
                spread = groups[groups.get('portfolio_type', '') == 'long_short_daily_spread'] if 'portfolio_type' in groups else pd.DataFrame()
                if not spread.empty:
                    spread = envelope_sample(spread, value='cumulative_return')
                    group_figure.add_trace(go.Scatter(x=spread.trade_date, y=spread.cumulative_return, name='多空差', mode='lines', line={'dash': 'dot', 'color': '#8A6BC6', 'width': 2}, connectgaps=False))
                style_chart(group_figure, title='分组累计标签收益', height=390, revision=result['run_id'])
                group_figure.update_yaxes(tickformat='.0%', title_text='累计标签收益')
                group_figure.update_xaxes(tickformat='%Y-%m', hoverformat='%Y-%m-%d', nticks=6)
                group_figure.update_traces(hovertemplate='%{y:.2%}<extra>%{fullData.name}</extra>')
                st.plotly_chart(group_figure, width='stretch', config=CHART_CONFIG)
            st.caption('等权分组标签收益 · 未扣交易费用')
            with st.expander('分组数据明细'):
                render_paged_table(groups, key='factor_groups')
        with detail_tab:
            render_paged_table(pd.DataFrame(result['detail']), key='factor_detail')
            if not public_mode:
                archive = prepared_download(key='_factor_archive_bytes', identity=result['run_id'],
                    build=lambda: save_factor_archive(result['config'], factor_export_result(result)))
                st.download_button('下载本地因子归档', archive, 'factor-research-local.zip',
                                   mime='application/zip', key='factor_local_archive')

        if not public_mode:
            with st.expander('转为因子选股策略', expanded=False):
                st.caption('按因子分数选取排名靠前的标的。')
                left, right = st.columns(2)
                top_k = left.number_input('持有标的上限', 1, int(frame.symbol.nunique()),
                    min(3, int(frame.symbol.nunique())), 1, key='factor_draft_top_k')
                frequency = right.selectbox('调仓频率', ['daily', 'weekly', 'monthly'], index=1,
                    key='factor_draft_frequency', filter_mode=None,
                    format_func={'daily':'每日', 'weekly':'每周', 'monthly':'每月'}.get)
                eligible = saved[0] == identity and result['overview']['valid_ic_sessions'] > 0
                if st.button('创建策略草案并前往策略', disabled=not eligible, key='factor_to_strategy'):
                    st.session_state['_factor_strategy_draft'] = service.to_strategy_draft(result,
                        top_k=top_k, direction='long', rebalance_frequency=frequency)
                    st.session_state['_factor_strategy_frame'] = frame.copy(deep=True)
                    st.session_state['_open_factor_strategy'] = True
                    st.session_state['explicit_strategy_mode'] = '因子选股'
                    st.query_params['workspace'] = 'strategy'
                    st.rerun()
        def _explain_290():
            _render_factor_boundaries(result, summary)
            render_run_audit(result['run_manifest'], integrity=result['integrity']['input'],
                             public_mode=public_mode, key='factor_run_audit')
        help_link('数据与方法', _explain_290, key='factor_research_view_help_290')


def _render_factor_boundaries(result, summary):
    integrity = summary['integrity']
    turnover = summary['turnover']
    with st.expander('如何读这组结果 / How to read', expanded=False):
        st.markdown(
            '- **标签跨度**：按每个标的已有的交易会话计数，以观察日收盘价到第 h 个后续会话收盘价的变化构造未来收益，不是自然日；尾部不足 h 个会话时保持缺失。\n'
            '- **IC**：每个交易日横截面因子排序与未来标签排序的 Spearman 相关，均值和正值占比描述方向与稳定性。\n'
            '- **统计口径**：IC 波动使用有效观测的样本标准差（ddof=1）；正 IC 占比的分母是有效 IC 会话，零值不计入正值。\n'
            '- **分组累计**：同一观察日按因子分组后的等权标签收益累计；多空差是每日最高组减最低组后再连乘的研究序列。它没有模拟费用、拒单、现金、成交价或真实持仓。\n'
            '- **换手与稳定性**：换手用前一交易日最高组成员的退出比例计算；排名自相关描述全体共同标的的排序变化，仍不等于可交易性。'
        )
    integrity_status = integrity['pit_status']
    pit_label = '已检查声明时点' if integrity_status == 'DECLARED_TIMING_CHECKED' else '尚未完成真实 PIT 核验'
    st.info(
        f"样本 {format_count(result.get('overview', {}).get('rows'))} 行 · "
        f"标签跨度 {format_count(integrity['label_horizon'])} 个交易会话 · "
        f"标签尾部 {format_count(integrity['incomplete_tail'])} 行保留缺失 · "
        f"换手中位数 {_factor_metric(turnover['median'], format_percent)} · "
        f"覆盖率 {_factor_metric(turnover['coverage_ratio'], format_percent)} · "
        f"PIT：{pit_label}"
    )
    st.caption('成本影响：未应用成本模型 / Cost impact: no cost model applied。分组收益不含手续费、滑点、拒单和成交约束。')
    st.caption('覆盖率＝可分组的因子行数 ÷ 输入行数，包含尚未到期的标签行；不等于有效标签比例。累计指标取各序列最后一个非缺失观察值。')
