"""Strategy and portfolio research workspace implementation and adapter."""
from __future__ import annotations
from portfolio_app.research_help import help_link

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from portfolio_app.research_audit_view import register_run
from portfolio_app.research_charts import build_performance_chart, CHART_CONFIG
from portfolio_app.workspace_shell import workspace_heading, research_columns

T = TypeVar("T")

_RESEARCH_GLOBALS = (
    "PUBLIC_MODE", "SAMPLE_ROOT", "STRATEGIES", "RunStatus", "json", "pd", "st",
    "build_data_fingerprint", "build_drawdown_chart", "build_equity_chart",
    "build_single_stock_performance", "build_single_stock_sensitivity_report",
    "build_strategy_result_cost_frame", "build_strategy_result_details",
    "build_strategy_result_position_frame", "build_strategy_result_trade_frame",
    "build_strategy_result_payload", "create_strategy_archive", "draft_payload",
    "format_research_status", "normalize_strategy_params", "read_market_file",
    "run_explicit", "run_portfolio_research", "run_single_stock_research",
    "show_safe_error", "sync_draft",
)


def render_research_workspace(route_state: Any, *, render_body: Callable[[Any], T]) -> T:
    """Render strategy or portfolio research only for its supported routes."""
    if getattr(route_state, "active_workspace", None) not in {"strategy", "portfolio"}:
        raise ValueError("research workspace requires strategy or portfolio route")
    return render_body(route_state)


def render_research_workspace_body(route_state: Any, *, app_globals: Mapping[str, Any]) -> None:
    """Render the extracted strategy/portfolio workspace with explicit dependencies."""
    module_globals = globals()
    from .workspace_dependencies import bind_workspace_dependencies
    bind_workspace_dependencies(module_globals, app_globals, _RESEARCH_GLOBALS)
    render_explicit_research_workspace(route_state)

def render_explicit_research_workspace(route_state) -> None:
    # Widget state is removed when its page is absent. Preserve strategy controls
    # separately so navigation does not silently replace a successful draft.
    if route_state.active_workspace != 'strategy':
        _render_explicit_research_workspace(route_state)
        return
    def is_control(key):
        return key in {'explicit_cost_strategy', 'explicit_strategy_strategy'} or key.startswith('explicit_strategy_')
    for key, value in st.session_state.get('_strategy_workspace_controls', {}).items():
        if st.session_state.get(key) is None and value is not None:
            st.session_state[key] = value
    try:
        _render_explicit_research_workspace(route_state)
    finally:
        saved = dict(st.session_state.get('_strategy_workspace_controls', {}))
        saved.update({key: st.session_state[key] for key in st.session_state
                      if is_control(key) and st.session_state[key] is not None})
        st.session_state['_strategy_workspace_controls'] = saved


