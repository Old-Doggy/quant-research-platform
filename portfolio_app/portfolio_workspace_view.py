"""Compact portfolio workspace backed by the shared offline account."""
from __future__ import annotations
from portfolio_app.research_help import help_link

import json
import math

import pandas as pd
import streamlit as st

from .research_charts import build_performance_chart, build_time_series_chart, build_metric_bars, build_allocation_chart, CHART_CONFIG
from .offline_execution import ExecutionSpec
from .portfolio_archive import create_portfolio_archive
from .portfolio_recipe import PortfolioRecipe
from .portfolio_workspace import LIMITATIONS, portfolio_data_fingerprint, portfolio_drilldown, portfolio_scenarios, run_portfolio_workspace
from .research_run_adapter import sync_draft
from .research_run_state import RunStatus
from .strategies import STRATEGIES, normalize_strategy_params
from .research_audit_view import register_run, render_run_audit
from .research_task_view import background_run, previous_run_view
from .research_display import render_paged_table, envelope_sample, check_research_size, prepared_download
from .ui_copy import format_research_status


def _finite_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def align_portfolio_observations(frames, metadata):
    common_dates = set.intersection(*(set(f.trade_date) for f in frames.values()))
    excluded_rows = sum(len(f) - int(f.trade_date.isin(common_dates).sum()) for f in frames.values())
    if excluded_rows:
        if metadata['source_kind'] != 'synthetic' or any('session_calendar' in f.attrs for f in frames.values()):
            raise ValueError('组合标的交易日不齐，请先在数据中心核对缺失日期和停牌记录。')
        frames = {s: f.loc[f.trade_date.isin(common_dates)].copy() for s, f in frames.items()}
    return frames, common_dates, excluded_rows


def build_portfolio_research_summary(result):
    """Build the first-screen portfolio summary from the shared account result."""
    metrics = getattr(result, "metrics", {}) or {}
    accounting = getattr(result, "accounting", None)
    ledger = getattr(accounting, "ledger", pd.DataFrame()) if accounting is not None else pd.DataFrame()
    ledger = ledger if isinstance(ledger, pd.DataFrame) else pd.DataFrame()
    last = ledger.iloc[-1] if not ledger.empty else None
    initial_cash = _finite_float((getattr(result, "config", {}) or {}).get("initial_cash"))
    turnover_notional = _finite_float(ledger["turnover_notional"].sum()) if "turnover_notional" in ledger else None
    turnover = turnover_notional / initial_cash if turnover_notional is not None and initial_cash else None
    risk = getattr(accounting, "risk", {}) or {} if accounting is not None else {}
    diagnostics = getattr(accounting, "diagnostics", {}) or {} if accounting is not None else {}
    return {
        "return": _finite_float(metrics.get("total_return")),
        "drawdown": _finite_float(metrics.get("max_drawdown")),
        "cash_weight": _finite_float(last.get("cash_weight")) if last is not None else None,
        "gross_exposure": _finite_float(last.get("gross_exposure")) if last is not None else None,
        "net_exposure": _finite_float(last.get("net_exposure")) if last is not None else None,
        "turnover": turnover,
        "cost": _finite_float(metrics.get("total_cost")),
        "fills": int(metrics.get("fills") or 0),
        "rejected": int(metrics.get("rejected") or 0),
        "risk": {
            "status": str(risk.get("status") or "unavailable"),
            "annual_volatility": _finite_float(risk.get("annual_volatility")),
            "sharpe": _finite_float(risk.get("sharpe")),
            "sortino": _finite_float(risk.get("sortino")),
            "concentration_hhi": _finite_float(risk.get("concentration_hhi")),
            "observations": int(risk.get("observations") or 0),
        },
        "reconciliation": str(diagnostics.get("contribution_status") or "unknown"),
    }


