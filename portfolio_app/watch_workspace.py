"""Watch workspace implementation and route adapter.

The body is extracted from the local app while its shared dependencies are
bridged explicitly through the already loaded local app module.
"""
from __future__ import annotations
from portfolio_app.research_help import help_link
from portfolio_app.workspace_shell import workspace_heading

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

T = TypeVar("T")

_WATCH_GLOBALS = ('DEFAULT_DATA_ROOT', 'PUBLIC_MODE', 'REPO_ROOT', 'ResearchSubmission', 'SAMPLE_ROOT', 'STRATEGIES', '_render_pure_stock_view', '_research_data_version', '_research_processing_payload', 'build_data_quality_report', 'build_drawdown_chart', 'build_equity_chart', 'build_equity_chart_key', 'build_indicator_config_controls', 'build_market_detail_context', 'build_ohlcv_payload', 'build_portfolio_contribution_chart', 'build_portfolio_exposure_chart', 'build_portfolio_robustness_report', 'build_portfolio_trade_event_frame', 'build_readable_trades', 'build_research_cache_key', 'build_research_diagnostics_frame', 'build_robustness_chart', 'build_robustness_report', 'build_robustness_summary', 'build_single_stock_performance', 'build_single_stock_sensitivity_report', 'build_single_stock_snapshot', 'build_stock_quote_table', 'build_strategy_comparison', 'build_strategy_comparison_chart', 'build_strategy_focus_event_id', 'build_strategy_result_details', 'build_strategy_result_diagnostics', 'build_strategy_result_position_frame', 'build_strategy_result_trade_frame', 'build_strategy_showcases', 'cached_local_symbol', 'cached_stock_catalog', 'cached_symbol_names', 'cached_symbols', 'chart_bridge_html', 'compare_symbol_backtests', 'components', 'create_strategy_archive', 'current_submission', 'explain_report_limitations', 'format_metric', 'hashlib', 'json', 'normalize_indicator_config', 'normalize_strategy_params', 'pd', 'read_market_file', 'render_allocation', 'render_experiments', 'render_import_preview', 'render_strategy_showcase_card', 'run_portfolio_research', 'run_single_stock_research', 'search_stock_catalog', 'sensitivity_report', 'show_safe_error', 'st', 'walk_forward_report', 'watchlist_store')


def render_watch_workspace(route_state: Any, *, render_body: Callable[[Any], T]) -> T:
    """Render the watch workspace only when the router selected watch."""
    if getattr(route_state, "active_workspace", None) != "watch":
        raise ValueError("watch workspace requires the watch route")
    return render_body(route_state)


def render_watch_workspace_body(route_state: Any, *, app_globals: Mapping[str, Any]) -> None:
    """Keep the explicitly selected source while Streamlit removes hidden widgets."""
    session = app_globals['st'].session_state
    if 'dashboard_source' not in session and '_watch_source_preference' in session:
        session['dashboard_source'] = session['_watch_source_preference']
    try:
        _render_watch_workspace_body(route_state, app_globals=app_globals)
    finally:
        if 'dashboard_source' in session:
            session['_watch_source_preference'] = session['dashboard_source']


