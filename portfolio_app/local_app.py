from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from portfolio_app.research_charts import style_chart, build_comparison_chart, build_metric_bars, build_time_series_chart, PALETTE, CHART_CONFIG
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

from portfolio_app.capability_mode import CapabilityMode, capabilities_for, resolve_capability_mode
from portfolio_app.backtest import compare_symbol_backtests, run_backtest, run_equal_weight_portfolio
from portfolio_app.chart_bridge import chart_bridge_html
from portfolio_app.chart_payload import build_ohlcv_payload
from portfolio_app.data import (
    build_data_quality_report,
    build_market_summary,
    build_symbol_return_summary,
    list_local_symbols,
    load_local_symbol,
    read_market_file,
)
from portfolio_app.data_catalog import build_dataset_manifest
from portfolio_app.data_center import DataCenter
from portfolio_app.data_workflow import DataWorkflowStep, DataWorkflowState, build_data_workflow, next_data_workflow
from portfolio_app.dataset_registry import RegistrationConfirmationRequired
from portfolio_app.evidence import (
    build_model_comparison_rows,
    build_research_artifact_manifest,
    load_all_model_evidence,
    load_model7_evidence,
)
from portfolio_app.indicators import (
    INDICATOR_REGISTRY,
    add_chart_indicators,
    build_default_indicator_config,
    normalize_indicator_config,
    order_indicator_config,
    validate_indicator_layout,
)
from portfolio_app.projects import RESEARCH_PROJECTS, get_evidence_layers, get_project_detail
from portfolio_app.portfolio_content import build_portfolio_content, list_public_artifacts
from portfolio_app.research import run_portfolio_research
from portfolio_app.reports import (
    build_portfolio_robustness_report,
    build_robustness_report,
    build_robustness_summary,
    build_strategy_comparison,
    explain_report_limitations,
)
from portfolio_app.validation import sensitivity_report, walk_forward_report
from portfolio_app.sensitivity import build_single_stock_sensitivity_report
from portfolio_app.research import build_research_diagnostics_frame, run_single_stock_research
from portfolio_app.single_stock_performance import build_single_stock_performance
from portfolio_app.strategy_result_details import (
    build_strategy_result_details,
    build_strategy_result_payload,
    create_strategy_archive,
)
from portfolio_app.showcase import build_strategy_showcases
from portfolio_app.strategies import STRATEGIES, generate_signal, normalize_strategy_params
from portfolio_app.stock_view import build_single_stock_snapshot, build_stock_quote_table, build_readable_trades, build_market_detail_context, number
from portfolio_app.stock_catalog import build_market_view, build_stock_catalog, search_stock_catalog
from portfolio_app.watchlist import WatchlistStore
from portfolio_app.market_periods import build_market_window
from portfolio_app.workbench_controls import (
    render_allocation, render_import_preview,
    render_indicator_template_controls, serialize_indicator_template,
)
from portfolio_app.experiment_view import render_experiments
from portfolio_app.evidence_view import annual_oos_table, evidence_table
from portfolio_app.research_run_adapter import draft_payload, run_explicit, sync_draft
from portfolio_app.research_diagnostics import show_safe_error
from portfolio_app.research_run_state import RunStatus
from portfolio_app.research_result_cache import ResearchResultCache, build_data_fingerprint, build_research_cache_key
from portfolio_app.research_submission import ResearchSubmission, current_submission
from portfolio_app.research_jobs import ResearchJobCoordinator
from portfolio_app.ui_copy import (
    format_research_status,
)
from portfolio_app.context_status_bar import render_context_status_bar
from portfolio_app.watch_workspace import render_watch_workspace, render_watch_workspace_body
from portfolio_app.data_workspace import render_data_workspace, render_data_workspace_body
from portfolio_app.research_workspace import render_research_workspace, render_research_workspace_body
from portfolio_app.factor_workspace_view import render_factor_workspace
from portfolio_app.archive_workspace import render_experiments_workspace, render_showcase_workspace
from portfolio_app.workspace_navigation import (
    default_workspace_state,
    navigation_query,
    resolve_workspace_query,
    view_target,
)
from portfolio_app.workspace_router import WORKSPACE_ROUTES, switch_workspace
from portfolio_app.workbench_theme import apply_workbench_theme, render_sidebar_brand


REPO_ROOT = Path(__file__).resolve().parents[1]
# Keep pure chart/data helpers importable for tests and adapters. The actual
# local workbench entrypoint validates the environment again in ``main``.
_CAPABILITY_MODE = resolve_capability_mode()
CAPABILITIES = capabilities_for(_CAPABILITY_MODE)
DEFAULT_DATA_ROOT = Path(
    os.environ.get("PORTFOLIO_DATA_ROOT", str(REPO_ROOT / "data"))
    if CAPABILITIES.can_read_local_market
    else REPO_ROOT / "data"
)
PUBLIC_MODE = CAPABILITIES.public_only
SAMPLE_ROOT = Path(__file__).resolve().parent / "sample_data"
DISPLAY_PRIVATE_RAW_EVIDENCE = (
    CAPABILITIES.can_display_private_evidence
    and os.environ.get("PORTFOLIO_RESEARCH_EVIDENCE", "redacted").lower() == "private_raw"
)


def _research_result_cache() -> ResearchResultCache:
    cache = st.session_state.get("dashboard_research_cache")
    if not isinstance(cache, ResearchResultCache):
        cache = ResearchResultCache()
        st.session_state["dashboard_research_cache"] = cache
    return cache


def build_workspace_selector_kwargs(active_workspace: str, *, synced: bool) -> dict[str, object]:
    """Avoid passing Streamlit's default index with an existing session value."""

    kwargs: dict[str, object] = {
        "options": [route.id for route in WORKSPACE_ROUTES],
        "format_func": {route.id: f"{route.label_zh} / {route.label_en}" for route in WORKSPACE_ROUTES}.get,
        "key": "workspace_route_selector",
        "width": "stretch",
    }
    if not synced:
        kwargs["index"] = [route.id for route in WORKSPACE_ROUTES].index(active_workspace)
    return kwargs


def _research_job_coordinator() -> ResearchJobCoordinator:
    coordinator = st.session_state.get("dashboard_research_jobs")
    if not isinstance(coordinator, ResearchJobCoordinator):
        coordinator = ResearchJobCoordinator(_research_result_cache())
        st.session_state["dashboard_research_jobs"] = coordinator
    return coordinator


def _research_data_version(frames: dict[str, pd.DataFrame]) -> str:
    parts: list[pd.DataFrame] = []
    for symbol, frame in sorted(frames.items()):
        part = frame.copy()
        if "symbol" not in part.columns:
            part.insert(0, "symbol", symbol)
        parts.append(part)
    return build_data_fingerprint(pd.concat(parts, ignore_index=True, sort=False))


def _research_processing_payload(
    *,
    analysis_mode: str,
    symbols: list[str],
    strategy_key: str,
    strategy_params: dict[str, object],
    transaction_cost: float,
    date_start: object,
    date_end: object,
    lookback: int,
    target_weights: dict[str, float] | None,
    cash_weight: float,
    indicator_config: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "analysis_mode": analysis_mode,
        "symbols": list(symbols),
        "strategy_key": strategy_key,
        "strategy_params": dict(strategy_params),
        "transaction_cost": float(transaction_cost),
        "date_start": str(pd.Timestamp(date_start).date()),
        "date_end": str(pd.Timestamp(date_end).date()),
        "lookback": int(lookback),
        "target_weights": dict(target_weights or {}),
        "cash_weight": float(cash_weight),
        "indicator_config": indicator_config,
    }


def evidence_display_public_only() -> bool:
    """Keep portfolio-facing pages redacted unless raw evidence is explicitly opted in."""
    return PUBLIC_MODE or not DISPLAY_PRIVATE_RAW_EVIDENCE


def safe_evidence_source_label(public_only: bool) -> str:
    return "curated research summary" if public_only else "private research workspace"


def public_project_text(value: str, public_only: bool) -> str:
    """Keep project wording useful while removing private runtime vocabulary."""
    if not public_only:
        return value
    replacements = {
        "目标仓位": "组合配置意图",
        "目标文件": "运行状态文件",
        "targets": "运行状态记录",
        "资金管理链路": "组合管理流程",
    }
    text = value
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    return text


def _format_showcase_metric(key: str, value: object) -> str:
    if value is None:
        return "未提供"
    numeric = float(value)
    if key in {"annual_return", "max_drawdown"}:
        return f"{numeric:.2%}"
    return f"{numeric:.2f}"