def _render_single_strategy_result_payload(
    payload: dict[str, object],
    *,
    state,
    strategy,
    strategy_params: dict[str, object],
    is_current: bool,
) -> None:
    """Render the single-stock result as a summary followed by intentional detail layers."""
    from portfolio_app.research_audit_view import render_run_audit
    summary = payload.get("summary", {})
    summary = summary if isinstance(summary, dict) else {}
    performance = payload.get("performance", {})
    performance = performance if isinstance(performance, dict) else {}
    details = payload.get("details", {})
    details = details if isinstance(details, dict) else {}
    limitations = [str(item) for item in payload.get("limitations", [])]
    result_title = "当前运行结果" if is_current else "上次成功结果"
    st.subheader(result_title)
    status_text = "已完成 · 当前草案匹配" if is_current else "仅供查看 · 当前草案已改变"
    dataset = payload.get('archive', {}).get('manifest', {}).get('dataset', {})
    dataset_label = f"{dataset.get('dataset_id', '未记录数据集')} / {dataset.get('data_version', '未记录版本')}"
    st.caption(f"{status_text} · {dataset_label}")

    summary_columns = st.columns(4)
    for column, label, key in zip(
        summary_columns,
        ("区间收益", "最大回撤", "交易次数", "总成本"),
        ("total_return", "max_drawdown", "trades", "total_cost"),
    ):
        value = summary.get(key)
        if value is None:
            display = "—"
        elif key in {"total_return", "max_drawdown", "total_cost"}:
            display = f"{float(value):.2%}"
        else:
            display = f"{int(value):,}"
        column.metric(label, display)
    sharpe_value = summary.get("sharpe")
    sharpe_display = "—" if sharpe_value is None else f"{float(sharpe_value):.2f}"
    st.caption(
        f"信号 {int(summary.get('signals', 0) or 0):,} · "
        f"订单 {int(summary.get('orders', 0) or 0):,} · "
        f"成交 {int(summary.get('fills', 0) or 0):,} · "
        f"拒单 {int(summary.get('rejected_orders', 0) or 0):,} · "
        f"夏普 {sharpe_display}"
    )

    performance_tab,trades_tab,costs_panel,records_panel=st.tabs(
        ['净值表现','买卖事件','成本与参数','研究记录'],key='strategy_main_view',on_change='rerun')
    detail=None
    if performance_tab.open:
        with performance_tab:
            detail=st.segmented_control('表现视图',['净值与回撤','结果摘要'],default='净值与回撤',
                required=True,key='strategy_performance_detail')
    if costs_panel.open:
        with costs_panel:
            detail=st.segmented_control('分析视图',['成交与成本','参数敏感性'],default='成交与成本',
                required=True,key='strategy_analysis_detail')
    if records_panel.open:
        with records_panel:
            detail=st.segmented_control('研究记录',['规则与口径','归档与复现'],default='规则与口径',
                required=True,key='strategy_records_detail')
    if performance_tab.open and detail=='结果摘要':
        with performance_tab:
            metrics = performance.get("metrics", {}) if isinstance(performance, dict) else {}
            metrics = metrics if isinstance(metrics, dict) else {}
            st.write("研究状态：已完成离线研究模拟。")
            st.caption(
                f"研究区间：{payload.get('research_diagnostics', {}).get('date_start', '未提供')} 至 "
                f"{payload.get('research_diagnostics', {}).get('date_end', '未提供')} · "
                f"执行口径：{metrics.get('execution_policy_label', '下一交易日收盘（离线研究假设）')}"
            )
            diagnostics = payload.get("research_diagnostics", {})
            if isinstance(diagnostics, dict):
                quality = diagnostics.get("data_quality", {})
                quality_status = quality.get("status", "未知") if isinstance(quality, dict) else "未知"
                st.dataframe(pd.DataFrame([
                    {"研究检查": "数据质量", "结果": quality_status},
                    {"研究检查": "预热期", "结果": f"{int(diagnostics.get('warmup_bars', 0) or 0)} 根"},
                    {"研究检查": "信号覆盖率", "结果": f"{float(diagnostics.get('signal_coverage', 0.0) or 0.0):.2%}"},
                    {"研究检查": "研究限制", "结果": "；".join(limitations)},
                ]), width="stretch", hide_index=True)
    if performance_tab.open and detail=='净值与回撤':
        with performance_tab:
            curve = pd.DataFrame(performance.get("curve", []))
            if curve.empty:
                st.info("当前结果没有可展示的净值曲线。")
            else:
                display=st.segmented_control('净值展示',['图表','表格'],default='图表',required=True,key='strategy_nav_display')
                table=curve.rename(columns=dict(date='日期',nav='净值',benchmark_nav='买入持有净值',
                    drawdown='回撤',daily_return='日收益',daily_cost='日成本'))
                curve["trade_date"] = pd.to_datetime(curve.pop("date"))
                curve["equity"] = curve.pop("nav")
                curve["benchmark_equity"] = curve.pop("benchmark_nav")
                curve["drawdown"] = pd.to_numeric(curve.get("drawdown"), errors="coerce")
                if display=='图表':
                    from .research_display import envelope_sample
                    shown=envelope_sample(curve,value=['equity','benchmark_equity','drawdown'])
                    st.plotly_chart(build_performance_chart(shown, nav="equity", benchmark="benchmark_equity",
                        revision=f"strategy-{state.run_id}"), width="stretch", config=CHART_CONFIG,
                        key=f"explicit-performance-{state.run_id}")
                else:
                    from .research_display import render_paged_table
                    render_paged_table(table,key='strategy_nav_table')
                st.download_button('下载净值数据',table.to_csv(index=False).encode('utf-8-sig'),
                    'strategy-nav.csv','text/csv',key='strategy_nav_csv')
                def _explain_141():
                    st.write('净值已扣设定成本；灰线为同标的买入持有，回撤相对策略历史峰值。拖动框选缩放，双击复位，点击图例显隐。')
                help_link('图表与计算说明', _explain_141, key='research_workspace_help_141')
    if trades_tab.open:
        with trades_tab:
            trade_frame = build_strategy_result_trade_frame(details)
            if trade_frame.empty:
                st.info("当前参数和区间没有产生买卖事件。")
            else:
                from .strategy_event_view import render_strategy_events
                render_strategy_events(performance,trade_frame,revision=f'strategy-events-{state.run_id}')
            position_frame = build_strategy_result_position_frame(details)
            with st.expander("单位化事件账本", expanded=False):
                st.caption("按单位买卖记录现金与数量；比例净值见净值表现，金额不代表策略账户资产。")
                if position_frame.empty:
                    st.info("当前结果没有成交，因此没有现金与持仓快照。")
                else:
                    st.dataframe(position_frame, width="stretch", hide_index=True)
    if costs_panel.open and detail=='成交与成本':
        with costs_panel:
            cost_assumption = performance.get("cost_assumption", {})
            cost_assumption = cost_assumption if isinstance(cost_assumption, dict) else {}
            cost_metrics = performance.get("metrics", {})
            cost_metrics = cost_metrics if isinstance(cost_metrics, dict) else {}
            cost_columns = st.columns(3)
            cost_columns[0].metric("单次换手成本", f"{float(cost_assumption.get('transaction_cost', 0.0)):.2%}")
            cost_columns[1].metric("累计成本", f"{float(cost_metrics.get('total_cost', 0.0)):.2%}")
            cost_columns[2].metric("产生成本的交易日", str(int(performance.get("diagnostics", {}).get("cost_rows", 0) or 0)))
            st.caption("成本 = 持仓换手 × 设定费率")
            from .strategy_cost_view import render_strategy_costs
            render_strategy_costs(performance,revision=f'strategy-cost-{state.run_id}')
    if costs_panel.open and detail=='参数敏感性':
        with costs_panel:
            st.subheader("当前运行参数")
            st.dataframe(pd.DataFrame([{"参数": key, "值": value} for key, value in strategy_params.items()]), width="stretch", hide_index=True)
            sensitivity = pd.DataFrame(payload.get("sensitivity", []))
            if sensitivity.empty:
                st.info("当前结果没有参数敏感性记录。")
            else:
                from .research_charts import build_metric_bars
                if {'scenario_id', 'total_return'}.issubset(sensitivity.columns):
                    shown = sensitivity.copy()
                    shown['场景'] = shown.scenario_id.map(lambda v: str(v).replace('baseline','基准').replace('transaction-cost-','费率 ').replace('slippage-bps-','滑点（基点） ').replace('parameter-neighbor-','参数邻域 ').replace('neighbor-','邻域 ').replace('fast_window','短期窗口').replace('slow_window','长期窗口').replace('execution-policy-next_day_open','次日开盘执行'))
                    st.plotly_chart(build_metric_bars(shown, category='场景', value='total_return',
                        title='参数与成本场景 · 区间收益', revision=f'sensitivity-{state.run_id}'),
                        width='stretch', config=CHART_CONFIG)
                with st.expander('场景数据明细'):
                    st.dataframe(sensitivity, width="stretch", hide_index=True)
    if records_panel.open and detail=='规则与口径':
        with records_panel:
            config = payload.get("strategy_config", {})
            config = config if isinstance(config, dict) else {}
            st.subheader("策略规则")
            for rule in config.get("rules", []):
                st.write(f"• {rule}")
            st.dataframe(pd.DataFrame([{"参数": key, "值": value} for key, value in strategy_params.items()]), width="stretch", hide_index=True)
            st.subheader("研究限制")
            for limitation in limitations:
                st.write(f"• {limitation}")
            render_run_audit(payload.get("run_manifest", {}), integrity=payload.get("integrity", {}), public_mode=PUBLIC_MODE)
    if records_panel.open and detail=='归档与复现':
        with records_panel:
            archive = payload.get("archive")
            if archive is None:
                st.info("当前结果没有可下载归档。")
            else:
                st.write("归档包含运行口径、数据指纹、策略结果详情和限制说明，可用于本地复核。")
                st.download_button(
                    "下载本地策略结果归档",
                    data=json.dumps(archive, ensure_ascii=False, indent=2),
                    file_name=f"{state.run_id}-strategy-result-archive.json",
                    mime="application/json",
                    key=f"download-explicit-strategy-archive-{state.run_id}",
                )


