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
        "portfolio_allocation", "portfolio_date", "portfolio_symbol"}
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
    common_dates = set.intersection(*(set(f.trade_date) for f in frames.values()))
    excluded_rows = sum(len(f) - int(f.trade_date.isin(common_dates).sum()) for f in frames.values())
    with settings_column:
        def _explain_164():
            st.write(f"使用 {len(common_dates)} 个共同交易日，排除 {excluded_rows} 行日期不齐的记录。")
            st.write('日频多头模拟，统一现金账户。手续费、滑点和调仓门槛见高级设置。')
        help_link('数据与方法', _explain_164, key='portfolio_workspace_view_help_164')
    frames = {s: f.loc[f.trade_date.isin(common_dates)].copy() for s, f in frames.items()}
    try:
        revision = portfolio_data_fingerprint(frames)
    except ValueError as exc:
        from .research_diagnostics import show_safe_error
        show_safe_error(exc, operation='configuration')
        return
    draft = dict(context_id=context_id, input_revision=revision, recipe=recipe.to_dict(), policy=policy, cost=cost,
        slippage=slippage, initial_cash=initial_cash, strategy_key=strategy_key, params=params)
    state = sync_draft(st.session_state.get("portfolio_workspace_run"), draft)
    st.session_state["portfolio_workspace_run"] = state
    def compute(token):
        baseline = run_portfolio_workspace(frames, recipe=recipe, spec=spec,
            strategy_key=strategy_key, params=params, initial_cash=initial_cash, token=token)
        alternate = {s: (1 - cash_weight) * (.6 if i == 0 else .4 / (len(symbols) - 1))
                     for i, s in enumerate(symbols)} if len(symbols) > 1 else weights
        variants = [("费用 +10 基点", "cost", cost + 10),
            ("切换成交时点", "execution", "next_open" if policy == "next_close" else "next_close")]
        if len(symbols) > 1 and cash_weight < 1:
            variants.append(("首标的权重 60%", "weights", alternate))
        report = portfolio_scenarios(frames, recipe=recipe, spec=spec, strategy_key=strategy_key,
            params=params, initial_cash=initial_cash, variants=variants, token=token)
        return dict(baseline=baseline, scenarios=report)
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
                st.info(format_research_status('draft'))
            elif state.status is RunStatus.STALE:
                st.info(f"{format_research_status('stale')}；上次成功结果保留，请重新运行。")
            else:
                st.error(f"{format_research_status('failed', recoverable=state.last_success is not None)}；上次成功结果保留。")
            return
        result = state.result["baseline"]
        run_id = state.run_id
        metrics = result.metrics
        summary = build_portfolio_research_summary(result)
        a, b, c, d = st.columns(4)
        a.metric("组合区间收益", f"{summary['return']:.2%}" if summary['return'] is not None else "—")
        b.metric("最大回撤", f"{summary['drawdown']:.2%}" if summary['drawdown'] is not None else "—")
        c.metric("期末现金权重", f"{summary['cash_weight']:.2%}" if summary['cash_weight'] is not None else "—")
        d.metric("区间换手", f"{summary['turnover']:.2%}" if summary['turnover'] is not None else "—")
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
        nav_tab, cash_tab, orders_tab, contribution_tab, leg_tab, risk_tab, robust, archive_tab = st.tabs([
            "净值与回撤", "现金与持仓", "成交与拒单", "个股贡献", "策略腿贡献", "风险与暴露", "稳健性", "研究归档"
        ])
        with nav_tab:
            curve = view["curve"].copy()
            curve["unit_nav"] = curve.nav / result.config['initial_cash']
            curve["drawdown"] = curve.nav / curve.nav.cummax() - 1
            curve = envelope_sample(curve, value='nav')
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
        with cash_tab:
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
                "market_value": "市值", "close": "收盘价"})
            if positions.empty:
                st.info("当前筛选无持仓")
            else:
                with st.expander('持仓明细'):
                    render_paged_table(positions, key="portfolio_positions")
        with orders_tab:
            st.subheader(f"{date} · {selected} · 成交与拒单")
            orders = pd.DataFrame(view["orders"])
            if orders.empty:
                st.info("当前筛选无订单")
                st.caption("空订单不是异常，表示当日没有满足条件的调仓或没有可执行成交。")
            else:
                orders = orders[["symbol", "side", "effective_date", "requested_quantity", "filled_quantity",
                    "remaining_quantity", "status", "reason"]].rename(columns={"symbol": "标的", "side": "方向",
                    "effective_date": "执行日期", "requested_quantity": "申请股数", "filled_quantity": "成交股数",
                    "remaining_quantity": "剩余股数", "status": "状态", "reason": "原因"})
                render_paged_table(orders, key="portfolio_orders")
            st.caption("成交价格、现金变化和拒单原因来自同一条离线订单链；空交易不会被当作失败。")
        with contribution_tab:
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
        with leg_tab:
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
        with risk_tab:
            risk = result.accounting.risk
            for column, label, key, percent in zip(st.columns(4),
                ['年化波动', '夏普比率', 'Sortino', '股票集中度'],
                ['annual_volatility', 'sharpe', 'sortino', 'concentration_hhi'],
                [True, False, False, False]):
                value = _finite_float(risk.get(key))
                column.metric(label, '—' if value is None else f'{value:.2%}' if percent else f'{value:.2f}')
            def _explain_320():
                st.write('波动按252个交易日年化。夏普和Sortino衡量单位风险收益；集中度HHI越接近1，持仓越集中。')
                st.caption(f"有效样本 {risk.get('observations', '—')} · 状态 {risk.get('status', '—')}")
            help_link('风险指标说明', _explain_320, key='portfolio_workspace_view_help_320')
            exposure = view["ledger"][["trade_date", "cash_weight", "gross_exposure", "net_exposure"]].copy()
            exposure = envelope_sample(exposure, value="gross_exposure")
            exposure_fig = build_time_series_chart(exposure,
                {'cash_weight':'现金比例', 'gross_exposure':'股票暴露'}, title='现金与股票暴露',
                revision=f'exposure-{run_id}')
            st.plotly_chart(exposure_fig, width='stretch', key='portfolio_exposure', config=CHART_CONFIG)
            st.caption(f"期末股票暴露 {summary['gross_exposure']:.2%} · 期末现金权重 {summary['cash_weight']:.2%} · 风险状态 {summary['risk']['status']}")
        with robust:
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
        with archive_tab:
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