def _render_research_result_view(card: dict[str, object]) -> None:
    """Render normalized local artifacts while keeping evidence layers explicit."""
    view = card.get("result_view", {})
    if not view:
        return
    curve = view.get("curve", [])
    curve_status = view.get("curve_status", "unavailable")
    if curve:
        curve_frame = pd.DataFrame(curve)
        figure = go.Figure(
            go.Scatter(
                x=curve_frame["date"],
                y=curve_frame["value"],
                mode="lines",
                name="归一化净值",
                line={"color": "#2864D7", "width": 2},
                customdata=curve_frame[["drawdown"]].to_numpy(),
                hovertemplate="%{x}<br>净值=%{y:.3f}<br>回撤=%{customdata[0]:.2%}<extra></extra>",
            )
        )
        figure.update_layout(
            height=320,
            yaxis_title="归一化净值",
            xaxis_title="交易日",
            hovermode="x unified",
            margin={"l": 15, "r": 15, "t": 25, "b": 35},
        )
        st.subheader("实际日净值曲线")
        style_chart(figure, title=figure.layout.title.text or '', height=figure.layout.height or 360)
        st.plotly_chart(figure, width="stretch", key=f"research-result-curve-{card['model_id']}")
        st.caption(f"读取真实日频产物，共 {len(curve_frame):,} 个观测点；净值已归一化，未暴露账户规模。")
    elif curve_status == "not_in_reviewed_bundle":
        st.info("审核公开包没有逐日曲线；这里不从年化指标反推曲线。")
    else:
        st.warning("当前正式产物没有可安全展示的逐日曲线。")

    cost_cases = view.get("cost_cases", [])
    if cost_cases:
        rows = []
        for case in cost_cases:
            metrics = case.get("metrics", {})
            rows.append(
                {
                    "情景": case.get("case", ""),
                    "区间": case.get("period", ""),
                    "年化收益": _format_showcase_metric("annual_return", metrics.get("annual_return")),
                    "夏普": _format_showcase_metric("sharpe", metrics.get("sharpe")),
                    "最大回撤": _format_showcase_metric("max_drawdown", metrics.get("max_drawdown")),
                    "交易日/折叠": str(case.get("trade_days", case.get("days", ""))),
                }
            )
        st.subheader("成本与验证情景")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    annual_oos = view.get("annual_oos", [])
    if annual_oos:
        rows = []
        for item in annual_oos:
            metrics = item.get("metrics", {})
            rows.append(
                {
                    "年度": item.get("year", ""),
                    "区间": item.get("period", ""),
                    "交易日数": item.get("days", ""),
                    "年化收益": _format_showcase_metric("annual_return", metrics.get("annual_return")),
                    "夏普": _format_showcase_metric("sharpe", metrics.get("sharpe")),
                    "最大回撤": _format_showcase_metric("max_drawdown", metrics.get("max_drawdown")),
                }
            )
        st.subheader("年度样本外结果")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    blocked = view.get("blocked_trade_summary", {})
    if blocked:
        st.subheader("执行约束审计")
        st.dataframe(pd.DataFrame([blocked]), width="stretch", hide_index=True)

    gate = view.get("research_gate", "not_reported")
    if gate == "review_required":
        st.warning("该候选仍处于 review_required，不代表已通过最终研究门禁或生产配置。")
    elif gate == "validated_with_separate_runtime_layer":
        st.info("模型 7 已将选择验证、latest 本地回测和运行状态分层；运行状态不计入历史收益证据。")

    explanation = view.get("execution_explanation", {})
    if explanation:
        st.subheader("买入、退出与组合解释")
        st.dataframe(
            pd.DataFrame(
                [
                    {"买入/进入": explanation.get("entry", ""), "退出/调仓": explanation.get("exit", ""), "执行窗口": explanation.get("execution_window", ""), "组合约束": explanation.get("portfolio_constraints", "")}
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        trade_status = view.get("trade_evidence_status", "not_available")
        if trade_status == "runtime_symbols_private":
            st.caption("模型 7 的标的级运行状态保持私有；页面只展示组合层解释和历史回测结果。")
        elif trade_status == "aggregate_only":
            st.caption("当前策略公开为聚合结果与执行口径，没有公开逐笔买卖记录。")
        else:
            st.caption("当前策略保留执行审计摘要，可继续下钻到约束拦截统计。")


def render_strategy_showcase_card(card: dict[str, object], *, expanded: bool = False) -> None:
    """Render one disclosure-safe project card from the shared showcase contract."""
    title = f"{card['title']} · {card['category']} · {card['status_label']}"
    with st.expander(title, expanded=expanded):
        st.write(card["summary"])
        st.markdown("**研究问题**")
        st.write(card["research_question"])
        st.markdown("**已完成工作**")
        for item in card["work_completed"]:
            st.write(f"• {item}")
        st.markdown("**研究方法**")
        st.write("、".join(card["methods"]))
        st.markdown("**验证状态与代表性指标**")
        headline = card.get("metrics", {})
        if headline:
            metric_columns = st.columns(len(headline))
            metric_labels = {
                "annual_return": "年化收益",
                "sharpe": "夏普",
                "max_drawdown": "最大回撤",
            }
            for column, (key, value) in zip(metric_columns, headline.items()):
                column.metric(metric_labels.get(key, key), _format_showcase_metric(key, value))
        else:
            st.info("当前没有可展示的公开聚合指标。")
        st.dataframe(evidence_table(card), width="stretch", hide_index=True)
        _render_research_result_view(card)
        layers_with_metrics = [layer for layer in card["evidence_layers"] if layer.get("metrics")]
        if len(layers_with_metrics) > 1 and card["model_id"] != "model7":
            figure = build_comparison_chart([layer['key'] for layer in layers_with_metrics],
                [(title, [layer['metrics'].get(metric) for layer in layers_with_metrics])
                 for metric, title in [('annual_return','年化收益'), ('max_drawdown','最大回撤')]], title='研究情景')
            style_chart(figure, title=figure.layout.title.text or '', height=figure.layout.height or 360)
            st.plotly_chart(figure, width="stretch", key=f"evidence-scenarios-{card['model_id']}")
        if card["model_id"] == "model3":
            annual = annual_oos_table(REPO_ROOT)
            st.subheader("年度样本外表现")
            if not annual.empty:
                figure = build_metric_bars(annual, category='年度', value='年化收益', title='年度样本外收益')
                style_chart(figure, title=figure.layout.title.text or '', height=figure.layout.height or 360)
                st.plotly_chart(figure, width="stretch", key="showcase-annual-oos")
                display = annual.copy()
                display["年化收益"] = display["年化收益"].map(lambda value: f"{value:.2%}")
                st.dataframe(display, width="stretch", hide_index=True)
        if not card.get("result_view", {}).get("curve"):
            st.caption("逐日净值曲线：当前展示层没有可用曲线。这里不从聚合收益推算历史曲线；运行状态也不作为收益证据。")
        for layer in card["evidence_layers"]:
            layer_title = f"{layer['label']} · {layer['status_label']}"
            st.markdown(f"**{layer_title}**")
            st.write(f"区间：{layer['period']}")
            layer_metrics = layer.get("metrics", {})
            if layer_metrics:
                st.write("；".join(f"{key}={_format_showcase_metric(key, value)}" for key, value in layer_metrics.items()))
            st.caption(f"来源：{layer['source_label']}")
            if layer.get("limitations"):
                st.caption(f"限制：{layer['limitations']}")
        st.markdown("**研究验证**")
        for item in card["validation"]:
            st.write(f"• {item}")
        st.markdown("**研究限制**")
        for item in card["limitations"]:
            st.write(f"• {item}")
        st.markdown("**公开边界**")
        st.write("页面只保留研究问题、方法摘要、聚合结果、验证状态和限制；核心代码、精确参数、原始数据、持仓和账户信息不在展示层。")
        st.markdown("**代表性研究产物**")
        for artifact in card["artifacts"]:
            if artifact["available"]:
                artifact_path = REPO_ROOT / str(artifact["path"])
                st.download_button(
                    f"下载{artifact['label']}（{artifact['suffix']}）",
                    data=artifact_path.read_bytes(),
                    file_name=artifact_path.name,
                    mime="application/octet-stream",
                    key=f"showcase_download_{card['model_id']}_{artifact['path']}",
                )
            else:
                st.caption(f"暂不可用：{artifact['label']}")


st.set_page_config(page_title="量化研究与可视化平台", page_icon="Q", layout="wide", initial_sidebar_state="expanded")


@st.cache_data(show_spinner=False)
def cached_symbols(data_root: str, adjusted: str = "qfq") -> list[str]:
    return list_local_symbols(data_root, adjusted)


@st.cache_data(show_spinner=False)
def cached_symbol_names(data_root: str) -> dict[str, str]:
    path = Path(data_root) / "stock_basic.csv"
    if not path.is_file():
        return {}
    try:
        basic = pd.read_csv(path, dtype=str, usecols=["ts_code", "name"])
    except (ValueError, OSError, UnicodeError):
        return {}
    return dict(zip(basic["ts_code"], basic["name"]))


@st.cache_data(show_spinner=False)
def cached_stock_catalog(data_root: str, adjusted: str = "qfq") -> list[dict[str, object]]:
    """Build the directory from filenames and the name table.

    The directory is intentionally lazy: reading thousands of full Parquet
    histories merely to populate a search box makes the local page unusable.
    The selected symbol is loaded later, where its real latest quote is built
    from the actual history.
    """
    names = cached_symbol_names(data_root)
    return [
        {
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "latest_date": None,
            "close": None,
            "change": None,
            "price_unit": "unknown",
            "volume_unit": "unknown",
            "observations": None,
        }
        for symbol in cached_symbols(data_root, adjusted)
    ]


def watchlist_store() -> WatchlistStore:
    from portfolio_app.state_paths import state_root
    return WatchlistStore(state_root() / "watchlist.json")


def _render_pure_stock_view(
    frame: pd.DataFrame,
    *,
    symbol: str,
    name: str,
    source_label: str,
    price_mode: str,
    price_unit: str,
    volume_unit: str,
    indicator_config: list[dict[str, object]],
    panel_count: int,
) -> None:
    """Render historical quotes before any strategy research is submitted."""
    if build_data_quality_report(frame)['status'] != '通过':
        st.error('行情质量检查未通过，请在数据工作区检查价格、日期与成交记录。')
        return
    daily_view = build_market_view(
        frame,
        symbol=symbol,
        name=name,
        price_unit=price_unit,
        volume_unit=volume_unit,
    )
    if daily_view["status"] != "READY":
        st.info(str(daily_view["message"]))
        return
    st.subheader(f"{name} {symbol}".strip())
    available_dates = pd.to_datetime(frame["trade_date"], errors="coerce").dropna()
    if available_dates.empty:
        st.info("当前数据没有可用交易日期。")
        return
    period_column, date_column = st.columns([1, 2])
    period = period_column.selectbox(
        "行情周期",
        ["1d", "1w", "1m"],
        format_func={"1d": "日K", "1w": "周K", "1m": "月K"}.get,
        key=f"market_period_{symbol}", filter_mode=None,
    )
    actual = st.session_state.get('_actual_context_watch')
    if actual:
        actual['period'] = '1mo' if period == '1m' else period
    market_dates = date_column.date_input(
        "行情日期范围",
        value=(available_dates.min().date(), available_dates.max().date()),
        min_value=available_dates.min().date(),
        max_value=available_dates.max().date(),
        key=f"market_date_range_{symbol}",
    )
    if not isinstance(market_dates, tuple) or len(market_dates) != 2:
        st.info("请选择完整的行情起止日期。")
        return
    market_window = build_market_window(
        frame,
        period=period,
        start=market_dates[0],
        end=market_dates[1],
    )
    if market_window["status"] != "READY":
        st.info(str(market_window["message"]))
        return
    display_frame = market_window["frame"]
    if actual:
        actual['as_of'] = str(market_window['window']['end'])[:10]
    incomplete = int((~display_frame["is_complete"].astype(bool)).sum()) if "is_complete" in display_frame else 0
    period_label = {"1d": "日K", "1w": "周K", "1m": "月K"}[period]
    st.caption(f"{period_label} · {market_window['window']['start']} — {market_window['window']['end']}")
    latest = display_frame.iloc[-1]
    close = number(latest.get("close"))
    previous = number(latest.get("pre_close"))
    if previous is None and len(display_frame) > 1:
        previous = number(display_frame.iloc[-2].get("close"))
    quote = {
        "close": close,
        "previous_close": previous,
        "change": close / previous - 1 if close is not None and previous not in (None, 0) else None,
        "high": number(latest.get("high")),
        "low": number(latest.get("low")),
    }
    quote_columns = st.columns(5)
    quote_columns[0].metric("最近收盘", format_metric(quote["close"]))
    quote_columns[1].metric("前收", format_metric(quote["previous_close"]))
    quote_columns[2].metric("涨跌幅", format_metric(quote["change"], True))
    quote_columns[3].metric("最高", format_metric(quote["high"]))
    quote_columns[4].metric("最低", format_metric(quote["low"]))
    payload = build_ohlcv_payload(
        display_frame,
        symbol=symbol,
        events=[],
        initial_bars=min(120, len(frame)),
        min_visible_bars=min(30, max(1, len(frame))),
        max_visible_bars=len(frame),
        indicator_config=indicator_config,
        period=period,
        data_context=build_market_detail_context(
            display_frame, symbol=symbol, source=source_label,
            price_mode=price_mode, price_unit=price_unit,
            volume_unit=volume_unit, as_of=market_window["window"]["end"],
        ),
    )
    chart_height = 520 + 126 * panel_count
    from .chart_component import render_interactive_chart
    selection = render_interactive_chart(payload, height=chart_height, key='watch_price')
    if selection:
        picked = display_frame.loc[pd.to_datetime(display_frame['trade_date']).dt.strftime('%Y-%m-%d').eq(selection['date'])]
        if not picked.empty:
            selected_bar = picked.iloc[0]
            st.caption(f"图上选择 {selection['date']} · 收盘 {format_metric(number(selected_bar.get('close')))}")
    st.caption(f"{market_window['bars']:,} 根{period_label}" + (f" · {incomplete} 个周期未完成" if incomplete else ''))
    st.subheader("最近行情")
    table = build_stock_quote_table(display_frame)
    if incomplete:
        visible_status = display_frame["is_complete"].tail(len(table)).tolist()
        table.insert(0, "周期状态", ["未完成" if not bool(value) else "完整" for value in visible_status])
    from portfolio_app.result_presentations import render_recent_quotes
    render_recent_quotes(display_frame, key='market_recent_quotes', table=table)


@st.cache_data(show_spinner=False)
def cached_local_symbol(data_root: str, symbol: str, adjusted: str):
    return load_local_symbol(data_root, symbol, adjusted)


def format_metric(value: float, percent: bool = False) -> str:
    if value is None or not np.isfinite(value):
        return "--"
    if percent:
        return f"{value:.2%}"
    return f"{value:.2f}"


def build_indicator_config_controls() -> tuple[list[dict[str, object]], list[str], list[str]]:
    """Render registry-driven indicator controls and return the normalized selection."""
    render_indicator_template_controls()
    overlay_keys = ["MA", "EMA", "BOLL", "VWAP"]
    panel_keys = ["RSI", "MACD", "KDJ", "ATR", "OBV"]
    default_config = build_default_indicator_config()
    default_overlay = [item["key"] for item in default_config if INDICATOR_REGISTRY[item["key"]].pane == "overlay"]
    default_panels = [item["key"] for item in default_config if INDICATOR_REGISTRY[item["key"]].pane == "panel"]
    overlay_selected = st.multiselect("主图指标", overlay_keys, default=default_overlay, key="registry_overlay_indicators", filter_mode=None)
    panel_selected = st.multiselect(
        "副图指标", panel_keys, default=default_panels, max_selections=3,
        help="默认只打开一个副图，最多同时显示三个副图。取消选择即可隐藏。",
        key="registry_panel_indicators", filter_mode=None,
    )
    with st.expander("指标参数", expanded=False):
        config, _, _ = _indicator_parameter_controls(overlay_selected, panel_selected)
        extra_periods = st.multiselect("附加均线周期", [5, 10, 20, 30, 60, 120, 250], key="extra_ma_periods", filter_mode=None)
        existing_ma = [item["params"]["period"] for item in config if item["key"] == "MA"]
        config += [{"key": "MA", "params": {"period": period}} for period in extra_periods if period not in existing_ma]
        options = ["默认顺序", *panel_selected]
        if st.session_state.get("indicator_panel_priority") not in options:
            st.session_state["indicator_panel_priority"] = "默认顺序"
        first_panel = st.selectbox("优先副图", options, key="indicator_panel_priority", filter_mode=None)
        if "imported_indicator_config" in st.session_state:
            config = st.session_state["imported_indicator_config"]
            if st.button("退出模板配置"):
                del st.session_state["imported_indicator_config"]
                st.rerun()
        try:
            config = order_indicator_config(config, panel_order=[] if first_panel == "默认顺序" else [first_panel])
        except ValueError as exc:
            show_safe_error(exc, operation='configuration')
            config = build_default_indicator_config()
        st.download_button("下载指标模板", serialize_indicator_template(config),
                           file_name="indicator-template.json", mime="application/json")
    config = validate_indicator_layout(config)
    return config, [item["key"] for item in config if INDICATOR_REGISTRY[item["key"]].pane == "overlay"], [item["key"] for item in config if INDICATOR_REGISTRY[item["key"]].pane == "panel"]


def _indicator_parameter_controls(overlay_selected: list[str], panel_selected: list[str]):
    config: list[dict[str, object]] = []
    for pane, selected in (("overlay", overlay_selected), ("panel", panel_selected)):
        for key in selected:
            spec = INDICATOR_REGISTRY[key]
            params: dict[str, object] = {}
            for name, definition in spec.parameters.items():
                widget_key = f"indicator_{key}_{name}"
                if definition["type"] == "int":
                    params[name] = st.number_input(
                        f"{key} {name}",
                        min_value=int(definition["min"]),
                        max_value=int(definition["max"]),
                        value=int(definition["default"]),
                        step=int(definition["step"]),
                        key=widget_key,
                    )
                else:
                    params[name] = st.number_input(
                        f"{key} {name}",
                        min_value=float(definition["min"]),
                        max_value=float(definition["max"]),
                        value=float(definition["default"]),
                        step=float(definition["step"]),
                        key=widget_key,
                    )
            config.append({"key": key, "params": params})
    return config, overlay_selected, panel_selected


def build_price_chart(
    frame: pd.DataFrame,
    symbol: str,
    overlay_indicators: list[str] | None = None,
    panel_indicators: list[str] | None = None,
    show_signals: bool = True,
    trade_events: list[dict[str, object]] | None = None,
    initial_bars: int | None = None,
) -> go.Figure:
    """Build a responsive terminal-style chart for the local research view."""
    overlay_indicators = overlay_indicators or ["MA20", "MA60"]
    panel_indicators = panel_indicators or ["RSI"]
    data = add_chart_indicators(frame)
    panel_rows = 2 + len(panel_indicators)
    row_heights = [0.54, 0.16] + [0.30 / max(len(panel_indicators), 1)] * len(panel_indicators)
    figure = make_subplots(
        rows=panel_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=row_heights,
        subplot_titles=[None, "成交量"] + panel_indicators,
    )
    x = data["trade_date"]
    figure.add_trace(
        go.Candlestick(
            x=x,
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            name=symbol,
            increasing_line_color="#ef5350",
            increasing_fillcolor="#ef5350",
            decreasing_line_color="#26a69a",
            decreasing_fillcolor="#26a69a",
            whiskerwidth=0.6,
            hovertemplate="%{x|%Y-%m-%d}<br>开 %{open:.2f}<br>高 %{high:.2f}<br>低 %{low:.2f}<br>收 %{close:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    overlay_specs = {
        "MA5": ("ma5", "MA5", "#8A6BC6", 1.2),
        "MA20": ("ma20", "MA20", "#2864D7", 1.4),
        "MA60": ("ma60", "MA60", "#c084fc", 1.4),
        "EMA12": ("ema12", "EMA12", "#14949B", 1.2),
        "EMA26": ("ema26", "EMA26", "#a78bfa", 1.2),
    }
    for selected in overlay_indicators:
        if selected in overlay_specs:
            column, label, color, width = overlay_specs[selected]
            figure.add_trace(go.Scatter(x=x, y=data[column], name=label, line={"color": color, "width": width}), row=1, col=1)
        elif selected == "布林带":
            figure.add_trace(go.Scatter(x=x, y=data["bb_upper"], name="布林上轨", line={"color": "#94a3b8", "width": 1, "dash": "dot"}), row=1, col=1)
            figure.add_trace(go.Scatter(x=x, y=data["bb_lower"], name="布林下轨", line={"color": "#94a3b8", "width": 1, "dash": "dot"}, fill="tonexty", fillcolor="rgba(148,163,184,0.08)"), row=1, col=1)
            figure.add_trace(go.Scatter(x=x, y=data["bb_mid"], name="布林中轨", line={"color": "#64748b", "width": 1}), row=1, col=1)

    if show_signals:
        fills = [event for event in (trade_events or []) if event.get("event_type") == "FILL"]
        if fills:
            event_frame = pd.DataFrame(fills)
            event_frame["effective_date"] = pd.to_datetime(event_frame["effective_date"], errors="coerce")
            event_frame["price"] = pd.to_numeric(event_frame["price"], errors="coerce")
            marker_groups = (
                (event_frame["side"].eq("BUY"), "买入", "triangle-up", "#ef5350"),
                (event_frame["side"].eq("SELL"), "卖出", "triangle-down", "#26a69a"),
            )
            for mask, label, marker, color in marker_groups:
                selected = event_frame.loc[mask].dropna(subset=["effective_date", "price"])
                if selected.empty:
                    continue
                hover_text = [
                    f"{label}<br>价格 {price:.2f}<br>原因：{reason}<br>信号日期：{decision}"
                    for price, reason, decision in zip(
                        selected["price"],
                        selected["reason_text_public"],
                        selected["decision_date"],
                    )
                ]
                figure.add_trace(
                    go.Scatter(
                        x=selected["effective_date"],
                        y=selected["price"],
                        mode="markers",
                        name=label,
                        customdata=hover_text,
                        marker={"symbol": marker, "color": color, "size": 11, "line": {"color": "#0f172a", "width": 1}},
                        hovertemplate="%{x|%Y-%m-%d}<br>reason=%{customdata}<extra></extra>",
                    ),
                    row=1,
                    col=1,
                )
        elif "position" in data:
            changes = data["position"].diff().fillna(data["position"])
            marker_groups = (
                (changes.gt(0), "买入", "triangle-up", "#ef5350"),
                (changes.lt(0), "卖出", "triangle-down", "#26a69a"),
            )
            for mask, label, marker, color in marker_groups:
                selected = data.loc[mask]
                if selected.empty:
                    continue
                figure.add_trace(
                    go.Scatter(
                        x=selected["trade_date"],
                        y=selected["close"],
                        mode="markers",
                        name=label,
                        marker={"symbol": marker, "color": color, "size": 10, "line": {"color": "#0f172a", "width": 1}},
                        hovertemplate=f"%{{x|%Y-%m-%d}}<br>{label}<br>价格 %{{y:.2f}}<extra></extra>",
                    ),
                    row=1,
                    col=1,
                )

    volume = pd.to_numeric(data.get("vol", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    volume_colors = np.where(data["close"] >= data["open"], "rgba(239,83,80,0.75)", "rgba(38,166,154,0.75)")
    figure.add_trace(go.Bar(x=x, y=volume, name="成交量", marker_color=volume_colors), row=2, col=1)
    figure.add_trace(go.Scatter(x=x, y=data["vol_ma5"], name="VOL MA5", line={"color": "#8A6BC6", "width": 1}), row=2, col=1)
    figure.add_trace(go.Scatter(x=x, y=data["vol_ma20"], name="VOL MA20", line={"color": "#2864D7", "width": 1}), row=2, col=1)

    row = 3
    for indicator in panel_indicators:
        if indicator == "RSI":
            figure.add_trace(go.Scatter(x=x, y=data["rsi14"], name="RSI(14)", line={"color": "#526C93", "width": 1.5}), row=row, col=1)
            figure.add_hline(y=70, line_dash="dot", line_color="#64748b", line_width=1, row=row, col=1)
            figure.add_hline(y=30, line_dash="dot", line_color="#64748b", line_width=1, row=row, col=1)
            figure.update_yaxes(range=[0, 100], row=row, col=1)
        elif indicator == "MACD":
            histogram_colors = np.where(data["macd_hist"] >= 0, "rgba(239,83,80,0.75)", "rgba(38,166,154,0.75)")
            figure.add_trace(go.Bar(x=x, y=data["macd_hist"], name="MACD柱", marker_color=histogram_colors), row=row, col=1)
            figure.add_trace(go.Scatter(x=x, y=data["macd"], name="DIF", line={"color": "#2864D7", "width": 1.2}), row=row, col=1)
            figure.add_trace(go.Scatter(x=x, y=data["macd_signal"], name="DEA", line={"color": "#8A6BC6", "width": 1.2}), row=row, col=1)
        elif indicator == "KDJ":
            for column, label, color in (("k", "K", "#2864D7"), ("d", "D", "#8A6BC6"), ("j", "J", "#c084fc")):
                figure.add_trace(go.Scatter(x=x, y=data[column], name=label, line={"color": color, "width": 1.2}), row=row, col=1)
            figure.update_yaxes(range=[0, 100], row=row, col=1)
        elif indicator == "ATR":
            figure.add_trace(go.Scatter(x=x, y=data["atr14"], name="ATR(14)", line={"color": "#B65269", "width": 1.4}), row=row, col=1)
        row += 1

    trade_dates = pd.to_datetime(data["trade_date"], errors="coerce").dropna().sort_values().unique()
    if len(trade_dates) > 0:
        market_start = pd.Timestamp(trade_dates[0])
        market_end = pd.Timestamp(trade_dates[-1])
        requested_bars = initial_bars if initial_bars is not None else 120
        visible_bars = max(20, min(int(requested_bars), len(trade_dates)))
        visible_start = pd.Timestamp(trade_dates[-visible_bars])
        range_selector_buttons = [
            {"count": 1, "label": "1个月", "step": "month", "stepmode": "backward"},
            {"count": 3, "label": "3个月", "step": "month", "stepmode": "backward"},
            {"count": 6, "label": "6个月", "step": "month", "stepmode": "backward"},
            {"count": 1, "label": "1年", "step": "year", "stepmode": "backward"},
            {"label": "全部", "step": "all"},
        ]
    else:
        market_start = market_end = visible_start = None
        range_selector_buttons = []

    figure.update_layout(
        height=560 + 126 * len(panel_indicators),
        autosize=True,
        title={"text": f"{symbol} · 价格、成交量与指标", "x": 0.01, "y": 0.995, "xanchor": "left", "yanchor": "top", "font": {"size": 16}},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": "Segoe UI, Microsoft YaHei, sans-serif", "size": 14, "color": "#334155"},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.01, "x": 0, "yanchor": "bottom", "font": {"size": 14}},
        margin={"l": 42, "r": 18, "t": 102, "b": 26},
        xaxis_rangeslider={"visible": True, "thickness": 0.07, "bgcolor": "#f8fafc", "bordercolor": "#cbd5e1"},
        xaxis={
            "range": [visible_start, market_end] if visible_start is not None else None,
            "autorange": False if visible_start is not None else True,
            "minallowed": market_start,
            "maxallowed": market_end,
            "rangeselector": {"buttons": range_selector_buttons, "x": 1, "xanchor": "right", "y": 1.12, "font": {"size": 14}},
        },
        dragmode="pan",
        uirevision=f"{symbol}-{market_start}-{market_end}",
        modebar={"orientation": "v"},
    )
    figure.update_xaxes(
        showgrid=True,
        gridcolor="#e2e8f0",
        showline=True,
        linecolor="#cbd5e1",
        tickformat="%Y-%m",
        rangeslider={"visible": False},
        range=[visible_start, market_end] if visible_start is not None else None,
        autorange=False if visible_start is not None else True,
        minallowed=market_start,
        maxallowed=market_end,
    )
    figure.update_yaxes(showgrid=True, gridcolor="#e2e8f0", zeroline=False, showline=True, linecolor="#cbd5e1", fixedrange=False)
    # Only one navigator below the final panel; per-axis sliders obscure indicators.
    figure.update_xaxes(rangeslider=dict(visible=True, thickness=.045), row=panel_rows, col=1)
    return figure


TRADE_TABLE_COLUMNS = [
    "decision_date",
    "effective_date",
    "fill_date",
    "side",
    "reason_code",
    "reason_text_public",
    "evidence",
    "price",
    "quantity",
    "status",
    "order_id",
    "fill_id",
]


def build_trade_event_frame(events: list[dict[str, object]] | None) -> pd.DataFrame:
    """Return public-safe filled trades with decision and execution dates separated."""
    fills = [event for event in (events or []) if event.get("event_type") == "FILL"]
    if not fills:
        return pd.DataFrame(columns=TRADE_TABLE_COLUMNS)
    frame = pd.DataFrame(fills)
    for column in TRADE_TABLE_COLUMNS:
        if column not in frame:
            frame[column] = None
    return frame[TRADE_TABLE_COLUMNS].sort_values(
        ["effective_date", "side"], kind="stable"
    ).reset_index(drop=True)


def build_strategy_result_trade_frame(details: dict[str, object]) -> pd.DataFrame:
    """Turn the linked signal/order/fill contract into a readable local table."""
    rows = list(details.get("trades", [])) if isinstance(details, dict) else []
    columns = [
        "信号日期", "执行日期", "标的", "方向", "状态", "约束状态",
        "原因", "数量", "价格", "信号ID", "订单ID", "成交ID",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    table = pd.DataFrame(
        [
            {
                "信号日期": row.get("decision_date"),
                "执行日期": row.get("effective_date"),
                "标的": row.get("symbol"),
                "方向": {"BUY": "买入", "SELL": "卖出"}.get(str(row.get("side")), row.get("side")),
                "状态": {"FILLED": "已成交", "REJECTED": "已拒单", "PLANNED": "待执行"}.get(str(row.get("status")), row.get("status")),
                "约束状态": row.get("constraint_status"),
                "原因": row.get("reason_text_public") or row.get("reason_code"),
                "数量": row.get("quantity"),
                "价格": row.get("price"),
                "信号ID": row.get("signal_id"),
                "订单ID": row.get("order_id"),
                "成交ID": row.get("fill_id"),
            }
            for row in rows
        ]
    )
    return table[columns].sort_values(["执行日期", "标的"], kind="stable").reset_index(drop=True)


def build_strategy_result_position_frame(details: dict[str, object]) -> pd.DataFrame:
    """Turn cash/position snapshots into a compact presentation table."""
    rows = list(details.get("positions", [])) if isinstance(details, dict) else []
    columns = ["日期", "标的", "持仓数量", "现金"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(
        [
            {
                "日期": row.get("date"),
                "标的": row.get("symbol"),
                "持仓数量": row.get("quantity"),
                "现金": row.get("cash"),
            }
            for row in rows
        ],
        columns=columns,
    )


def build_strategy_result_cost_frame(performance: dict[str, object]) -> pd.DataFrame:
    """Return the non-zero daily cost rows used by the cost detail tab."""
    curve = performance.get("curve", []) if isinstance(performance, dict) else []
    rows = []
    for item in curve if isinstance(curve, list) else []:
        if not isinstance(item, dict):
            continue
        cost = pd.to_numeric(item.get("daily_cost"), errors="coerce")
        if pd.notna(cost) and float(cost) != 0.0:
            rows.append({
                "日期": item.get("date"),
                "日收益": item.get("daily_return"),
                "日成本": float(cost),
                "净值": item.get("nav"),
            })
    return pd.DataFrame(rows, columns=["日期", "日收益", "日成本", "净值"])


def build_strategy_result_diagnostics(
    research_diagnostics: dict[str, object],
    details: dict[str, object],
    performance: dict[str, object],
) -> dict[str, str]:
    """Build the compact diagnosis contract shown beside a single-stock result."""
    summary = details.get("summary", {}) if isinstance(details, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    quality = research_diagnostics.get("data_quality", {}) if isinstance(research_diagnostics, dict) else {}
    quality = quality if isinstance(quality, dict) else {}
    signals = int(summary.get("signals", 0) or 0)
    orders = int(summary.get("orders", 0) or 0)
    fills = int(summary.get("fills", 0) or 0)
    rejected = int(summary.get("rejected_orders", 0) or 0)
    diagnostics = performance.get("diagnostics", {}) if isinstance(performance, dict) else {}
    empty_trade = bool(diagnostics.get("empty_trade_state", fills == 0)) if isinstance(diagnostics, dict) else fills == 0
    return {
        "交易能力": "离线模拟",
        "估值时点": "历史收盘数据，非实时",
        "数据质量": str(quality.get("status", "未知")),
        "预热期": f"{int(research_diagnostics.get('warmup_bars', 0) or 0)} 根",
        "信号参与率": f"{float(research_diagnostics.get('signal_coverage', 0.0) or 0.0):.2%}",
        "拒单": str(rejected),
        "未成交订单": str(max(0, orders - fills)),
        "归档": "可下载" if not empty_trade or signals == 0 else "可下载（空交易）",
    }


def build_strategy_focus_event_id(row: object) -> str | None:
    """Return the most concrete public event ID from a selected detail row."""
    if not isinstance(row, (dict, pd.Series)):
        return None
    for key in ("成交ID", "订单ID", "信号ID"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def build_drawdown_chart(frame: pd.DataFrame, title: str = "策略回撤") -> go.Figure:
    """Build a stable underwater chart for a single-stock backtest."""
    drawdown = frame["drawdown"] if "drawdown" in frame else frame["equity"] / frame["equity"].cummax() - 1
    figure = go.Figure(
        go.Scatter(
            x=frame["trade_date"],
            y=drawdown,
            name="回撤",
            mode="lines",
            line={"color": "#dc2626", "width": 1.5},
            fill="tozeroy",
            fillcolor="rgba(220,38,38,0.14)",
            hovertemplate="%{x|%Y-%m-%d}<br>回撤 %{y:.2%}<extra></extra>",
        )
    )
    figure.update_layout(
        height=260,
        title=title,
        yaxis={"tickformat": ".0%", "zeroline": True, "zerolinecolor": "#94a3b8"},
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
    )
    style_chart(figure, title=figure.layout.title.text or '', height=figure.layout.height or 340)
    return figure


def build_portfolio_contribution_frame(contributions: pd.DataFrame) -> pd.DataFrame:
    """Normalize per-leg daily contribution data for tables and charts."""
    if contributions is None or contributions.empty:
        return pd.DataFrame(columns=["trade_date"])
    frame = contributions.copy()
    if "trade_date" not in frame:
        frame = frame.reset_index(names="trade_date")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    legs = [column for column in frame.columns if column != "trade_date"]
    for leg in legs:
        frame[leg] = pd.to_numeric(frame[leg], errors="coerce").fillna(0.0)
    return frame[["trade_date", *legs]].sort_values("trade_date").reset_index(drop=True)


def build_portfolio_contribution_chart(contributions: pd.DataFrame) -> go.Figure:
    """Show daily strategy contribution by portfolio leg."""
    frame = build_portfolio_contribution_frame(contributions)
    figure = go.Figure()
    for leg in [column for column in frame.columns if column != "trade_date"]:
        figure.add_trace(
            go.Bar(
                x=frame["trade_date"],
                y=frame[leg],
                name=str(leg),
                hovertemplate=f"%{{x|%Y-%m-%d}}<br>{leg}贡献 %{{y:.2%}}<extra></extra>",
            )
        )
    figure.update_layout(
        barmode="relative",
        height=300,
        title="组合腿日贡献",
        yaxis={"tickformat": ".2%"},
        legend={"orientation": "h"},
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
    )
    style_chart(figure, title=figure.layout.title.text or '', height=figure.layout.height or 340)
    return figure


def build_portfolio_exposure_chart(frame: pd.DataFrame) -> go.Figure:
    """Show invested exposure and residual cash weight."""
    data = frame.copy()
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=data["trade_date"],
            y=data["gross_exposure"],
            name="股票暴露",
            mode="lines",
            line={"color": "#2563eb", "width": 2},
            stackgroup="one",
            hovertemplate="%{x|%Y-%m-%d}<br>股票暴露 %{y:.0%}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=data["trade_date"],
            y=data["cash_weight"],
            name="现金",
            mode="lines",
            line={"color": "#94a3b8", "width": 1},
            stackgroup="one",
            hovertemplate="%{x|%Y-%m-%d}<br>现金 %{y:.0%}<extra></extra>",
        )
    )
    figure.update_layout(
        height=300,
        title="组合暴露与现金",
        yaxis={"range": [0, 1], "tickformat": ".0%"},
        legend={"orientation": "h"},
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
    )
    style_chart(figure, title=figure.layout.title.text or '', height=figure.layout.height or 340)
    return figure


def build_portfolio_trade_event_frame(events: list[dict[str, object]] | None) -> pd.DataFrame:
    """Return portfolio fills with leg and public explanation fields."""
    frame = build_trade_event_frame(events)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "组合腿",
                "信号日期",
                "执行日期",
                "成交日期",
                "方向",
                "原因代码",
                "公开解释",
                "证据字段",
                "成交价格",
                "数量",
                "状态",
                "订单ID",
                "成交ID",
            ]
        )
    fills = pd.DataFrame([event for event in (events or []) if event.get("event_type") == "FILL"])
    legs = fills.drop_duplicates("fill_id").set_index("fill_id").get("portfolio_leg", pd.Series(dtype="object"))
    frame["portfolio_leg"] = frame["fill_id"].map(legs).fillna("")
    return frame.rename(
        columns={
            "portfolio_leg": "组合腿",
            "decision_date": "信号日期",
            "effective_date": "执行日期",
            "fill_date": "成交日期",
            "side": "方向",
            "reason_code": "原因代码",
            "reason_text_public": "公开解释",
            "evidence": "证据字段",
            "price": "成交价格",
            "quantity": "数量",
            "status": "状态",
            "order_id": "订单ID",
            "fill_id": "成交ID",
        }
    )


def build_equity_chart(frame, title: str = "组合净值与基准对比"):
    series = {'equity': '策略净值'}
    if 'benchmark_equity' in frame:
        series['benchmark_equity'] = '基准'
    figure = build_time_series_chart(frame, series, title=title, unit='number', height=360)
    if len(figure.data) > 1:
        figure.data[1].line.color = '#8A99AF'
        figure.data[1].line.width = 1.5
    return figure


def build_equity_chart_key(scope: str) -> str:
    """Return a stable unique Streamlit element key for repeated equity views."""
    return f"equity-chart-{scope}"


def build_robustness_chart(report: pd.DataFrame) -> go.Figure:
    if report is None or report.empty:
        return style_chart(go.Figure(), title='稳健性场景暂无结果', height=280)
    data = report.copy()
    data['scenario'] = data.apply(lambda row: f"{int(row['window_bars'])}根 / {row['transaction_cost']:.2%}", axis=1)
    figure = build_comparison_chart(data.scenario, [('年化收益', data.annual_return)], title='窗口与成本 · 年化收益')
    valid = pd.to_numeric(data.annual_return, errors='coerce').notna() & pd.to_numeric(data.annual_return, errors='coerce').abs().ne(float('inf'))
    figure.data[0].customdata = data.loc[valid, ['max_drawdown','sharpe','trades']]
    figure.data[0].hovertemplate = '场景 %{y}<br>年化收益 %{x:.2%}<br>最大回撤 %{customdata[0]:.2%}<br>夏普 %{customdata[1]:.2f}<br>交易次数 %{customdata[2]}<extra></extra>'
    return figure


def build_strategy_comparison_chart(comparison: pd.DataFrame) -> go.Figure:
    if comparison is None or comparison.empty or comparison['stability_label'].eq('无有效场景').all():
        return style_chart(go.Figure(), title='策略比较暂无结果', height=280)
    return _metric_comparison_panels(comparison, 'strategy_name', ('年化收益中位数','夏普中位数','最差回撤'))


def render_model_evidence(evidence: dict[str, object]) -> None:
    status = str(evidence.get("status", "unavailable"))
    label = str(evidence.get("status_label", "产物不可用"))
    if status == "validated":
        st.success(label)
    elif status == "review_required":
        st.warning(label)
    elif status == "validated_with_limitations":
        st.info(label)
    else:
        st.error(label)

    headline = evidence.get("headline", {})
    if headline:
        metric_columns = st.columns(3)
        metric_columns[0].metric("年化收益", format_metric(float(headline.get("annual_return", 0.0)), True))
        metric_columns[1].metric("夏普比率", format_metric(float(headline.get("sharpe", 0.0))))
        metric_columns[2].metric("最大回撤", format_metric(float(headline.get("max_drawdown", 0.0)), True))
    st.caption(f"证据区间：{evidence.get('period', '未提供')} · 来源：{evidence.get('source', '未提供')}")
    secondary = evidence.get("secondary", {})
    if secondary:
        st.json(secondary)
    for note in evidence.get("notes", []):
        st.write(f"• {note}")
    if evidence.get("cases"):
        st.dataframe(pd.DataFrame(evidence["cases"]), width="stretch", hide_index=True)
    annual_oos = evidence.get("annual_oos")
    if annual_oos:
        annual_frame = pd.DataFrame(annual_oos)
        st.dataframe(annual_frame, width="stretch", hide_index=True)
        if "year" in annual_frame and "annualized_return" in annual_frame:
            chart = build_metric_bars(annual_frame, category='year', value='annualized_return', title='年度样本外年化收益')
            style_chart(chart, title=chart.layout.title.text or '', height=chart.layout.height or 360)
            st.plotly_chart(chart, width="stretch")


def model_comparison_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Create a readable comparison table while keeping numeric chart fields."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["annual_return_display"] = frame["annual_return"].map(
        lambda value: "未提供" if pd.isna(value) else f"{float(value):.2%}"
    )
    frame["sharpe_display"] = frame["sharpe"].map(
        lambda value: "未提供" if pd.isna(value) else f"{float(value):.2f}"
    )
    frame["max_drawdown_display"] = frame["max_drawdown"].map(
        lambda value: "未提供" if pd.isna(value) else f"{float(value):.2%}"
    )
    return frame


def build_model_metric_chart(rows: list[dict[str, object]]) -> go.Figure:
    frame = pd.DataFrame(rows).copy()
    if frame.empty:
        return style_chart(go.Figure(), title='暂无可比指标', height=260)
    frame = frame.dropna(subset=['annual_return', 'sharpe', 'max_drawdown'])
    frame['label'] = frame['key'].str.replace('model', '模型', regex=False)
    return _metric_comparison_panels(frame, 'label', ('年化收益','夏普比率','最大回撤'))


def render_portfolio_home() -> None:
    public_only = evidence_display_public_only()
    language = st.session_state.get("app_language", "zh")
    content = build_portfolio_content(language)
    rows = build_model_comparison_rows(REPO_ROOT, public_only=public_only)
    validated = sum(row["status"] == "validated" for row in rows)
    review_required = sum(row["status"] == "review_required" for row in rows)

    st.title(str(content["title"]))
    st.caption(str(content["subtitle"]))

    lead, metric_one, metric_two, metric_three = st.columns([2.2, 1, 1, 1])
    with lead:
        st.subheader("项目主线" if language == "zh" else "Project Focus")
        st.write(str(content["positioning"]))
    metric_labels = content["metric_labels"]
    metric_one.metric(str(metric_labels["models"]), f"{len(rows)} {'个' if language == 'zh' else ''}".strip())
    metric_two.metric(str(metric_labels["validated"]), f"{validated} {'个' if language == 'zh' else ''}".strip())
    metric_three.metric(str(metric_labels["review"]), f"{review_required} {'个' if language == 'zh' else ''}".strip())

    st.subheader("能力与应用" if language == "zh" else "Capabilities")
    st.dataframe(pd.DataFrame({str(content["capability_columns"][0]): list(content["capabilities"])}), width="stretch", hide_index=True)
    st.subheader(str(content["projects_heading"]))
    st.caption(str(content["comparison_note"]))
    st.plotly_chart(build_model_metric_chart(rows), width="stretch")

    overview = model_comparison_frame(rows)
    st.dataframe(
        overview[["model", "asset_scope", "status_label", "annual_return_display", "sharpe_display", "max_drawdown_display"]].rename(
            columns={
                "model": "研究项目",
                "asset_scope": "资产范围",
                "status_label": "验证状态",
                "annual_return_display": "年化收益",
                "sharpe_display": "夏普",
                "max_drawdown_display": "最大回撤",
            }
        ),
        width="stretch",
        hide_index=True,
    )

    st.caption(str(content["historical_note"]))


def render_public_artifacts() -> None:
    language = st.session_state.get("app_language", "zh")
    content = build_portfolio_content(language)
    st.title(str(content["artifacts_heading"]))
    st.caption(str(content["artifacts_intro"]))
    st.write(str(content["boundary"]))
    for artifact in list_public_artifacts(REPO_ROOT):
        st.markdown(f"**{artifact['label']}**")
        st.caption(f"`{artifact['path']}` · {artifact['suffix']} · {artifact['size']} bytes")
        path = REPO_ROOT / str(artifact["path"])
        st.download_button(
            "下载 / Download",
            data=path.read_bytes(),
            file_name=path.name,
            mime="text/csv" if artifact["suffix"] == "csv" else "text/markdown" if artifact["suffix"] == "md" else "text/plain",
            key=f"artifact_download_{artifact['path']}",
        )


def render_model_comparison() -> None:
    public_only = evidence_display_public_only()
    rows = build_model_comparison_rows(REPO_ROOT, public_only=public_only)
    st.title("Model Comparison")
    st.caption("统一展示模型1–7的历史研究证据。比较用于理解研究结构，不代表不同资产之间的绝对排名。")
    status_options = ["全部"] + sorted({str(row["status_label"]) for row in rows})
    selected_status = st.selectbox("验证状态", status_options, filter_mode=None)
    filtered_rows = rows if selected_status == "全部" else [row for row in rows if row["status_label"] == selected_status]
    table = model_comparison_frame(filtered_rows)
    if table.empty:
        st.info("当前筛选没有可展示的研究证据。")
        return

    st.plotly_chart(build_model_metric_chart(filtered_rows), width="stretch")
    st.dataframe(
        table[["model", "category", "asset_scope", "status_label", "period", "annual_return_display", "sharpe_display", "max_drawdown_display", "source"]].rename(
            columns={
                "model": "研究项目",
                "category": "研究类型",
                "asset_scope": "资产范围",
                "status_label": "验证状态",
                "period": "证据区间",
                "annual_return_display": "年化收益",
                "sharpe_display": "夏普",
                "max_drawdown_display": "最大回撤",
                "source": "证据来源",
            }
        ),
        width="stretch",
        hide_index=True,
    )
    st.info("阅读方式：先看资产范围和验证状态，再看指标；模型2、模型6的 review_required 状态是研究结论的一部分。")
    for row in filtered_rows:
        with st.expander(f"{row['model']} · {row['status_label']}"):
            st.write(f"资产范围：{row['asset_scope']}")
            st.write(f"证据区间：{row['period']}")
            if row.get("notes"):
                st.write(row["notes"])
            st.caption(f"来源：{row['source']}")


def _data_registry_root() -> Path:
    from portfolio_app.state_paths import state_root
    return state_root() / "dataset_registry"


def _data_workflow_state() -> DataWorkflowState:
    state = st.session_state.get("data_workflow_state")
    if isinstance(state, DataWorkflowState):
        return state
    state = build_data_workflow()
    st.session_state["data_workflow_state"] = state
    return state


def _set_data_workflow_state(state: DataWorkflowState) -> None:
    st.session_state["data_workflow_state"] = state


def _reset_data_workflow_inputs() -> DataWorkflowState:
    state = build_data_workflow()
    _set_data_workflow_state(state)
    st.session_state.pop("data_workflow_frame", None)
    st.session_state.pop("data_workflow_staged_path", None)
    return state


def _data_source_kind(label: str) -> str:
    return {"合成示例": "synthetic", "文件导入": "file_import", "本地行情": "local_market"}[label]


def _stage_uploaded_data(uploaded, dataset_id: str) -> Path:
    """Keep an explicitly selected local upload available for version registration."""
    safe_name = Path(str(uploaded.name)).name
    target = _data_registry_root() / "staged_sources" / dataset_id / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(uploaded.getvalue())
    return target


def _render_data_workflow_stepper(state: DataWorkflowState) -> None:
    labels = {
        DataWorkflowStep.IMPORT: "导入数据 / Import",
        DataWorkflowStep.QUALITY: "质量检查 / Quality",
        DataWorkflowStep.VERSION: "数据版本 / Version",
        DataWorkflowStep.RESEARCH: "进入研究 / Research",
    }
    current = labels[state.step]
    st.info(f"当前步骤：{current} · 下一步：{state.next_action}")
    st.caption("导入 → 预览 → 质量检查 → 登记/选择版本 → 进入离线研究")


def render_data_analysis() -> None:
    st.title("Data Analysis")
    st.caption("先检查数据质量，再查看收益、波动和回撤；本页不触发实盘下单。")

    with st.sidebar:
        st.header("分析设置")
        data_source = st.selectbox("数据来源", ["合成示例", "文件导入"] if PUBLIC_MODE else ["合成示例", "文件导入", "本地行情"], key="analysis_source", filter_mode=None)
        data_root = str(DEFAULT_DATA_ROOT)
        adjusted = "qfq"
        symbols = []
        portfolio_cash_weight = 0.0
        if data_source == "本地行情":
            data_root = st.text_input("本地数据目录", data_root, key="analysis_data_root")
            adjusted = st.selectbox("价格口径", ["qfq", "hfq", "raw"], index=0, key="analysis_adjusted", filter_mode=None)
            symbols = list_local_symbols(data_root, adjusted)

    uploaded = st.file_uploader(
        "导入 CSV、Excel 或 Parquet",
        type=["csv", "xlsx", "xls", "parquet", "pq"],
        key="analysis_upload",
    )
    source = ""
    if data_source == "合成示例":
        frame = read_market_file(SAMPLE_ROOT / "quant_demo_multi_symbol.csv")
        source = "合成多标的示例 · 非真实证券数据"
    elif uploaded is not None:
        try:
            frame = render_import_preview(uploaded, key="analysis")
            if frame is None:
                return
            source = f"导入文件：{uploaded.name}"
        except Exception as exc:
            show_safe_error(exc, operation='import')
            return
    elif symbols:
        symbol = st.selectbox("本地股票", symbols, key="analysis_symbol", filter_mode=None)
        try:
            frame = cached_local_symbol(data_root, symbol, adjusted)
            source = f"本地数据：{symbol} · {adjusted}"
        except Exception as exc:
            show_safe_error(exc, operation='import')
            return
    else:
        st.info("请选择有效的本地数据目录，或导入一份日线数据。")
        return

    summary = build_market_summary(frame)
    quality = build_data_quality_report(frame)
    returns = build_symbol_return_summary(frame)
    st.caption(source)

    metric_columns = st.columns(5)
    metric_columns[0].metric("记录数", f"{summary['rows']:,}")
    metric_columns[1].metric("股票数", f"{summary['symbols']:,}")
    metric_columns[2].metric("起始日期", summary["start"] or "未提供")
    metric_columns[3].metric("结束日期", summary["end"] or "未提供")
    metric_columns[4].metric("质量状态", quality["status"])

    overview, returns_tab, quality_tab = st.tabs(["数据概览", "收益与风险", "质量检查"])
    with overview:
        st.subheader("数据摘要")
        st.dataframe(pd.DataFrame([summary]), width="stretch", hide_index=True)
        preview_columns = [column for column in ["symbol", "trade_date", "open", "high", "low", "close", "vol", "return"] if column in frame.columns]
        st.subheader("最近记录")
        st.dataframe(frame[preview_columns].tail(30), width="stretch", hide_index=True)

    with returns_tab:
        st.subheader("按股票汇总")
        display_returns = returns.copy()
        for column in ["total_return", "annualized_return", "annualized_volatility", "max_drawdown"]:
            if column in display_returns:
                display_returns[column] = display_returns[column].map(lambda value: f"{float(value):.2%}")
        st.dataframe(display_returns, width="stretch", hide_index=True)
        if not returns.empty:
            chart = build_metric_bars(returns, category='symbol', value='total_return', title='各股票区间收益')
            style_chart(chart, title=chart.layout.title.text or '', height=chart.layout.height or 360)
            st.plotly_chart(chart, width="stretch")

    with quality_tab:
        if quality["status"] == "通过":
            st.success("未发现需要立即复核的常见数据质量问题。")
        else:
            st.warning("发现需要复核的数据质量问题，请在使用回测结果前处理。")
        quality_table = pd.DataFrame(
            [
                {"检查项": "缺失必需字段", "异常数量": len(quality.get("missing_columns", [])), "详情": ", ".join(quality.get("missing_columns", [])) or "无"},
                {"检查项": "必需字段缺失值", "异常数量": quality["missing_required_value_rows"], "详情": "行"},
                {"检查项": "OHLC逻辑异常", "异常数量": quality["invalid_ohlc_rows"], "详情": "行"},
                {"检查项": "非正收盘价", "异常数量": quality["non_positive_close_rows"], "详情": "行"},
                {"检查项": "重复日期记录", "异常数量": quality["duplicate_key_rows"], "详情": "行"},
                {"检查项": "日期顺序异常", "异常数量": quality["non_monotonic_rows"], "详情": "行"},
            ]
        )
        st.dataframe(quality_table, width="stretch", hide_index=True)


def main() -> None:
    apply_workbench_theme()
    route_state, route_warning = resolve_workspace_query(dict(st.query_params))
    route_selector_key = "workspace_route_selector"
    if st.session_state.get("_route_synced_query") != tuple(sorted(dict(st.query_params).items())):
        st.session_state[route_selector_key] = route_state.active_workspace
        st.session_state["_route_synced_query"] = tuple(sorted(dict(st.query_params).items()))
    with st.sidebar:
        render_sidebar_brand()
        if '_registered_research_dataset' in st.session_state:
            registered = st.session_state['_registered_research_dataset'].attrs['research_dataset']
            st.session_state['_registered_dataset_toggle'] = st.session_state.get('_use_registered_research_dataset', False)
            st.checkbox(f"使用登记数据：{registered['dataset_id']} / {registered['version']}",
                key='_registered_dataset_toggle', on_change=lambda: st.session_state.update(
                    _use_registered_research_dataset=st.session_state['_registered_dataset_toggle']))
        workspace_options = [route.id for route in WORKSPACE_ROUTES]
        workspace_labels = {route.id: f"{route.label_zh} / {route.label_en}" for route in WORKSPACE_ROUTES}
        selector_kwargs = build_workspace_selector_kwargs(
            route_state.active_workspace,
            synced=st.session_state.get("_route_synced_query") == tuple(sorted(dict(st.query_params).items())),
        )
        selector_kwargs["key"] = route_selector_key
        selector_kwargs['format_func'] = {route.id: route.label_zh for route in WORKSPACE_ROUTES}.get
        selected_workspace = st.radio("工作区 / Workspace", **selector_kwargs, label_visibility='collapsed')
        with st.expander('显示与数据', expanded=False):
            st.selectbox("作品语言 / Showcase language", ["zh", "en"], format_func=lambda value: "中文" if value == "zh" else "English", key="app_language", filter_mode=None)
        st.html('<div class="quant-nav-footer">本地研究空间<br>数据 · 验证 · 可视化</div>')
    if selected_workspace != route_state.active_workspace:
        next_state = switch_workspace(route_state, selected_workspace)
        st.query_params.clear()
        st.query_params.update(navigation_query(next_state))
        st.rerun()
    if route_warning:
        st.warning(route_warning)
    # Reserve the status location, then fill it after the workspace has
    # updated its state. This prevents a completed run from being labeled with
    # the status from the previous Streamlit rerun.
    status_slot = st.empty()
    st.session_state.pop(f'_actual_context_{route_state.active_workspace}', None)
    if route_state.active_workspace == "showcase":
        render_showcase_workspace(
            route_state,
            root=REPO_ROOT,
            language=st.session_state.get("app_language", "zh"),
            mode=CAPABILITIES.mode.value,
        )
    elif route_state.active_workspace == "data":
        render_data_workspace(
            route_state,
            render_body=lambda current_route: render_data_workspace_body(
                current_route, app_globals=globals()
            ),
        )
    elif route_state.active_workspace in {"strategy", "portfolio"}:
        render_research_workspace(
            route_state,
            render_body=lambda current_route: render_research_workspace_body(
                current_route, app_globals=globals()
            ),
        )
    elif route_state.active_workspace == 'experiments':
        render_experiments_workspace(route_state, public_mode=PUBLIC_MODE)
    elif route_state.active_workspace == "factors":
        from portfolio_app.research_dataset import selected_dataset
        render_factor_workspace(
            route_state,
            frame=selected_dataset(st.session_state, lambda: read_market_file(SAMPLE_ROOT / 'quant_demo_multi_symbol.csv')),
            public_mode=PUBLIC_MODE,
        )
    else:
        render_watch_workspace(
            route_state,
            render_body=lambda current_route: render_watch_workspace_body(
                current_route, app_globals=globals()
            ),
        )

    render_context_status_bar(
        route_state,
        container=status_slot,
        public_mode=PUBLIC_MODE,
        local_data_available=bool(cached_symbols(str(DEFAULT_DATA_ROOT))),
    )



def _metric_comparison_panels(frame, label, titles):
    figure = make_subplots(rows=1, cols=3, subplot_titles=titles, horizontal_spacing=.10)
    for column, (metric, title) in enumerate(zip(('annual_return','sharpe','max_drawdown'), titles), 1):
        fmt = '.2f' if metric == 'sharpe' else '.1%'
        figure.add_trace(go.Scatter(x=frame[metric], y=frame[label], mode='markers', name=title,
            marker=dict(size=9,color=PALETTE[0] if column<3 else '#B65269'),
            hovertemplate='%{y}<br>'+title+' %{x:'+fmt+'}<extra></extra>'),row=1,col=column)
        figure.update_xaxes(tickformat=fmt, rangemode='tozero', showgrid=True, row=1,col=column)
        figure.update_yaxes(type='category',autorange='reversed',showgrid=True,dtick=1, row=1,col=column)
    style_chart(figure, height=max(300,140+len(frame)*36))
    figure.update_layout(showlegend=False,hovermode='closest',margin_t=65)
    return figure


if __name__ == "__main__":
    if resolve_capability_mode() is not CapabilityMode.LOCAL:
        raise RuntimeError("portfolio_app.local_app requires explicit PORTFOLIO_MODE=local")
    try:
        main()
    except Exception as exc:
        show_safe_error(exc)
        st.info('可从侧栏返回原工作区；已完成结果保留在当前会话。')