def _render_watch_workspace_body(route_state: Any, *, app_globals: Mapping[str, Any]) -> None:
    """Render the extracted watch workspace using the shared app contracts."""
    from .research_charts import build_performance_chart, CHART_CONFIG
    module_globals = globals()
    from .workspace_dependencies import bind_workspace_dependencies
    bind_workspace_dependencies(module_globals, app_globals, _WATCH_GLOBALS)

    """Current watch implementation, kept intact for incremental extraction."""
    workspace_heading("行情与研究")
    from .market_watch import render_market_watch
    if render_market_watch(route_state, app_globals):
        return
    from .research_dataset import selected_dataset, record_context
    registered_frame = selected_dataset(st.session_state, lambda: None)
    route_symbol = route_state.context.symbol
    if registered_frame is not None:
        st.session_state['dashboard_source'] = '登记研究数据'

    with st.expander("行情来源与研究设置", expanded=False):
        data_source = st.selectbox(
            "数据来源",
            (["登记研究数据"] if registered_frame is not None else []) + (["合成示例", "文件导入"] if PUBLIC_MODE else ["合成示例", "文件导入", "本地行情"]),
            index=0 if registered_frame is not None else 2 if not PUBLIC_MODE and cached_symbols(str(DEFAULT_DATA_ROOT)) else 0,
            key="dashboard_source",
            help="本地模式默认读取 data/daily_qfq_merged 下的日线文件；它是历史行情，不是实时行情。", filter_mode=None,
        )
        data_root = str(DEFAULT_DATA_ROOT)
        adjusted = "qfq"
        symbols = []
        stock_names: dict[str, str] = {}
        local_catalog: list[dict[str, object]] = []
        local_watchlist: WatchlistStore | None = None
        if data_source == "本地行情":
            # The local root is configured through PORTFOLIO_DATA_ROOT and is
            # intentionally not echoed into the page or exported UI state.
            st.caption("本地历史行情")
            adjusted = st.selectbox("价格口径", ["qfq", "hfq", "raw"], index=0, filter_mode=None, format_func={"qfq":"前复权", "hfq":"后复权", "raw":"不复权"}.get)
            local_catalog = cached_stock_catalog(data_root, adjusted)
            symbols = [str(item["symbol"]) for item in local_catalog]
            stock_names = cached_symbol_names(data_root)
            local_watchlist = watchlist_store()
            search_query = st.text_input("搜索代码或名称", key="local_stock_search", placeholder="例如 000001 或 平安")
            search_results = search_stock_catalog(local_catalog, search_query)
            if search_results:
                result_symbols = [str(item["symbol"]) for item in search_results]
                route_marker = (route_state.context.context_id, route_symbol)
                if (st.session_state.get('_watch_route_symbol') != route_marker or 'local_stock_search_result' not in st.session_state) and route_symbol in result_symbols:
                    st.session_state['local_stock_search_result'] = route_symbol
                st.session_state['_watch_route_symbol'] = route_marker
                selected_from_search = st.selectbox(
                    "搜索结果",
                    result_symbols,
                    format_func=lambda code: f"{stock_names.get(code, '')} {code}".strip(),
                    key="local_stock_search_result", filter_mode=None,
                )
            else:
                selected_from_search = ""
                st.info("没有匹配的股票，请修改代码或名称。")
            favorite_symbols = [code for code in local_watchlist.symbols if code in symbols]
            recent_symbols = [code for code in local_watchlist.recent if code in symbols]
            if favorite_symbols:
                st.caption("自选：" + "、".join(favorite_symbols))
            if recent_symbols:
                st.caption("最近访问：" + "、".join(recent_symbols[:5]))
        analysis_mode = st.radio("分析模式", ["单股", "等权组合"], horizontal=True)
        portfolio_cash_weight = 0.0
        if data_source == "本地行情" and analysis_mode == "等权组合":
            selected_symbols = st.multiselect("组合股票", symbols, default=symbols[:3], filter_mode=None)
            symbol = selected_symbols[0] if selected_symbols else "未选择股票"
            portfolio_cash_weight = st.number_input("组合现金权重", min_value=0.0, max_value=1.0, value=0.0, step=0.05, key="portfolio_cash_weight")
        elif data_source == "本地行情":
            symbol = selected_from_search or (symbols[0] if symbols else "")
            if symbol and local_watchlist is not None:
                if st.session_state.get("_last_recent_symbol") != symbol:
                    local_watchlist.record_recent(symbol)
                    st.session_state["_last_recent_symbol"] = symbol
                favorite_action = st.button(
                    "移出自选" if symbol in local_watchlist.symbols else "加入自选",
                    key="toggle_local_watchlist",
                )
                if favorite_action:
                    if symbol in local_watchlist.symbols:
                        local_watchlist.remove(symbol)
                    else:
                        local_watchlist.add(symbol)
                    st.rerun()
            selected_symbols = [symbol]
        else:
            symbol = ""
            selected_symbols = []
        strategy_name = st.selectbox("策略", [strategy.name for strategy in STRATEGIES], filter_mode=None)
        strategy = next(item for item in STRATEGIES if item.name == strategy_name)
        with st.expander("高级设置 · 策略参数与成本"):
            st.caption(strategy.description)
            strategy_params: dict[str, object] = {}
            for parameter in strategy.parameters:
                key = str(parameter["key"])
                label = str(parameter["label"])
                default = parameter["default"]
                if parameter["type"] == "int":
                    strategy_params[key] = st.slider(
                        label,
                        int(parameter["min"]),
                        int(parameter["max"]),
                        int(default),
                        int(parameter["step"]),
                        key=f"strategy_{key}",
                    )
                else:
                    strategy_params[key] = st.slider(
                        label,
                        float(parameter["min"]),
                        float(parameter["max"]),
                        float(default),
                        float(parameter["step"]),
                        key=f"strategy_{key}",
                    )
            lookback = st.slider("展示区间", 120, 2500, 720, 30)
            transaction_cost = st.number_input("单次换手成本", min_value=0.0, max_value=0.02, value=0.001, step=0.0005, format="%.4f")
        try:
            normalize_strategy_params(strategy.key, strategy_params)
        except ValueError as exc:
            show_safe_error(exc, operation='configuration')
            return
        def _explain_168():
            st.write("规则链：" + "；".join(strategy.rules))
            st.write("必需字段：" + "、".join(strategy.required_features))
            st.caption(f"信号执行延迟：{strategy.execution_lag_days} 个交易日")
        help_link("查看策略规则", _explain_168, key='watch_workspace.py_explain_168')

    uploaded = st.file_uploader("导入 CSV、Excel 或 Parquet", type=["csv", "xlsx", "xls", "parquet", "pq"]) if data_source == "文件导入" else None
    synthetic = data_source == "合成示例"
    if registered_frame is not None and data_source == '登记研究数据':
        frame = registered_frame
        options = sorted(frame.symbol.unique())
        symbol = st.selectbox('登记数据标的', options, index=options.index(route_symbol) if route_symbol in options else 0, filter_mode=None)
        selected_symbols = st.multiselect('登记组合标的', options, default=options[:3], filter_mode=None) if analysis_mode == '等权组合' else [symbol]
        frame = frame.loc[frame.symbol.isin(selected_symbols)].copy()
        if frame.empty:
            st.info('请选择至少一个标的。')
            return
    elif synthetic:
        sample_name = "quant_demo_multi_symbol.csv" if analysis_mode == "等权组合" else "quant_demo_single_symbol.csv"
        frame = read_market_file(SAMPLE_ROOT / sample_name)
        demo_symbols = sorted(frame["symbol"].unique())
        selected_symbols = st.multiselect("示例标的", demo_symbols, default=demo_symbols, key="demo_symbols", filter_mode=None) if analysis_mode == "等权组合" else demo_symbols[:1]
        symbol = selected_symbols[0] if selected_symbols else "未选择"
        portfolio_cash_weight = st.number_input("组合现金权重", min_value=0.0, max_value=1.0, value=0.0, step=0.05, key="demo_portfolio_cash_weight") if analysis_mode == "等权组合" else 0.0
        st.caption("合成示例 · 非真实证券数据")
    elif uploaded is not None:
        try:
            frame = render_import_preview(uploaded, key="dashboard")
            if frame is None:
                return
            uploaded_symbols = sorted(symbol for symbol in frame["symbol"].unique() if symbol)
            if analysis_mode == "等权组合":
                selected_symbols = st.multiselect("导入文件中的组合股票", uploaded_symbols, default=uploaded_symbols[:3], filter_mode=None)
                portfolio_cash_weight = st.number_input("组合现金权重", min_value=0.0, max_value=1.0, value=0.0, step=0.05, key="uploaded_portfolio_cash_weight")
                if selected_symbols:
                    frame = frame.loc[frame["symbol"].isin(selected_symbols)].copy()
                    symbol = selected_symbols[0]
            else:
                uploaded_symbol = st.selectbox("导入文件中的股票", uploaded_symbols or ["uploaded"], filter_mode=None)
                frame = frame.loc[frame["symbol"].eq(uploaded_symbol)].copy() if uploaded_symbols else frame
                symbol = uploaded_symbol
            st.success(f"已导入 {len(frame):,} 条记录，日期范围 {frame['trade_date'].min().date()} 至 {frame['trade_date'].max().date()}。")
        except Exception as exc:
            show_safe_error(exc, operation='import')
            return
    elif symbols:
        try:
            frame = cached_local_symbol(data_root, symbol, adjusted)
        except Exception as exc:
            show_safe_error(exc, operation='import')
            return
    else:
        st.info("请选择本地数据目录，或导入一份日线数据开始分析。")
        return

    if build_data_quality_report(frame)['status'] != '通过':
        st.error('行情质量检查未通过，请在数据工作区检查价格、日期与成交记录。')
        return
    available_dates = pd.to_datetime(frame["trade_date"], errors="coerce").dropna()
    if available_dates.empty:
        st.error("当前数据没有可用交易日期。")
        return

    layers_column, date_column, task_column, submit_column = st.columns([1, 1, 1, 1])
    with layers_column, st.popover("指标与图层", width="stretch"):
        registry_indicator_config, registry_overlay_keys, registry_panel_keys = build_indicator_config_controls()
    try:
        normalize_indicator_config(registry_indicator_config)
    except ValueError as exc:
        show_safe_error(exc, operation='configuration')
        return
    with date_column, st.popover('研究日期设置', width="stretch"):
        date_range = st.date_input(
            "回测日期范围",
            value=(available_dates.min().date(), available_dates.max().date()),
            min_value=available_dates.min().date(),
            max_value=available_dates.max().date(),
            key=f"dashboard_date_range_{data_source}_{adjusted}_{analysis_mode}_{symbol or 'demo'}_{available_dates.min().date()}_{available_dates.max().date()}",
        )
    full_history = frame.copy()
    start_date, end_date = available_dates.min(), available_dates.max()
    if not isinstance(date_range, tuple) or len(date_range) != 2:
        st.info("请选择完整的起止日期。")
        return
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        frame = frame.loc[frame["trade_date"].between(start_date, end_date)].copy()
    if frame.empty:
        st.info("当前日期范围没有可用行情记录，请扩大日期范围。")
        return

    record_context(st.session_state, 'watch', frame,
        source_kind=None if data_source == '登记研究数据' else 'synthetic' if synthetic else 'file_import' if data_source == '文件导入' else 'local_market',
        price_basis=None if data_source == '登记研究数据' else adjusted if data_source == '本地行情' else 'synthetic' if synthetic else 'unspecified', symbol=symbol)

    if analysis_mode == "等权组合":
        if not selected_symbols:
            st.info("请选择至少一只股票后开始组合分析。")
            return
        target_weights = render_allocation(selected_symbols, portfolio_cash_weight)
        if target_weights is None:
            return
        if uploaded is not None or synthetic or data_source == '登记研究数据':
            portfolio_frames = {
                selected_symbol: frame.loc[frame["symbol"].eq(selected_symbol)].tail(lookback).copy()
                for selected_symbol in selected_symbols
            }
        else:
            portfolio_frames = {
                selected_symbol: cached_local_symbol(data_root, selected_symbol, adjusted)
                for selected_symbol in selected_symbols
            }
            portfolio_frames = {
                code: history.loc[history["trade_date"].between(start_date, end_date)].tail(lookback).copy()
                for code, history in portfolio_frames.items()
            }
        if any(history.empty for history in portfolio_frames.values()):
            st.info("部分组合标的在所选日期没有行情，请调整日期或移除该标的。")
            return
        common_dates = set.intersection(*(set(history.trade_date) for history in portfolio_frames.values()))
        excluded = sum(len(history) - int(history.trade_date.isin(common_dates).sum()) for history in portfolio_frames.values())
        if not common_dates:
            st.warning('组合没有共同交易会话，请调整标的或数据。')
            return
        st.caption(f'组合使用 {len(common_dates)} 个共同会话，明确排除 {excluded} 行不齐会话。')
        portfolio_frames = {code: history.loc[history.trade_date.isin(common_dates)].copy()
            for code, history in portfolio_frames.items()}
        for history in portfolio_frames.values():
            history['return'] = history.close.pct_change()
        research_frames = portfolio_frames
    else:
        frame = frame.tail(lookback).copy()
        if not selected_symbols and symbol:
            selected_symbols = [str(symbol)]
        research_frames = {str(symbol): full_history}

    from portfolio_app.research_display import check_research_size, render_paged_table, page_frame
    try:
        check_research_size(pd.concat(list(research_frames.values()), ignore_index=True))
    except ValueError as exc:
        st.warning(str(exc))
        return
    cache_key = build_research_cache_key(
        dataset_id="seeded_demo" if synthetic else f"{data_source.lower()}:{adjusted}",
        data_version=_research_data_version(research_frames),
        processing=_research_processing_payload(
            analysis_mode=analysis_mode,
            symbols=[str(item) for item in selected_symbols],
            strategy_key=strategy.key,
            strategy_params=strategy_params,
            transaction_cost=float(transaction_cost),
            date_start=start_date,
            date_end=end_date,
            lookback=lookback,
            target_weights=target_weights if analysis_mode == "等权组合" else None,
            cash_weight=float(portfolio_cash_weight),
            indicator_config=registry_indicator_config,
        ),
        engine_id="offline_research-v1",
    )
    from portfolio_app.research_task_view import session_runner
    cache = session_runner(public_mode=PUBLIC_MODE).cache
    submission = current_submission(st.session_state.get("dashboard_research_submission"), cache_key)
    stats = cache.stats()

    with task_column:
        def _explain_328():
            st.caption(f"提交 {stats.submissions} 次 · 命中 {stats.cache_hits} 次 · {cache_key.key_id}")
        help_link('运行与缓存详情', _explain_328, key='watch_workspace_help_328')
    with submit_column:
        from .strategy_catalog import strategy_input_status
        blocked = [strategy_input_status(history, strategy.key) for history in research_frames.values()]
        blocked = [item for item in blocked if not item['can_run']]
        if blocked:
            st.caption(blocked[0]['message'])
            st.caption(blocked[0]['action'])
        start_dashboard = st.button("提交研究", type="primary", key="submit_dashboard_research", width="stretch", disabled=bool(blocked))
    def compute_research(token) -> dict[str, object]:
        token.report(.05, "preflight")
        if analysis_mode == "等权组合":
            portfolio_result = run_portfolio_research(
                portfolio_frames,
                strategy_key=strategy.key,
                target_weights=target_weights,
                cash_weight=portfolio_cash_weight,
                params=strategy_params,
                transaction_cost=transaction_cost,
                token=token,
            )
            return {
                "portfolio_result": portfolio_result,
                "symbol_comparison": compare_symbol_backtests(
                    portfolio_frames,
                    strategy.key,
                    params=strategy_params,
                    transaction_cost=transaction_cost,
                ),
                "portfolio_robustness_report": build_portfolio_robustness_report(
                    portfolio_frames,
                    strategy_key=strategy.key,
                    weight_scenarios=(
                        target_weights,
                        {symbol_key: round((1.0 - portfolio_cash_weight) / len(portfolio_frames), 12) for symbol_key in portfolio_frames},
                        {symbol_key: round((1.0 - portfolio_cash_weight) * (1.0 if len(portfolio_frames) == 1 else 0.5 if index == 0 else 0.5 / (len(portfolio_frames) - 1)), 12) for index, symbol_key in enumerate(portfolio_frames)},
                    ),
                    windows=(min(120, len(next(iter(portfolio_frames.values())))), min(252, len(next(iter(portfolio_frames.values()))))),
                    transaction_costs=(0.0, transaction_cost, min(0.02, transaction_cost * 2)),
                    cash_weight=portfolio_cash_weight,
                    params_by_strategy=strategy_params,
                ),
            }
        single_stock_research = run_single_stock_research(
            full_history,
            strategy_key=strategy.key,
            params=strategy_params,
            transaction_cost=transaction_cost,
            start_date=frame["trade_date"].min(),
            end_date=frame["trade_date"].max(), token=token,
        )
        return {
            "single_stock_research": single_stock_research,
            "single_stock_performance": build_single_stock_performance(
                single_stock_research.frame,
                transaction_cost=transaction_cost,
            ),
            "single_stock_sensitivity": build_single_stock_sensitivity_report(
                full_history,
                strategy.key,
                params=strategy_params,
                transaction_cost=transaction_cost,
                transaction_costs=(0.0, transaction_cost, min(0.02, transaction_cost * 2)),
                slippage_bps=(0.0, 5.0, 10.0),
                execution_policies=("next_day_close", "next_day_open"),
                start_date=frame["trade_date"].min(),
                end_date=frame["trade_date"].max(),
            ),
            "robustness_report": build_robustness_report(
                frame, strategy.key, windows=(120, 252, 504), transaction_costs=(0.0, 0.001, 0.002), params=strategy_params
            ),
            "strategy_comparison": build_strategy_comparison(frame, windows=(252,), transaction_costs=(0.001,)),
        }

    from portfolio_app.research_task_view import background_task
    task, computed = background_task(workspace='dashboard', identity=cache_key.key_id,
        compute=compute_research, start=start_dashboard, public_mode=PUBLIC_MODE)
    if computed is not None:
        submission = ResearchSubmission(key_id=cache_key.key_id, result=computed, cache_hit=task['cache_hit'])
        st.session_state['dashboard_research_submission'] = submission
    if task.get('status') in {'failed', 'cancelled'} and submission is not None:
        st.warning('当前显示上次成功结果；本次研究未提交，结果不属于失败或取消的尝试。')
    if submission is None:
        from portfolio_app.research_task_view import previous_result_selected
        old = st.session_state.get('dashboard_research_submission')
        if previous_result_selected(workspace='dashboard', marker=(cache_key.key_id, task.get('task_id')),
                                    available=old is not None):
            previous = old.result
            if 'single_stock_research' in previous:
                old_frame = previous['single_stock_research'].frame
                old_metrics = previous['single_stock_performance']['metrics']
            else:
                old_frame = previous['portfolio_result'].frame
                old_metrics = previous['portfolio_result'].diagnostics['metrics']
            st.caption('上次研究摘要与原始结果曲线；当前配置仍为草案。')
            st.metric('上次策略区间收益', format_metric(old_metrics['total_return'], True))
            st.plotly_chart(build_equity_chart(old_frame, '上次成功结果'), width='stretch', key='dashboard_previous_curve')
            render_paged_table(old_frame, key='dashboard_previous_detail')
            return
        if analysis_mode == "单股":
            _render_pure_stock_view(
                frame,
                symbol=str(symbol),
                name=stock_names.get(str(symbol), "") if data_source == "本地行情" else "",
                source_label={"合成示例": "合成示例行情", "文件导入": "用户导入数据", "本地行情": "本地历史行情"}.get(data_source, "离线行情"),
                price_mode=adjusted if data_source == "本地行情" else ("imported" if data_source == "文件导入" else "synthetic"),
                price_unit="unknown",
                volume_unit="unknown",
                indicator_config=registry_indicator_config,
                panel_count=len(registry_panel_keys),
            )
        else:
            st.subheader("组合行情数据")
            display_frame = frame.tail(30).copy()
            display_frame.attrs = {}
            st.dataframe(display_frame, width="stretch", hide_index=True)
        return

    if analysis_mode == "等权组合":
        portfolio_result = submission.result["portfolio_result"]
        portfolio_frame = portfolio_result.frame
        metrics = portfolio_result.diagnostics["metrics"]
        symbol_comparison = submission.result["symbol_comparison"]
        portfolio_contribution_frame = portfolio_result.attribution
        portfolio_trade_frame = build_portfolio_trade_event_frame(portfolio_result.trade_events)
        portfolio_robustness_report = submission.result["portfolio_robustness_report"]
        backtest_frame = None
    else:
        single_stock_research = submission.result["single_stock_research"]
        backtest_frame, metrics = single_stock_research.frame, single_stock_research.metrics
        single_performance = submission.result.get("single_stock_performance")
        if single_performance is None:
            # Old cached submissions may predate the presentation contract.
            # Rebuild the view from the immutable research frame without rerunning research.
            single_performance = build_single_stock_performance(
                backtest_frame,
                transaction_cost=transaction_cost,
            )
        performance_metrics_view = single_performance["metrics"]
        metrics = {
            **metrics,
            "total_return": performance_metrics_view["total_return"],
            "annual_return": performance_metrics_view["annual_return"],
            "annual_volatility": performance_metrics_view["annual_volatility"],
            "sharpe": performance_metrics_view["sharpe"],
            "max_drawdown": performance_metrics_view["max_drawdown"],
            "trades": performance_metrics_view["trades"],
        }
        single_performance_frame = pd.DataFrame(single_performance["curve"])
        single_performance_frame["trade_date"] = pd.to_datetime(single_performance_frame.pop("date"))
        single_performance_frame["equity"] = single_performance_frame.pop("nav")
        single_performance_frame["benchmark_equity"] = single_performance_frame.pop("benchmark_nav")
        portfolio_frame = None
        robustness_report = submission.result["robustness_report"]
        execution_sensitivity = submission.result.get("single_stock_sensitivity")
        if execution_sensitivity is None:
            execution_sensitivity = build_single_stock_sensitivity_report(
                full_history,
                strategy.key,
                params=strategy_params,
                transaction_cost=transaction_cost,
                transaction_costs=(0.0, transaction_cost, min(0.02, transaction_cost * 2)),
                slippage_bps=(0.0, 5.0, 10.0),
                execution_policies=("next_day_close", "next_day_open"),
                start_date=frame["trade_date"].min(),
                end_date=frame["trade_date"].max(),
            )
        strategy_comparison = submission.result["strategy_comparison"]

    st.caption(f"已提交研究 · {'命中缓存' if submission.cache_hit else '完成计算'} · key {submission.key_id}")

    def performance_metrics():
        columns = st.columns(5)
        columns[0].metric("策略区间收益", format_metric(metrics["total_return"], True))
        columns[1].metric("年化收益", format_metric(metrics["annual_return"], True))
        columns[2].metric("夏普比率", format_metric(metrics["sharpe"]))
        columns[3].metric("最大回撤", format_metric(metrics["max_drawdown"], True))
        columns[4].metric("模拟成交次数", str(int(metrics["trades"])))

    robustness_summary: dict[str, object] = {}
    if analysis_mode == "单股":
        robustness_summary = build_robustness_summary(robustness_report)

    overview, strategy_tab, robustness_tab, projects_tab, data_tab, experiments_tab = st.tabs(
        ["行情概览", "策略回测", "稳健性报告", "研究项目", "数据检查", "实验记录"]
    )
    with overview:
        if analysis_mode == "等权组合":
            performance_metrics()
            overview_left, overview_right = st.columns(2)
            with overview_left:
                st.plotly_chart(
                    build_equity_chart(portfolio_frame, "等权组合净值与基准对比"),
                    width="stretch",
                    key=build_equity_chart_key("portfolio-overview"),
                )
            with overview_right:
                st.plotly_chart(
                    build_drawdown_chart(portfolio_frame, "组合策略回撤"),
                    width="stretch",
                    key="portfolio-overview-drawdown",
                )
            exposure_columns = st.columns(3)
            exposure_columns[0].metric("当前股票暴露", format_metric(float(portfolio_frame["gross_exposure"].iloc[-1]), True))
            exposure_columns[1].metric("当前现金权重", format_metric(float(portfolio_frame["cash_weight"].iloc[-1]), True))
            exposure_columns[2].metric("当前活跃标的", f"{int(portfolio_frame['active_symbols'].iloc[-1])} 只")
            st.plotly_chart(
                build_portfolio_exposure_chart(portfolio_frame),
                width="stretch",
                key="portfolio-overview-exposure",
            )
            display_frame = portfolio_frame.tail(30).copy()
            display_frame.attrs = {}
            st.dataframe(display_frame, width="stretch", hide_index=True)
        else:
            snapshot = build_single_stock_snapshot(backtest_frame, symbol=str(symbol))
            names = cached_symbol_names(data_root) if data_source == "本地行情" else {}
            st.subheader(f"{names.get(str(symbol), '')} {symbol}".strip())
            st.caption(
                f"历史行情 · {snapshot['start_date']} 至 {snapshot['latest_date']} · "
                f"共 {snapshot['observations']:,} 个交易日 · 数据截止日为 {snapshot['latest_date']}，不是实时行情"
            )
            quote_columns = st.columns(5)
            quote_columns[0].metric("最近收盘", format_metric(snapshot["close"]))
            quote_columns[1].metric("当日涨跌", format_metric(snapshot["daily_change"], True))
            quote_columns[2].metric("区间涨跌", format_metric(snapshot["period_return"], True))
            quote_columns[3].metric("模拟仓位", str(snapshot["strategy_state"]))
            quote_columns[4].metric("最近信号", str(snapshot["signal_state"]))
            lightweight_payload = build_ohlcv_payload(
                backtest_frame,
                symbol=str(symbol),
                events=backtest_frame.attrs.get("trade_events", []),
                focus_event_id=(
                    st.session_state.get("single_strategy_focus", {}).get("event_id")
                    if st.session_state.get("single_strategy_focus", {}).get("cache_key") == submission.key_id
                    else None
                ),
                initial_bars=min(120, len(backtest_frame)),
                min_visible_bars=min(30, max(1, len(backtest_frame))),
                max_visible_bars=len(backtest_frame),
                indicator_config=registry_indicator_config,
                data_context=build_market_detail_context(
                    backtest_frame, symbol=str(symbol), source="历史行情 + 离线研究模拟",
                    price_mode=adjusted if data_source == "本地行情" else "synthetic" if synthetic else "imported",
                    price_unit="元/股" if data_source == "本地行情" else "源数据单位",
                    volume_unit="源文件单位", as_of=snapshot["latest_date"],
                ),
            )
            chart_height = 520 + 126 * len(registry_panel_keys)
            components.html(chart_bridge_html(lightweight_payload, height=chart_height), height=chart_height, scrolling=False)
            st.caption(f"{strategy.name} · 红色买入 / 绿色卖出")
            summary_left, summary_right = st.columns(2)
            with summary_left:
                st.markdown(f"**最近信号 · {snapshot['latest_date']}**")
                st.write(snapshot["reason"])
            with summary_right:
                latest_trade = snapshot["latest_trade"]
                st.markdown("**最近模拟成交**")
                if latest_trade:
                    st.write(f"{latest_trade['effective_date']} · {'买入' if latest_trade['side'] == 'BUY' else '卖出'} · 模拟价格 {float(latest_trade['price']):.2f}")
                else:
                    st.write("当前区间没有模拟成交")
            st.subheader("最近行情")
            from .result_presentations import render_recent_quotes
            render_recent_quotes(backtest_frame, key='watch_recent_quotes')
    with strategy_tab:
        performance_metrics()
        st.write(strategy.description)
        if analysis_mode == "等权组合":
            st.subheader("组合配置")
            st.dataframe(pd.DataFrame([{"标的": key, "资金权重": f"{value:.2%}"}
                                      for key, value in portfolio_result.weights.items()]
                                     + [{"标的": "现金", "资金权重": f"{portfolio_result.cash_weight:.2%}"}]), width="stretch", hide_index=True)
            st.plotly_chart(
                build_equity_chart(portfolio_frame, "组合策略净值与基准对比"),
                width="stretch",
                key=build_equity_chart_key("portfolio-strategy"),
            )
            st.caption("各标的使用固定资金权重；无持仓信号的资金保留现金。组合成本按各标的权重与换手扣除，不是动态再平衡的真实账户。")
            st.plotly_chart(
                build_portfolio_contribution_chart(portfolio_contribution_frame),
                width="stretch",
                key="portfolio-strategy-contribution",
            )
            st.subheader("逐股票表现")
            st.dataframe(symbol_comparison, width="stretch", hide_index=True)
            st.subheader("组合个股研究")
            drill_symbol = st.selectbox("分析组合中的个股", list(portfolio_frames), key="portfolio_drill_symbol", filter_mode=None)
            drill = run_single_stock_research(portfolio_frames[drill_symbol], strategy_key=strategy.key,
                                             params=strategy_params, transaction_cost=transaction_cost)
            drill_payload = build_ohlcv_payload(drill.frame, symbol=drill_symbol, events=drill.trade_events,
                                               indicator_config=registry_indicator_config,
                                               min_visible_bars=min(30, len(drill.frame)),
                                               data_context=build_market_detail_context(
                                                   drill.frame, symbol=drill_symbol,
                                                   source="历史行情 + 离线研究模拟",
                                                   price_mode=adjusted if data_source == "本地行情" else "synthetic" if synthetic else "imported",
                                                   price_unit="元/股" if data_source == "本地行情" else "源数据单位",
                                                   volume_unit="源文件单位",
                                               ))
            drill_height = 520 + 126 * len(registry_panel_keys)
            components.html(chart_bridge_html(drill_payload, height=drill_height), height=drill_height, scrolling=False)
            render_paged_table(build_readable_trades(drill.trade_events), key='dashboard_drill_trades')
            st.subheader("组合成交事件与公开解释")
            if portfolio_trade_frame.empty:
                st.info("当前组合参数和区间没有产生模拟成交事件。可以扩大日期范围或调整策略参数。")
            else:
                render_paged_table(portfolio_trade_frame, key='dashboard_portfolio_trades')
            st.subheader("组合日状态")
            display_frame = portfolio_frame[
                    [
                        "trade_date",
                        "daily_return",
                        "equity",
                        "drawdown",
                        "gross_exposure",
                        "cash_weight",
                        "active_symbols",
                    ]
                ].tail(60).copy()
            display_frame.attrs = {}
            st.dataframe(
                display_frame,
                width="stretch",
                hide_index=True,
            )
        else:
            benchmark_return = float(backtest_frame["benchmark_equity"].iloc[-1] - 1)
            comparison = st.columns(3)
            comparison[0].metric("买入持有收益", format_metric(benchmark_return, True))
            comparison[1].metric("相对买入持有", format_metric(metrics["total_return"] - benchmark_return, True))
            comparison[2].metric("单次换手成本", format_metric(transaction_cost, True))
            st.metric("累计成本", format_metric(float(performance_metrics_view["total_cost"]), True))
            def _explain_655():
                st.write('信号次日收盘执行，按持仓换手扣除设定成本。买卖事件为离线模拟。')
            help_link('回测方法', _explain_655, key='watch_workspace_help_655')
            events = backtest_frame.attrs.get("trade_events", [])
            st.plotly_chart(build_performance_chart(single_performance_frame, nav='equity',
                benchmark='benchmark_equity', title='单股净值与回撤', revision=submission.key_id),
                width='stretch', key=build_equity_chart_key('single-equity'), config=CHART_CONFIG)
            details = build_strategy_result_details(events, initial_cash=100_000.0)
            detail_summary = details["summary"]
            event_columns = st.columns(4)
            event_columns[0].metric("信号", str(detail_summary["signals"]))
            event_columns[1].metric("订单意图", str(detail_summary["orders"]))
            event_columns[2].metric("成交", str(detail_summary["fills"]))
            event_columns[3].metric("拒单", str(detail_summary["rejected_orders"]))
            st.subheader("结果诊断")
            diagnostics_table = pd.DataFrame([
                {"诊断项": key, "状态": value}
                for key, value in build_strategy_result_diagnostics(
                    single_stock_research.diagnostics,
                    details,
                    single_performance,
                ).items()
            ])
            diagnostics_table = diagnostics_table.astype(str)
            st.dataframe(diagnostics_table, width="stretch", hide_index=True)
            st.subheader("交易详情与公开解释")
            st.caption("信号、订单意图、成交和拒单来自同一条离线回测事件链；成交价格是回测价格，不是实盘报价。")
            detail_frame = build_strategy_result_trade_frame(details)
            if detail_frame.empty:
                st.info("当前参数和区间没有产生信号或订单。可以扩大日期范围或调整策略参数。")
            else:
                detail_page = 0
                if len(detail_frame) > 100:
                    pages = (len(detail_frame) + 99) // 100
                    detail_page = int(st.number_input('交易详情页码', 1, pages, 1)) - 1
                    st.caption(f'共 {len(detail_frame):,} 行；每页 100 行，归档保留全部事件。')
                displayed_detail = page_frame(detail_frame, page=detail_page)
                detail_view = st.dataframe(
                    displayed_detail,
                    width="stretch",
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun",
                    key="single-strategy-result-details",
                )
                selected_rows = list(getattr(getattr(detail_view, "selection", None), "rows", []) or [])
                if selected_rows:
                    selected = displayed_detail.iloc[int(selected_rows[0])]
                    selected_event_id = build_strategy_focus_event_id(selected)
                    current_focus = st.session_state.get("single_strategy_focus", {})
                    if selected_event_id and current_focus != {"cache_key": submission.key_id, "event_id": selected_event_id}:
                        st.session_state["single_strategy_focus"] = {
                            "cache_key": submission.key_id,
                            "event_id": selected_event_id,
                        }
                        st.rerun()
                    st.info(
                        f"已选事件：{selected['方向']} · {selected['状态']} · "
                        f"{selected['执行日期']} · {selected['原因']} · "
                        f"信号ID {selected['信号ID']} · 订单ID {selected['订单ID']} · 成交ID {selected['成交ID']}"
                    )
            position_frame = build_strategy_result_position_frame(details)
            with st.expander("现金与持仓快照", expanded=False):
                if position_frame.empty:
                    st.info("当前区间没有成交，因此没有现金与持仓变动快照。")
                else:
                    render_paged_table(position_frame, key='dashboard_positions')
            archive = create_strategy_archive(
                strategy={"strategy_id": strategy.key, "name": strategy.name, "config": single_stock_research.strategy_config},
                dataset={
                    "symbol": str(symbol),
                    "rows": int(len(backtest_frame)),
                    "coverage_start": str(backtest_frame["trade_date"].min().date()),
                    "coverage_end": str(backtest_frame["trade_date"].max().date()),
                    "content_hash": hashlib.sha256(
                        backtest_frame[["trade_date", "close"]].to_csv(index=False).encode("utf-8")
                    ).hexdigest(),
                },
                execution={
                    "mode": "offline_research_simulation",
                    "execution_lag_days": int(single_stock_research.strategy_config["execution_lag_days"]),
                    "execution_policy": str(single_stock_research.strategy_config["execution_policy"]),
                    "execution_policy_label": str(single_stock_research.strategy_config["execution_policy_label"]),
                    "transaction_cost": float(transaction_cost),
                    "slippage_bps": 0.0,
                    "execution_policy": "next_day_close",
                    "initial_cash": 100_000.0,
                },
                result={"performance": single_performance, "details": details},
                limitations=[
                    "离线历史研究模拟，不代表实时行情或真实成交",
                    "不连接 QMT、券商、账户或实盘提交系统",
                    "初始资金和成交数量为展示口径，不是账户资产记录",
                ],
            )
            st.download_button(
                "下载本地策略结果归档",
                data=json.dumps(archive, ensure_ascii=False, indent=2),
                file_name=f"{symbol}-{strategy.key}-strategy-archive.json",
                mime="application/json",
                key="download-single-strategy-archive",
            )
            with st.expander("研究参数与数据诊断", expanded=False):
                param_labels = {str(item["key"]): str(item["label"]) for item in strategy.parameters}
                st.dataframe(pd.DataFrame([{"参数": param_labels.get(key, key), "值": value}
                                          for key, value in strategy_params.items()]), width="stretch", hide_index=True)
                st.dataframe(build_research_diagnostics_frame(single_stock_research), width="stretch", hide_index=True)
    with robustness_tab:
        st.subheader("稳健性与策略比较")
        if analysis_mode == "等权组合":
            if portfolio_robustness_report.empty:
                st.info("当前组合没有足够的有效场景，暂时无法生成稳健性报告。")
            else:
                st.caption("组合稳健性报告固定比较当前组合构成、窗口和成本场景；不把单一最优结果当作稳定结论。")
                st.dataframe(portfolio_robustness_report, width="stretch", hide_index=True)
        elif robustness_report.empty:
            st.info("当前日期范围没有足够的有效行情场景，暂时无法生成稳健性报告。")
        else:
            summary_columns = st.columns(6)
            summary_columns[0].metric("场景数量", str(robustness_summary["scenario_count"]))
            summary_columns[1].metric("年化收益中位数", format_metric(float(robustness_summary["annual_return_median"]), True))
            summary_columns[2].metric("最差年化收益", format_metric(float(robustness_summary["annual_return_min"]), True))
            summary_columns[3].metric("最差最大回撤", format_metric(float(robustness_summary["max_drawdown_worst"]), True))
            summary_columns[4].metric("成本敏感度", format_metric(float(robustness_summary["cost_sensitivity"]), True))
            summary_columns[5].metric("稳定性标签", str(robustness_summary["stability_label"]))

            st.plotly_chart(build_robustness_chart(robustness_report), width="stretch", key="robustness-scenarios")
            report_table = robustness_report.rename(
                columns={
                    "strategy_name": "策略",
                    "window_bars": "历史窗口（根）",
                    "transaction_cost": "单次成本",
                    "observations": "样本数",
                    "total_return": "区间收益",
                    "annual_return": "年化收益",
                    "annual_volatility": "年化波动",
                    "sharpe": "夏普比率",
                    "max_drawdown": "最大回撤",
                    "trades": "交易次数",
                    "event_count": "事件数",
                }
            ).copy()
            for column in ("单次成本", "区间收益", "年化收益", "年化波动", "最大回撤"):
                report_table[column] = report_table[column].map(lambda value: f"{float(value):.2%}")
            st.dataframe(report_table, width="stretch", hide_index=True)

            st.subheader("公开演示策略比较")
            st.caption("比较使用同一历史窗口和成本口径，展示中位数与最差回撤，不把单次最优结果当作稳定结论。")
            st.plotly_chart(
                build_strategy_comparison_chart(strategy_comparison),
                width="stretch",
                key="strategy-comparison-report",
            )
            comparison_table = strategy_comparison.rename(
                columns={
                    "strategy_name": "策略",
                    "annual_return": "年化收益中位数",
                    "sharpe": "夏普中位数",
                    "max_drawdown": "最差最大回撤",
                    "trades": "交易次数中位数",
                    "stability_label": "稳定性标签",
                }
            ).copy()
            for column in ("年化收益中位数", "最差最大回撤"):
                comparison_table[column] = comparison_table[column].map(lambda value: f"{float(value):.2%}")
            comparison_table["夏普中位数"] = comparison_table["夏普中位数"].map(lambda value: f"{float(value):.2f}")
            st.dataframe(comparison_table, width="stretch", hide_index=True)

            st.subheader("滚动样本外与参数敏感性")
            validation_left, validation_right = st.columns(2)
            with validation_left:
                wf = walk_forward_report(frame, strategy.key, train_bars=min(252, max(30, len(frame) // 2)),
                                          test_bars=min(63, max(10, len(frame) // 6)), params=strategy_params,
                                          transaction_cost=transaction_cost)
                if wf.empty:
                    st.info("当前区间不足以形成历史上下文/测试滚动窗口。")
                else:
                    st.caption("固定参数的滚动样本外切片；历史期仅用于指标预热，不重新训练。")
                    display_wf = wf.rename(columns={'训练开始': '上下文开始', '训练截止': '上下文截止'}).copy()
                    for column in ("测试收益", "年化收益", "最大回撤"):
                        display_wf[column] = display_wf[column].map(lambda value: f"{float(value):.2%}")
                    display_wf["夏普"] = display_wf["夏普"].map(lambda value: f"{float(value):.2f}")
                    st.dataframe(display_wf, width="stretch", hide_index=True)
            with validation_right:
                sensitivity = sensitivity_report(frame, strategy.key, params=strategy_params, transaction_cost=transaction_cost)
                display_sensitivity = sensitivity.copy()
                for column in ("区间收益", "年化收益", "最大回撤"):
                    display_sensitivity[column] = display_sensitivity[column].map(lambda value: f"{float(value):.2%}")
                display_sensitivity["夏普"] = display_sensitivity["夏普"].map(lambda value: f"{float(value):.2f}")
                st.caption("参数邻域与额外滑点压力；这是敏感性分析，不是自动选优。")
                st.dataframe(display_sensitivity, width="stretch", hide_index=True)

            st.subheader("成本、滑点与执行政策敏感性")
            st.caption(f"场景数量：{len(execution_sensitivity)} · 基准场景：当前成本、0bp 滑点、下一交易日收盘")
            st.caption(
                "每个场景只改变一个研究假设；基准为当前成本、0bp 滑点和下一交易日收盘。"
                "执行政策是离线研究假设，不代表真实成交，也不自动选择最优场景。"
            )
            st.caption("结果字段：区间收益、最大回撤、总成本、相对基准收益差、相对基准回撤差、相对基准成本差。")
            execution_table = execution_sensitivity.rename(
                columns={
                    "scenario_id": "场景ID",
                    "changed_assumption": "变化假设",
                    "assumption_change": "假设变化",
                    "status": "状态",
                    "transaction_cost": "单次成本",
                    "slippage_bps": "额外滑点(bp)",
                    "execution_policy_label": "执行政策",
                    "trades": "交易次数",
                    "turnover": "换手量",
                    "total_return": "区间收益",
                    "max_drawdown": "最大回撤",
                    "total_cost": "总成本",
                    "delta_total_return": "相对基准收益差",
                    "delta_max_drawdown": "相对基准回撤差",
                    "delta_total_cost": "相对基准成本差",
                }
            ).copy()
            for column in ("单次成本", "区间收益", "最大回撤", "总成本", "相对基准收益差", "相对基准回撤差", "相对基准成本差"):
                if column in execution_table:
                    execution_table[column] = execution_table[column].map(
                        lambda value: "--" if pd.isna(value) else f"{float(value):.2%}"
                    )
            if "额外滑点(bp)" in execution_table:
                execution_table["额外滑点(bp)"] = execution_table["额外滑点(bp)"].map(
                    lambda value: "--" if pd.isna(value) else f"{float(value):.0f}"
                )
            # This is a presentation table. Converting every visible value to
            # text keeps mixed empty/number states Arrow-serializable without
            # changing the numeric sensitivity contract above.
            execution_table = pd.DataFrame({
                column: execution_table[column].map(lambda value: "--" if pd.isna(value) else str(value))
                for column in execution_table.columns
            })
            st.dataframe(execution_table, width="stretch", hide_index=True)

            st.subheader("公开限制说明")
            for limitation in explain_report_limitations(
                source_kind="synthetic_demo" if synthetic else "user_import_or_local",
                execution_model="next_day_close",
            ):
                st.write(f"• {limitation}")
    with projects_tab:
        st.subheader("研究项目目录")
        st.caption("这些项目来自仓库中的模型、回测和研究文档，展示平台只读呈现研究成果。")
        st.caption("可交互运行：本页单股与等权组合策略；研究项目卡：模型研究方法、验证证据与简历表述。")
        for card in build_strategy_showcases(REPO_ROOT, public_only=PUBLIC_MODE):
            render_strategy_showcase_card(card)
    with data_tab:
        st.write("标准字段已识别，可继续导入自己的日线文件进行同样分析。")
        if analysis_mode == "等权组合":
            st.dataframe(pd.DataFrame([{"标的数量": len(selected_symbols), "日期记录": len(portfolio_frame),
                                      "起始日期": str(portfolio_frame["trade_date"].min().date()),
                                      "截止日期": str(portfolio_frame["trade_date"].max().date())}]), width="stretch", hide_index=True)
        else:
            quality = build_data_quality_report(frame)
            st.dataframe(pd.DataFrame([
                {"检查项": "数据质量", "结果": quality["status"]},
                {"检查项": "记录数", "结果": str(len(frame))},
                {"检查项": "起始日期", "结果": str(frame["trade_date"].min().date())},
                {"检查项": "截止日期", "结果": str(frame["trade_date"].max().date())},
                {"检查项": "价格逻辑异常", "结果": str(quality["invalid_ohlc_rows"])},
            ]), width="stretch", hide_index=True)
            with st.expander("原始字段与行情明细", expanded=False):
                raw = frame.tail(60).copy()
                raw.attrs = {}
                st.dataframe(raw, width="stretch", hide_index=True)
    with experiments_tab:
        experiment_source = pd.concat(list(portfolio_frames.values()), ignore_index=True) if analysis_mode == "等权组合" else full_history
        spec = {
            "mode": "portfolio" if analysis_mode == "等权组合" else "single",
            "symbols": list(portfolio_frames) if analysis_mode == "等权组合" else [str(symbol)],
            "strategy_key": strategy.key, "params": strategy_params,
            "transaction_cost": transaction_cost,
            "start_date": str(portfolio_frame["trade_date"].min().date()) if analysis_mode == "等权组合" else str(backtest_frame["trade_date"].min().date()),
        "end_date": str(portfolio_frame["trade_date"].max().date()) if analysis_mode == "等权组合" else str(backtest_frame["trade_date"].max().date()),
        "lookback": lookback,
        "weights": portfolio_result.weights if analysis_mode == "等权组合" else {},
        "cash_weight": portfolio_result.cash_weight if analysis_mode == "等权组合" else 0.0,
        "source_kind": "synthetic_demo" if synthetic else "local_or_import",
        "price_mode": adjusted if data_source == "本地行情" else "source_unspecified",
        "indicator_config": registry_indicator_config,
    }
        from .state_paths import state_root
        render_experiments(experiment_source, spec, state_root() / 'workbench_experiments')