def _render_explicit_research_workspace(route_state) -> None:
    """Render strategy/portfolio research behind an explicit run boundary."""
    is_portfolio = route_state.active_workspace == "portfolio"
    from portfolio_app.research_audit_view import register_run, render_run_audit
    from portfolio_app.research_dataset import selected_dataset, dataset_metadata, record_context
    if is_portfolio:
        from portfolio_app.portfolio_workspace_view import render_portfolio_workspace

        render_portfolio_workspace(selected_dataset(st.session_state, lambda: read_market_file(SAMPLE_ROOT / "quant_demo_multi_symbol.csv")),
            context_id=route_state.context.context_id, public_mode=PUBLIC_MODE)
        return
    title = "组合研究" if is_portfolio else "策略研究"
    workspace_heading(title)
    settings_column, result_column = research_columns('strategy')
    if not PUBLIC_MODE:
        open_factor = st.session_state.pop('_open_factor_strategy', False)
        with settings_column:
            mode = st.radio('研究方式', ['单股模板', '因子选股'], horizontal=True,
                index=1 if open_factor else 0,
                key='explicit_strategy_mode')
        if mode == '因子选股':
            from .factor_rank_strategy_view import render_factor_strategy
            render_factor_strategy(context_id=route_state.context.context_id, public_mode=PUBLIC_MODE,
                settings_column=settings_column, result_column=result_column)
            return

    demo_name = "quant_demo_multi_symbol.csv" if is_portfolio else "quant_demo_single_symbol.csv"
    demo_frame = selected_dataset(st.session_state, lambda: read_market_file(SAMPLE_ROOT / demo_name))
    metadata = dataset_metadata(demo_frame)
    record_context(st.session_state, 'strategy', demo_frame)
    available_symbols = sorted(str(symbol) for symbol in demo_frame["symbol"].dropna().unique())
    strategy_keys = [item.key for item in STRATEGIES]
    strategy_labels = {item.key: item.name for item in STRATEGIES}
    previous = st.session_state.get(f"research_run_state_{route_state.active_workspace}")

    with settings_column:
        st.subheader("研究设置")
        st.caption(f"{metadata['dataset_id']} / {metadata['version']} · {len(demo_frame):,} 行")
        with st.container():
            strategy_key = st.selectbox("策略模板", strategy_keys, format_func=strategy_labels.get,
                index=0, filter_mode=None,
                key=f"explicit_strategy_{route_state.active_workspace}")
        with st.container():
            if is_portfolio:
                symbols = st.multiselect("组合标的", available_symbols, default=available_symbols[:3], key="explicit_portfolio_symbols", filter_mode=None)
            else:
                symbol = st.selectbox("标的", available_symbols,
                    index=0, key="explicit_strategy_symbol", filter_mode=None)
                symbols = [symbol]
        with st.expander('高级设置 · 参数与成本'):
            transaction_cost = st.number_input("单次换手成本", min_value=0.0, max_value=0.02,
                value=0.001,
                step=0.0005, format="%.4f", key=f"explicit_cost_{route_state.active_workspace}",
                help='0.001 表示每次换手扣除 0.1%，即 10 个基点。')

            strategy = next(item for item in STRATEGIES if item.key == strategy_key)
            strategy_params: dict[str, object] = {}
            parameter_columns = [st.container() for _ in strategy.parameters]
            for column, parameter in zip(parameter_columns, strategy.parameters):
                with column:
                    key = str(parameter["key"])
                    if parameter["type"] == "int":
                        strategy_params[key] = st.number_input(
                            str(parameter["label"]),
                            min_value=int(parameter["min"]),
                            max_value=int(parameter["max"]),
                            value=int(parameter["default"]),
                            step=int(parameter["step"]),
                            key=f"explicit_{route_state.active_workspace}_{key}",
                        )
                    else:
                        strategy_params[key] = st.number_input(
                            str(parameter["label"]),
                            min_value=float(parameter["min"]),
                            max_value=float(parameter["max"]),
                            value=float(parameter["default"]),
                            step=float(parameter["step"]),
                            key=f"explicit_{route_state.active_workspace}_{key}",
                        )
        st.caption("可直接使用默认参数运行；需要调整时展开高级设置。")
        from .strategy_catalog import strategy_input_status
        readiness = strategy_input_status(demo_frame.loc[demo_frame.symbol.isin(symbols)], strategy_key)
        if not readiness['can_run']:
            st.caption(readiness['message'])
            st.caption(readiness['action'])
        start = st.button("运行研究", type="primary", key=f"run_explicit_{route_state.active_workspace}", width="stretch",
                          disabled=not readiness['can_run'])
    result_area = result_column.container()
    try:
        normalize_strategy_params(strategy_key, strategy_params)
    except ValueError as exc:
        show_safe_error(exc, operation='configuration')
        return

    if not symbols:
        st.warning("请至少选择一个标的后再运行研究。")
        return
    draft = draft_payload(
        context_id=route_state.context.context_id,
        workspace=route_state.active_workspace,
        dataset_id=metadata['dataset_id'],
        symbols=symbols,
        as_of=str(route_state.context.as_of),
        strategy_key=strategy_key,
        strategy_params=strategy_params,
        analysis_mode="portfolio" if is_portfolio else "single",
        transaction_cost=float(transaction_cost),
    )
    draft['input_revision'] = build_data_fingerprint(demo_frame.loc[demo_frame.symbol.isin(symbols)])
    state = sync_draft(previous, draft)
    st.session_state[f"research_run_state_{route_state.active_workspace}"] = state

    status_labels = {
        RunStatus.DRAFT: format_research_status("draft"),
        RunStatus.STALE: format_research_status("stale"),
        RunStatus.RUNNING: format_research_status("running", phase="queued"),
        RunStatus.RESULT: format_research_status("succeeded"),
        RunStatus.FAILED: format_research_status("failed", recoverable=state.last_success is not None),
    }
    def compute(token) -> dict[str, object]:
        if is_portfolio:
            frames = {code: demo_frame.loc[demo_frame["symbol"].eq(code)].copy() for code in symbols}
            weights = {code: 1.0 / len(frames) for code in frames}
            research = run_portfolio_research(
                frames,
                strategy_key=strategy_key,
                target_weights=weights,
                cash_weight=0.0,
                params=strategy_params,
                transaction_cost=float(transaction_cost), token=token,
            )
            metrics = research.diagnostics["metrics"]
        else:
            selected = demo_frame.loc[demo_frame["symbol"].eq(symbols[0])].copy()
            research = run_single_stock_research(
                selected,
                strategy_key=strategy_key,
                params=strategy_params,
                transaction_cost=float(transaction_cost), token=token,
            )
            metrics = research.metrics
        if is_portfolio:
            result_payload = None
        else:
            performance = build_single_stock_performance(
                research.frame,
                transaction_cost=float(transaction_cost),
            )
            details = build_strategy_result_details(
                research.trade_events,
                initial_cash=100_000.0,
            )
            limitations = [
                "离线历史研究模拟，不代表实时行情或真实成交",
                "不连接 QMT、券商、账户或实盘提交系统",
                "初始资金和成交数量为展示口径，不是账户资产记录",
            ]
            from portfolio_app.return_series import build_return_series
            sensitivity_input=selected.copy(deep=True)
            sensitivity_input['return']=build_return_series(sensitivity_input)
            sensitivity_frame = build_single_stock_sensitivity_report(
                sensitivity_input,
                strategy_key,
                params=strategy_params,
                transaction_cost=float(transaction_cost),
                transaction_costs=(0.0, float(transaction_cost), min(0.02, float(transaction_cost) * 2)),
                slippage_bps=(0.0, 5.0, 10.0),
                execution_policies=("next_day_close", "next_day_open"),
                start_date=selected["trade_date"].min(),
                end_date=selected["trade_date"].max(),
            )
            sensitivity_records=sensitivity_frame.astype(object).where(sensitivity_frame.notna(),None).to_dict('records')
            archive = create_strategy_archive(
                strategy={"strategy_id": strategy_key, "config": research.strategy_config},
                dataset={
                    "dataset_id": metadata['dataset_id'],
                    "data_version": metadata['version'],
                    "symbol": str(symbols[0]),
                    "rows": int(len(selected)),
                    "coverage_start": str(selected["trade_date"].min().date()),
                    "coverage_end": str(selected["trade_date"].max().date()),
                    "content_hash": build_data_fingerprint(selected),
                },
                execution={
                    "mode": "offline_research_simulation",
                    "execution_lag_days": int(research.strategy_config["execution_lag_days"]),
                    "execution_policy": str(research.strategy_config["execution_policy"]),
                    "transaction_cost": float(transaction_cost),
                    "slippage_bps": 0.0,
                    "initial_cash": 100_000.0,
                },
                result={
                    "performance": performance,
                    "details": details,
                    "sensitivity": sensitivity_records,
                },
                limitations=limitations,
            )
            result_payload = build_strategy_result_payload(
                metrics=metrics,
                performance=performance,
                details=details,
                strategy_config=research.strategy_config,
                research_diagnostics=research.diagnostics,
                run_manifest=research.diagnostics["run_manifest"],
                integrity=research.diagnostics["integrity"],
                limitations=limitations,
                sensitivity=sensitivity_records,
            )
            result_payload["archive"] = archive
        computed = {
            "data_mode": "seeded_demo" if metadata['source_kind'] == 'synthetic' else metadata['source_kind'],
            "workspace": route_state.active_workspace,
            "strategy_key": strategy_key,
            "symbols": tuple(symbols),
            "metrics": {key: float(value) for key, value in metrics.items() if isinstance(value, (int, float))},
            'run_manifest': research.diagnostics['run_manifest'],
            'integrity': research.diagnostics['integrity'],
            'result_payload': result_payload,
        }
        if not PUBLIC_MODE and not is_portfolio:
            from .result_replay import single_stock_replay_inputs
            computed['single_stock_research'] = research
            computed['replay'] = single_stock_replay_inputs(selected, strategy_key=strategy_key,
                params=strategy_params, transaction_cost=transaction_cost)
            computed['research_parameters'] = computed['replay']['config']
        return computed

    from portfolio_app.research_task_view import background_run, previous_run_view
    state = background_run(state, compute, workspace="strategy", start=start, public_mode=PUBLIC_MODE)
    st.session_state[f"research_run_state_{route_state.active_workspace}"] = state

    with result_area:
        # Render the status after the task coordinator has accepted a submission or
        # delivered a terminal result, so RESULT is never shown as RUNNING.
        st.caption(status_labels[state.status])
        if state.last_success is not None and state.status in {RunStatus.STALE, RunStatus.FAILED}:
            st.caption(f"上次成功结果保留：{state.last_success_run_id}；当前配置不会混用该结果。")

        state = previous_run_view(state, workspace='strategy')
        if state.status is RunStatus.RESULT and state.result:
            result = state.result
            metrics = result.get("metrics", {})
            register_run(run_id=state.run_id, label='单股策略', manifest=result['run_manifest'],
                         metrics=metrics, public_mode=PUBLIC_MODE)
            result_payload = result.get("result_payload")
            if isinstance(result_payload, dict):
                _render_single_strategy_result_payload(
                    result_payload,
                    state=state,
                    strategy=strategy,
                    strategy_params=strategy_params,
                    is_current=st.session_state[f"research_run_state_{route_state.active_workspace}"].status is RunStatus.RESULT,
                )
            else:
                st.warning("该运行结果缺少新的分层展示载荷，请重新运行当前配置后查看完整结果。")
                st.subheader("当前运行结果")
                st.json(metrics)
            with st.expander('固定参数样本外验证', expanded=st.session_state.get('_validation_open', False)):
                if st.session_state[f"research_run_state_{route_state.active_workspace}"].status is not RunStatus.RESULT:
                    st.info('正在查看旧结果；请重新运行当前配置后再做样本外验证。')
                    return
                validation_start = st.button('检查样本外稳健性', key='locked_validation_run')
                if validation_start:
                    st.session_state['_validation_open'] = True
                from portfolio_app.validation import locked_validation_report
                from portfolio_app.research_task_view import background_task
                def validate(token):
                    source=demo_frame.loc[demo_frame.symbol.eq(symbols[0])].copy()
                    report=locked_validation_report(
                        source, strategy_key,
                        params=strategy_params, transaction_cost=float(transaction_cost), token=token)
                    if not PUBLIC_MODE:
                        from .result_replay import validation_replay_inputs
                        report['replay']=validation_replay_inputs(source,strategy_key=strategy_key,
                            params=strategy_params,transaction_cost=float(transaction_cost))
                    report['data_mode']='synthetic' if metadata['source_kind']=='synthetic' else metadata['source_kind']
                    return report
                validation_task, report = background_task(workspace='strategy-validation',
                    identity=state.draft_fingerprint, compute=validate, start=validation_start, public_mode=PUBLIC_MODE)
                if report is not None:
                    st.session_state['locked_validation_result'] = (state.run_id, report)
                saved = st.session_state.get('locked_validation_result')
                if saved and saved[0] == state.run_id:
                    report = saved[1]
                    from portfolio_app.result_presentations import render_validation_results
                    render_validation_results(report)
        elif state.status is RunStatus.FAILED:
            st.error(f"本次研究失败：{state.error}")
        else:
            st.html('<div class="quant-empty"><strong>查看策略表现</strong>'
                '选择标的与策略，点击“运行研究”。</div>')