def render_portfolio_workspace(frame, *, context_id, public_mode):
    # Streamlit removes widget state while a workspace is not rendered.
    # Keep an independent snapshot so returning restores the same draft.
    control_keys = {"portfolio_symbols", "portfolio_strategy", "portfolio_cash", "portfolio_initial",
        "portfolio_cost", "portfolio_policy", "portfolio_slippage", "portfolio_threshold",
        "portfolio_allocation", "portfolio_date", "portfolio_symbol","portfolio_capital_flows"}
    saved = st.session_state.get("portfolio_workspace_controls", {})
    for key, value in saved.items():
        if key not in st.session_state:
            st.session_state[key] = value
    try:
        _render_portfolio_workspace(frame, context_id=context_id, public_mode=public_mode)
    finally:
        st.session_state["portfolio_workspace_controls"] = {
            key: st.session_state[key] for key in st.session_state
            if key in control_keys or key.startswith(("portfolio_param_", "portfolio_weight_"))}


def _render_portfolio_workspace(frame, *, context_id, public_mode):
    try:
        check_research_size(frame)
    except ValueError as exc:
        st.warning(str(exc))
        return
    st.html('''<style>
    [data-testid="stMainBlockContainer"] {padding-top:2.8rem;max-width:1320px;}
    [data-testid="stMainBlockContainer"] h1 {font-size:1.65rem;}
    [data-testid="stMetricValue"] {font-size:1.45rem;overflow-wrap:anywhere;}
    [data-testid="stMainBlockContainer"] h3 {font-size:1.1rem;}
    @media(max-width:640px){[data-testid="stMainBlockContainer"]{padding:2rem 1rem;}}
    </style>''')
    st.title("组合研究")
    from .research_dataset import dataset_metadata, record_context
    metadata = dataset_metadata(frame)
    record_context(st.session_state, 'portfolio', frame)
    st.caption(f"{metadata['dataset_id']} / {metadata['version']} · 日频组合模拟")
    options = sorted(frame.symbol.unique())
    settings_column, result_column = st.columns([1, 3.5], gap="large")
    with settings_column:
        st.subheader("组合配置")
        symbols = st.multiselect("组合标的", options, default=options[:3], key="portfolio_symbols", filter_mode=None)
        strategy_key = st.selectbox("策略模板", [s.key for s in STRATEGIES],
            format_func=lambda k: next(s.name for s in STRATEGIES if s.key == k), key="portfolio_strategy", filter_mode=None)
        run_slot = st.container()
        if st.button("一键等权", key="portfolio_equal_weight"):
            st.session_state["portfolio_allocation"] = "等权"
            for symbol in symbols:
                st.session_state.pop(f"portfolio_weight_{symbol}", None)
            st.rerun()
        with st.expander("高级设置 · 资金与交易", expanded=False):
            a, b, c = [st.container() for _ in range(3)]
            cash_weight = a.number_input("保留现金比例", 0.0, 1.0, .1, .05, key="portfolio_cash",
                help='0.1 表示保留 10% 现金，其余资金按下方权重分配。')
            initial_cash = b.number_input("初始研究资金", min_value=1000.0, value=100000.0, step=10000.0, key="portfolio_initial")
            cost = c.number_input("交易费用（基点）", 0.0, 200.0, 10.0, 5.0, key="portfolio_cost",
                help='买入、卖出分别收费。10 个基点 = 成交金额的 0.1%。')
            a, b, c = [st.container() for _ in range(3)]
            policy = a.selectbox("成交时点", ["next_close", "next_open"],
                format_func=lambda x: "下一交易日收盘" if x == "next_close" else "下一交易日开盘", key="portfolio_policy", filter_mode=None)
            slippage = b.number_input("滑点（基点）", 0.0, 100.0, 0.0, 1.0, key="portfolio_slippage",
                help='在历史成交价上加入额外的不利价差；首次运行可保留 0。')
            threshold = c.number_input("最小调仓比例", 0.0, .2, .01, .005, key="portfolio_threshold",
                help='目标权重变化小于此比例时不调仓。0.01 = 1%。')
            flow_text=st.text_area('外部出入金（可选）',value='',key='portfolio_capital_flows',
                placeholder='2023-06-01,10000',height=95,
                help='每行：交易日期,金额。正数入金，负数出金；在当日开盘前计入，金额单位为元。留空表示没有外部资金变化。')
            params = {}
            strategy = next(s for s in STRATEGIES if s.key == strategy_key)
            columns = [st.container() for _ in strategy.parameters]
            for col, parameter in zip(columns, strategy.parameters):
                kind = int if parameter["type"] == "int" else float
                params[parameter["key"]] = col.number_input(parameter["label"],
                    min_value=kind(parameter["min"]), max_value=kind(parameter["max"]),
                    value=kind(parameter["default"]), step=kind(parameter["step"]),
                    key=f"portfolio_param_{parameter['key']}")
            allocation = st.radio("资金分配", ["等权", "自定义权重"], horizontal=False, key="portfolio_allocation")
            if not symbols:
                st.info("请选择至少一只标的；全现金研究可将目标现金比例设为 100%。")
                return
            weights = {s: (1 - cash_weight) / len(symbols) for s in symbols}
            if allocation == "自定义权重":
                for symbol in symbols:
                    weights[symbol] = st.number_input(f"{symbol} 资金权重", 0.0, 1.0,
                        float(weights[symbol]), .05, key=f"portfolio_weight_{symbol}")
            st.caption("目标权重：" + " · ".join(f"{s} {w:.1%}" for s, w in weights.items()) + f" · 现金 {cash_weight:.1%}")
        with run_slot:
            from .strategy_catalog import strategy_input_status
            readiness = strategy_input_status(frame.loc[frame.symbol.isin(symbols)], strategy_key)
            if not readiness['can_run']:
                st.caption(readiness['message'])
                st.caption(readiness['action'])
            start = st.button("运行组合研究", type="primary", key="portfolio_run", width="stretch",
                              disabled=not readiness['can_run'])
        st.caption(f"现金 {cash_weight:.0%} · 单边费用 {cost:g} 基点 · 滑点 {slippage:g} 基点")
    result_area = result_column.container()
    try:
        normalize_strategy_params(strategy_key, params)
        recipe = PortfolioRecipe.from_dict(dict(recipe_id="workspace", target_weights=weights,
            cash_weight=cash_weight, lot_size=100, min_rebalance_weight=threshold, missing_leg_policy="fail"))
        spec = ExecutionSpec(policy, "close" if policy == "next_close" else "open", policy, cost, slippage, "cn_stock")
    except ValueError as exc:
        from .research_diagnostics import show_safe_error
        show_safe_error(exc, operation='configuration')
        return
    frames = {s: frame.loc[frame.symbol.eq(s)].copy() for s in symbols}
    try:
        frames, common_dates, excluded_rows = align_portfolio_observations(frames, metadata)
        from .cashflow_returns import parse_flow_text,normalize_flows
        external_flows=normalize_flows(parse_flow_text(flow_text),
            [pd.Timestamp(day).date().isoformat() for day in common_dates])
    except ValueError as exc:
        st.info(str(exc))
        return
    with settings_column:
        def _explain_164():
            st.write(f"使用 {len(common_dates)} 个共同交易日，排除 {excluded_rows} 行日期不齐的记录。")
            st.write('日频多头模拟，统一现金账户。手续费、滑点和调仓门槛见高级设置。')
        help_link('数据与方法', _explain_164, key='portfolio_workspace_view_help_164')
    try:
        revision = portfolio_data_fingerprint(frames)
    except ValueError as exc:
        from .research_diagnostics import show_safe_error
        show_safe_error(exc, operation='configuration')
        return
    draft = dict(context_id=context_id, input_revision=revision, recipe=recipe.to_dict(), policy=policy, cost=cost,
        slippage=slippage, initial_cash=initial_cash, strategy_key=strategy_key, params=params,external_flows=external_flows)
    state = sync_draft(st.session_state.get("portfolio_workspace_run"), draft)
    st.session_state["portfolio_workspace_run"] = state
    def compute(token):
        baseline = run_portfolio_workspace(frames, recipe=recipe, spec=spec,
            strategy_key=strategy_key, params=params, initial_cash=initial_cash, token=token,external_flows=external_flows)
        alternate = {s: (1 - cash_weight) * (.6 if i == 0 else .4 / (len(symbols) - 1))
                     for i, s in enumerate(symbols)} if len(symbols) > 1 else weights
        variants = [("费用 +10 基点", "cost", cost + 10),
            ("切换成交时点", "execution", "next_open" if policy == "next_close" else "next_close")]
        if len(symbols) > 1 and cash_weight < 1:
            variants.append(("首标的权重 60%", "weights", alternate))
        report = portfolio_scenarios(frames, recipe=recipe, spec=spec, strategy_key=strategy_key,
            params=params, initial_cash=initial_cash, variants=variants, token=token,external_flows=external_flows)
        result = dict(baseline=baseline, scenarios=report)
        from .portfolio_capacity import capacity_inputs
        result['capacity_inputs']=capacity_inputs(frames)
        if not public_mode:
            from .result_replay import portfolio_replay_inputs
            from .research_dataset import dataset_metadata
            result['data_mode'] = dataset_metadata(next(iter(frames.values())))['source_kind']
            result['replay'] = portfolio_replay_inputs(frames, recipe=recipe, spec=spec,
                strategy_key=strategy_key, params=params, initial_cash=initial_cash,external_flows=external_flows)
        return result
    with result_area:
        state = background_run(state, compute, workspace='portfolio', start=start, public_mode=public_mode)
        st.session_state["portfolio_workspace_run"] = state
        state = previous_run_view(state, workspace='portfolio')
        if state.status is RunStatus.FAILED:
            return
        if state.status is not RunStatus.RESULT:
            if state.status is RunStatus.RUNNING:
                st.info(f"{format_research_status('running', phase='simulation')}；可取消或切换页面。")
            elif state.status is RunStatus.DRAFT:
                st.caption('确认组合配置后运行，结果将在此显示。')
            elif state.status is RunStatus.STALE:
                st.info(f"{format_research_status('stale')}；上次成功结果保留，请重新运行。")
            else:
                st.error(f"{format_research_status('failed', recoverable=state.last_success is not None)}；上次成功结果保留。")
            return
        result = state.result["baseline"]
        run_id = state.run_id
        metrics = result.metrics
        if result.config.get('external_flows'):
            annual=metrics.get('money_weighted_annual')
            st.caption('收益按时间加权计算；资金加权年收益 '+(f'{annual:.2%}' if annual is not None else '—（无法确定唯一值）')+' · ACT/365')
        summary = build_portfolio_research_summary(result)
        a, b, c, d = st.columns(4)
        a.metric("组合区间收益", f"{summary['return']:.2%}" if summary['return'] is not None else "—")
        b.metric("最大回撤", f"{summary['drawdown']:.2%}" if summary['drawdown'] is not None else "—")
        c.metric("期末现金权重", f"{summary['cash_weight']:.2%}" if summary['cash_weight'] is not None else "—")
        d.metric("累计换手", f"{summary['turnover']:.2%}" if summary['turnover'] is not None else "—",
                 help='区间累计成交金额除以初始资金，可能超过 100%。')
        cost_text = f"{summary['cost']:,.2f}" if summary['cost'] is not None else "—"
        st.caption(f"累计费用 {cost_text} · 模拟成交 {summary['fills']} 笔 · 拒单 {summary['rejected']} 笔")
        selection = st.session_state.get("portfolio_selection", {})
        dates = result.inputs["sessions"]
        if selection.get("run_id") != run_id:
            selection = dict(run_id=run_id, date=dates[-1], symbol=None)
            st.session_state["portfolio_date"] = dates[-1]
            st.session_state["portfolio_symbol"] = "全部标的"
        if st.session_state.get("portfolio_date") not in dates:
            st.session_state["portfolio_date"] = selection["date"]
        symbol_options = ["全部标的", *result.inputs["symbols"]]
        if st.session_state.get("portfolio_symbol") not in symbol_options:
            st.session_state["portfolio_symbol"] = selection["symbol"] or "全部标的"
        a, b = st.columns(2)
        date = a.selectbox("研究日期", dates, key="portfolio_date", filter_mode=None)
        selected = b.selectbox("钻取标的", symbol_options, key="portfolio_symbol", filter_mode=None)
        symbol = None if selected == "全部标的" else selected
        st.session_state["portfolio_selection"] = dict(run_id=run_id, date=date, symbol=symbol)
        view = portfolio_drilldown(result, date=date, symbol=symbol)
        performance,attribution,holdings,risk_panel=st.tabs(
            ['净值表现','收益归因','持仓交易','风险分析'],key='portfolio_main_view',on_change='rerun')
        detail=None
        if performance.open:
            with performance:
                detail=st.segmented_control('表现明细',['净值与回撤','稳健性','研究归档'],
                    default='净值与回撤',required=True,key='portfolio_performance_detail')
        if attribution.open:
            with attribution:
                detail=st.segmented_control('归因明细',['收益分解','策略贡献'],default='收益分解',
                    required=True,key='portfolio_attribution_detail')
        if holdings.open:
            with holdings:
                detail=st.segmented_control('持仓与交易明细',['现金与持仓','成交与拒单'],
                    default='现金与持仓',required=True,key='portfolio_holdings_detail')
        if risk_panel.open:
            with risk_panel:
                detail=st.segmented_control('风险明细',['风险与暴露','流动性与容量'],
                    default='风险与暴露',required=True,key='portfolio_risk_detail')
        if performance.open and detail=='净值与回撤':
            with performance:
                curve = view["curve"].copy()
                if 'unit_nav' not in curve:
                    curve["unit_nav"] = curve.nav / result.config['initial_cash']
                curve["drawdown"] = curve.unit_nav / curve.unit_nav.cummax().clip(lower=1.) - 1
                curve = envelope_sample(curve, value=['unit_nav','drawdown'])
                def select_chart_date():
                    from .chart_events import accept_chart_event, plotly_date_event
                    event = st.session_state.get("portfolio_nav", {})
                    previous = st.session_state.get('_portfolio_chart_event', {})
                    sequence = previous.get('sequence', 0) if previous.get('chart_id') == run_id else 0
                    selected_event = plotly_date_event(event, chart_id=run_id, symbol='portfolio', sequence=sequence + 1)
                    accepted = accept_chart_event(selected_event, chart_id=run_id, symbol='portfolio', dates=set(dates), last_sequence=sequence)
                    if accepted:
                        st.session_state['_portfolio_chart_event'] = accepted
                        st.session_state["portfolio_date"] = accepted['date']
                fig = build_performance_chart(curve, nav='unit_nav', label='账户净值',
                    title='账户净值与回撤', revision=f'portfolio-{run_id}')
                # Plotly emits point-selection events only for marker-enabled traces.
                # Keep the curve clean while retaining a seven-pixel click target.
                fig.data[0].update(mode='lines+markers', marker=dict(size=7, opacity=0))
                fig.update_layout(clickmode='event+select')
                st.plotly_chart(fig, width="stretch", key="portfolio_nav", on_select=select_chart_date,
                    selection_mode="points", config=CHART_CONFIG)
                st.caption(f"研究日期 {date} · 点击曲线定位持仓日期")
        if holdings.open and detail=='现金与持仓':
            with holdings:
                row = view["ledger"].iloc[0]
                a, b, c, d = st.columns(4)
                a.metric("当日现金", f"{row.cash:,.2f}")
                b.metric("股票市值", f"{row.positions_value:,.2f}")
                c.metric("现金权重", f"{row.cash_weight:.1%}")
                d.metric("股票暴露", f"{row.gross_exposure:.1%}")
                if row.get('receivables', 0.):
                    st.caption(f"应收股息 {row.receivables:,.2f} · 已计入净值，到账后转为可用现金 · 税前")
                def _explain_256():
                    st.caption(f"资金差额 {row.reconciliation_delta:.8f} · 贡献对账 {summary['reconciliation']}")
                help_link('账户对账', _explain_256, key='portfolio_workspace_view_help_256')
                st.subheader(f"{date} · {selected} · 实际持仓")
                if symbol is None and row.nav > 0:
                    st.plotly_chart(build_allocation_chart(view['positions'], cash=float(row.cash), nav=float(row.nav),
                        receivables=float(row.get('receivables', 0.)),
                        revision=f'allocation-{run_id}-{date}'), width='stretch', config=CHART_CONFIG,
                        key='portfolio_allocation_chart')
                positions = view["positions"].rename(columns={"trade_date": "日期", "symbol": "标的", "quantity": "股数",
                    "sellable_quantity": "已上市股数",
                    "valuation_status": "估值状态",
                    "market_value": "市值", "close": "收盘价"})
                if positions.empty:
                    st.info("当前筛选无持仓")
                else:
                    with st.expander('持仓明细'):
                        render_paged_table(positions, key="portfolio_positions")
        if holdings.open and detail=='成交与拒单':
            with holdings:
                st.subheader(f"{date} · {selected} · 成交与拒单")
                from .portfolio_order_view import render_orders
                render_orders(pd.DataFrame(view['orders']),revision=f'{run_id}-{date}-{selected}')
        if attribution.open and detail=='收益分解':
            with attribution:
                from .portfolio_contribution import contribution_period
                scope=st.segmented_control('贡献期间',['当日','截至所选日'],default='当日',key='portfolio_contribution_period')
                ledger=result.accounting.ledger
                first=ledger.trade_date.iloc[0] if scope=='截至所选日' else date
                required={'price_pnl','dividend_pnl','contribution_residual_pnl'}
                if required<=set(ledger):
                    report=contribution_period(ledger,initial_cash=result.config['initial_cash'],start=first,end=date)
                    components=report['components']
                    from .research_charts import build_contribution_waterfall
                    st.plotly_chart(build_contribution_waterfall(components,
                        revision=f'account-contribution-{run_id}-{date}-{scope}'),
                        width='stretch',config=CHART_CONFIG,key='portfolio_account_contribution')
                    st.caption(f"组合收益 {report['total_return']:.2%} · 分项合计 {components.contribution.sum():.2%}")
                    st.download_button('下载收益分解',components.to_csv(index=False).encode('utf-8-sig'),
                        'portfolio-contribution.csv','text/csv',key='portfolio_components_csv')
                else:
                    st.caption('此历史批次未保存分项账本，可查看原证券贡献。')
                st.subheader(f"{date} · {selected} · 个股贡献")
                contribution = view["contribution"].rename(columns={"trade_date": "日期", "symbol": "标的",
                    "contribution": "日收益贡献", "pnl": "毛损益", "kind": "贡献类型"})
                if contribution.empty:
                    st.info("当前筛选无收益贡献变化")
                else:
                    st.plotly_chart(build_metric_bars(contribution, category='标的', value='日收益贡献',
                        title='当日个股毛收益贡献', revision=f'contribution-{run_id}-{date}'),
                        width='stretch', config=CHART_CONFIG, key='portfolio_contribution_chart')
                    with st.expander('贡献明细'):
                        render_paged_table(contribution, key="portfolio_contribution")
                st.caption("毛收益贡献 · 费用与现金见账本")
                with st.expander("当日完整账本与事件编号"):
                    render_paged_table(view["ledger"], key="portfolio_raw_ledger")
                    render_paged_table(pd.DataFrame(view["orders"]), key="portfolio_raw_orders")
        if attribution.open and detail=='策略贡献':
            with attribution:
                st.subheader(f"{date} · {selected} · 策略腿贡献")
                legs = view["leg_contribution"].rename(columns={
                    "trade_date": "日期", "leg": "策略腿", "pnl": "毛损益", "contribution": "日收益贡献"
                })
                if legs.empty:
                    st.info("当前筛选无策略腿贡献变化")
                else:
                    st.plotly_chart(build_metric_bars(legs, category='策略腿', value='日收益贡献',
                        title='当日策略腿毛收益贡献', revision=f'legs-{run_id}-{date}'),
                        width='stretch', config=CHART_CONFIG, key='portfolio_leg_chart')
                    with st.expander('策略贡献明细'):
                        render_paged_table(legs, key="portfolio_leg_contribution")
        if risk_panel.open and detail=='流动性与容量':
            with risk_panel:
                from .portfolio_capacity_view import render_capacity
                st.caption(f'{date} · 全组合持仓，不随单只标的筛选变化')
                render_capacity(result,state.result.get('capacity_inputs'),date=date,revision=f'capacity-{run_id}-{date}')
        if risk_panel.open and detail=='风险与暴露':
            with risk_panel:
                risk = view['risk']
                st.caption(f'截至 {date} · 全组合风险，不随单只标的筛选变化')
                for column, label, key, percent in zip(st.columns(4),
                    ['年化波动', '夏普比率', 'Sortino', '股票集中度 HHI'],
                    ['annual_volatility', 'sharpe', 'sortino', 'concentration_hhi'],
                    [True, False, False, False]):
                    value = _finite_float(risk.get(key))
                    column.metric(label, '—' if value is None else f'{value:.2%}' if percent else f'{value:.2f}')
                def _explain_320():
                    st.write(f"波动按{risk['annualization_sessions']}个交易日年化。夏普和Sortino衡量单位风险收益；集中度HHI越接近1，持仓越集中。")
                    st.caption(f"有效样本 {risk.get('observations', '—')} · 状态 {risk.get('status', '—')}")
                help_link('风险指标说明', _explain_320, key='portfolio_workspace_view_help_320')
                exposure = view["curve"][["trade_date", "cash_weight", "gross_exposure", "net_exposure"]].copy()
                exposure = envelope_sample(exposure, value=['gross_exposure','cash_weight'])
                exposure_fig = build_time_series_chart(exposure,
                    {'cash_weight':'现金比例', 'gross_exposure':'股票暴露'}, title='现金与股票暴露',
                    revision=f'exposure-{run_id}-{date}')
                if (pd.Timestamp(exposure.trade_date.max())-pd.Timestamp(exposure.trade_date.min())).days<90:
                    exposure_fig.update_xaxes(tickformat='%m-%d',nticks=6)
                st.plotly_chart(exposure_fig, width='stretch', key='portfolio_exposure', config=CHART_CONFIG)
                exposure_row=view['ledger'].iloc[0]
                st.caption(f"{date} 股票暴露 {exposure_row.gross_exposure:.2%} · 现金权重 {exposure_row.cash_weight:.2%}")
        if performance.open and detail=='稳健性':
            with performance:
                st.caption("每个场景只改变一个假设；结果按预设顺序展示，失败和缺数据场景不计算比较差值。")
                report = state.result["scenarios"].drop(columns=["config", "data_sha256"], errors="ignore")
                if not report.empty and {'scenario_id', 'total_return'}.issubset(report.columns):
                    st.plotly_chart(build_metric_bars(report, category='scenario_id', value='total_return',
                        title='预设场景 · 区间收益', revision=f'scenarios-{run_id}'),
                        width='stretch', config=CHART_CONFIG, key='portfolio_scenario_chart')
                st.dataframe(report.rename(columns={"scenario_id": "场景", "changed_assumption": "变化假设",
                    "comparable": "可比较", "status": "状态", "total_return": "区间收益",
                    "max_drawdown": "最大回撤", "total_cost": "费用", "delta_total_return": "相对基准收益差",
                    "delta_max_drawdown": "相对基准回撤差", "delta_total_cost": "相对基准费用差"}),
                    width="stretch", hide_index=True)
        if performance.open and detail=='研究归档':
            with performance:
                register_run(run_id=run_id, label='统一账户组合', manifest=result.inputs['run_manifest'],
                             metrics=metrics, public_mode=public_mode)
                render_run_audit(result.inputs['run_manifest'], integrity={'status': 'UNVERIFIED'},
                                 public_mode=public_mode, key='portfolio_run_audit')
                st.caption("公开摘要仅保留汇总指标。完整归档保留配置、订单和持仓，仅供本地研究。")
                summary = create_portfolio_archive(result, mode="public_redacted")
                st.download_button("下载公开组合摘要", json.dumps(summary, ensure_ascii=False, indent=2),
                    "portfolio-summary.json", mime="application/json", key="portfolio_public_archive")
                if not public_mode:
                    local = prepared_download(key='_portfolio_archive_bytes', identity=run_id,
                        build=lambda: json.dumps(create_portfolio_archive(result, mode="private_local"), ensure_ascii=False, indent=2))
                    st.download_button("下载本地完整组合归档", local,
                        "portfolio-local.json", mime="application/json", key="portfolio_private_archive")
        def _explain_361():
            for limitation in LIMITATIONS:
                st.write(f"- {limitation}")
            st.caption("基准收益、因子收益归因与行业集中度：当前无可信输入，显示为不可用。")
        help_link("研究假设与缺失能力", _explain_361, key='portfolio_workspace_view.py_explain_361')
