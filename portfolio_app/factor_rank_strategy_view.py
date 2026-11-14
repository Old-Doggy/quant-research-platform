"""Review a factor draft and run it through the existing offline ledger."""
from __future__ import annotations
from portfolio_app.research_help import help_link

import json

import pandas as pd
import streamlit as st

from .factor_rank_strategy import run_factor_strategy
from .offline_execution import ExecutionSpec
from .portfolio_archive import create_portfolio_archive
from .research_audit_view import register_run
from .research_dataset import record_context
from .research_run_adapter import sync_draft
from .research_run_state import RunStatus
from .research_task_view import background_run, previous_run_view
from .research_charts import build_performance_chart, build_time_series_chart, CHART_CONFIG


def render_factor_strategy(*, context_id, public_mode, settings_column=None, result_column=None):
    draft = st.session_state.get('_factor_strategy_draft')
    frame = st.session_state.get('_factor_strategy_frame')
    if public_mode or draft is None or frame is None:
        st.info('请先在因子工作区完成研究，再创建策略草案。')
        return
    record_context(st.session_state, 'strategy', frame)
    st.session_state['_actual_context_strategy']['dataset_id'] = draft['source']['dataset_id']
    source, selection = draft['source'], draft['selection']
    with result_column if result_column is not None else st.container():
        st.subheader('因子选股草案')
        st.caption(f"来源：{source['factor_run_id']} · {source['factor_id']} · {source['dataset_id']} · "
            f"前 {selection['top_k']} 名 · {selection['rebalance_frequency']} 调仓 · 仅做多")
        def _explain_33():
            st.write('按因子排名选股，下一交易日执行。历史数据可用时点尚未核验。')
        help_link('数据与方法', _explain_33, key='factor_rank_strategy_view_help_33')
    saved_controls = st.session_state.get('_factor_strategy_controls', {})
    for key, value in saved_controls.items():
        if key not in st.session_state:
            st.session_state[key] = value
    with settings_column if settings_column is not None else st.container():
        with st.form('factor_strategy_execution'):
            left, middle, right = [st.container() for _ in range(3)]
            cost = left.number_input('单边费用（基点）', 0., 200., None if 'factor_strategy_cost' in st.session_state else 10., 5., key='factor_strategy_cost')
            slip = middle.number_input('滑点（基点）', 0., 100., None if 'factor_strategy_slip' in st.session_state else 0., 1., key='factor_strategy_slip')
            cash = right.number_input('目标现金比例', 0., 1., None if 'factor_strategy_cash' in st.session_state else .1, .05, key='factor_strategy_cash')
            policy = st.selectbox('成交时点', ['next_close', 'next_open'],
                index=0, filter_mode=None,
                format_func=lambda value: '下一交易日收盘' if value == 'next_close' else '下一交易日开盘', key='factor_strategy_policy')
            confirmed = st.checkbox('确认以上费用与成交设置')
            start = st.form_submit_button('运行因子策略回测', type='primary')
    st.session_state['_factor_strategy_controls'] = {key:st.session_state[key] for key in (
        'factor_strategy_cost', 'factor_strategy_slip', 'factor_strategy_cash', 'factor_strategy_policy')}
    if start and not confirmed:
        st.warning('请确认执行口径和成本后再运行。')
        start = False
    spec = ExecutionSpec('factor-rank-next-session', 'close' if policy == 'next_close' else 'open',
        policy, cost, slip, 'cn_stock')
    payload = dict(context_id=context_id, source=draft, cost=cost, slip=slip, cash=cash, policy=policy)
    state = sync_draft(st.session_state.get('_factor_strategy_run'), payload)
    with result_column if result_column is not None else st.container():
        state = background_run(state, lambda token: dict(result=run_factor_strategy(
            frame, draft, spec=spec, cash_weight=cash, token=token)), workspace='factor-strategy',
            start=start, public_mode=public_mode)
        st.session_state['_factor_strategy_run'] = state
        state = previous_run_view(state, workspace='factor-strategy')
        if state.status is not RunStatus.RESULT:
            st.caption('修改执行设置形成新草案；点击运行后才产生新的模拟结果。')
            return
        result = state.result['result']
        st.subheader('因子策略模拟结果')
        st.caption(f"结果来源：{result.config['factor_source']['factor_run_id']} · "
            f"明确排除 {result.config['factor_source']['excluded_rows']} 行不齐会话；归档保留完整执行配置。")
        a, b, c = st.columns(3)
        a.metric('组合区间收益', f"{result.metrics['total_return']:.2%}")
        b.metric('最大回撤', f"{result.metrics['max_drawdown']:.2%}")
        c.metric('模拟成交笔数', result.metrics['fills'])
        curve, trades, archive = st.tabs(['净值与现金', '买卖与拒单', '来源与归档'])
        with curve:
            ledger = result.accounting.ledger.copy()
            ledger['unit_nav'] = ledger['nav'] / result.config['initial_cash']
            ledger['drawdown'] = ledger['nav'] / ledger['nav'].cummax() - 1
            st.plotly_chart(build_performance_chart(ledger, nav='unit_nav', label='账户净值',
                revision=state.run_id), width='stretch', config=CHART_CONFIG)
            st.plotly_chart(build_time_series_chart(ledger, {'cash_weight':'现金比例',
                'gross_exposure':'股票暴露'}, title='现金与股票暴露', revision=state.run_id),
                width='stretch', config=CHART_CONFIG)
        with trades:
            st.dataframe(pd.DataFrame(result.orders).rename(columns={'symbol':'标的','side':'方向',
                'decision_date':'信号日期','effective_date':'执行日期','filled_quantity':'成交股数','reason':'原因'}),
                width='stretch', hide_index=True)
        with archive:
            st.json(result.config['factor_source'])
            st.download_button('下载因子策略完整归档',
                json.dumps(create_portfolio_archive(result, mode='private_local'), ensure_ascii=False, indent=2),
                'factor-strategy-local.json', mime='application/json')
        register_run(run_id=state.run_id, label='因子选股策略', manifest=result.inputs['run_manifest'],
            metrics=result.metrics, public_mode=public_mode)
