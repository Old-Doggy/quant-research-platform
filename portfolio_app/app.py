from __future__ import annotations

import os
from pathlib import Path
import runpy

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from portfolio_app.backtest import compare_symbol_backtests, run_backtest, run_equal_weight_portfolio
from portfolio_app.data import build_data_quality_report, build_market_summary, build_symbol_return_summary, read_market_file
from portfolio_app.strategies import STRATEGIES, generate_signal


SAMPLES = Path(__file__).resolve().parent / "sample_data"


def price_chart(frame: pd.DataFrame, symbol: str) -> go.Figure:
    chart = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.75, 0.25])
    chart.add_trace(go.Candlestick(x=frame.trade_date, open=frame.open, high=frame.high, low=frame.low, close=frame.close, name=symbol), row=1, col=1)
    for column, color in (("ma20", "#2563eb"), ("ma60", "#ea580c")):
        chart.add_trace(go.Scatter(x=frame.trade_date, y=frame[column], name=column.upper(), line={"color": color}), row=1, col=1)
    changes = frame.position.diff().fillna(frame.position)
    for mask, label, marker, color in ((changes.gt(0), "买入", "triangle-up", "#16804a"), (changes.lt(0), "卖出", "triangle-down", "#dc2626")):
        chart.add_trace(go.Scatter(x=frame.loc[mask, "trade_date"], y=frame.loc[mask, "close"], mode="markers", name=label, marker={"symbol": marker, "color": color, "size": 10}), row=1, col=1)
    chart.add_trace(go.Bar(x=frame.trade_date, y=frame.vol.fillna(0), name="成交量", marker_color="#9ca3af"), row=2, col=1)
    chart.update_layout(height=540, xaxis_rangeslider_visible=False, legend_orientation="h", margin={"l": 12, "r": 12, "t": 35, "b": 12})
    return chart


def equity_chart(frame: pd.DataFrame) -> go.Figure:
    chart = go.Figure()
    chart.add_trace(go.Scatter(x=frame.trade_date, y=frame.equity, name="策略净值", line={"color": "#167d70"}))
    chart.add_trace(go.Scatter(x=frame.trade_date, y=frame.benchmark_equity, name="基准", line={"color": "#6b7280", "dash": "dot"}))
    chart.update_layout(height=320, legend_orientation="h", margin={"l": 12, "r": 12, "t": 35, "b": 12})
    return chart


def load_frame(multi: bool, key: str) -> pd.DataFrame | None:
    with st.sidebar:
        source = st.selectbox("数据来源", ["合成示例", "文件导入"], key=f"{key}_source")
    if source == "合成示例":
        name = "quant_demo_multi_symbol.csv" if multi else "quant_demo_single_symbol.csv"
        st.caption("合成示例 · 非真实证券数据")
        return read_market_file(SAMPLES / name)
    upload = st.file_uploader("导入 CSV、Excel 或 Parquet", type=["csv", "xlsx", "xls", "parquet", "pq"], key=f"{key}_upload")
    if upload is None:
        st.info("暂无导入数据。")
        return None
    try:
        return read_market_file(upload)
    except Exception as exc:
        st.error(f"导入失败：{exc}")
        return None


def render_dashboard() -> None:
    st.title("Python 数据分析工作台")
    with st.sidebar:
        mode = st.radio("分析模式", ["单股", "等权组合"], horizontal=True)
        strategy_name = st.selectbox("策略", [item.name for item in STRATEGIES])
        strategy = next(item for item in STRATEGIES if item.name == strategy_name)
        threshold = st.slider("均值回归阈值", 0.5, 2.5, 1.0, 0.1, disabled=strategy.key != "mean_reversion")
        lookback = st.slider("展示区间", 120, 2500, 720, 30)
        cost = st.number_input("单次换手成本", min_value=0.0, max_value=0.02, value=0.001, step=0.0005, format="%.4f")
    frame = load_frame(mode == "等权组合", "dashboard")
    if frame is None:
        return
    symbols = sorted(frame.symbol.unique())
    if mode == "单股":
        symbol = st.selectbox("标的", symbols, format_func=lambda value: value or "导入标的")
        selected = frame.loc[frame.symbol.eq(symbol)].tail(lookback)
        result, metrics = run_backtest(generate_signal(selected, strategy.key, threshold), cost)
        count = "单股"
    else:
        selection = st.multiselect("组合标的", symbols, default=symbols)
        if not selection:
            st.info("暂无组合标的。")
            return
        frames = {symbol: frame.loc[frame.symbol.eq(symbol)].tail(lookback) for symbol in selection}
        result, metrics = run_equal_weight_portfolio(frames, strategy.key, threshold, cost)
        count = f"{len(selection)} 只"
    columns = st.columns(5)
    values = [f"{metrics['total_return']:.2%}", f"{metrics['annual_return']:.2%}", f"{metrics['sharpe']:.2f}", f"{metrics['max_drawdown']:.2%}", count]
    for column, label, value in zip(columns, ["区间收益", "年化收益", "夏普", "最大回撤", "分析对象"], values):
        column.metric(label, value)
    market, performance, quality = st.tabs(["行情与信号", "净值与回撤", "数据检查"])
    with market:
        if mode == "单股":
            st.plotly_chart(price_chart(result, symbol), width="stretch")
        else:
            st.dataframe(compare_symbol_backtests(frames, strategy.key, threshold, cost), width="stretch", hide_index=True)
        st.dataframe(result.tail(30), width="stretch", hide_index=True)
    with performance:
        st.plotly_chart(equity_chart(result), width="stretch")
        drawdown = result.equity / result.equity.cummax() - 1
        chart = go.Figure(go.Scatter(x=result.trade_date, y=drawdown, fill="tozeroy", name="回撤", line={"color": "#b91c1c"}))
        chart.update_layout(height=260, yaxis_tickformat=".0%", margin={"l": 12, "r": 12, "t": 20, "b": 12})
        st.plotly_chart(chart, width="stretch")
    with quality:
        st.dataframe(pd.DataFrame([build_data_quality_report(frame)]), width="stretch", hide_index=True)


def render_analysis() -> None:
    st.title("数据分析")
    frame = load_frame(True, "analysis")
    if frame is None:
        return
    overview, risk, quality = st.tabs(["数据概览", "收益与风险", "质量检查"])
    with overview:
        st.dataframe(pd.DataFrame([build_market_summary(frame)]), width="stretch", hide_index=True)
        st.dataframe(frame.tail(30), width="stretch", hide_index=True)
    with risk:
        summary = build_symbol_return_summary(frame)
        st.dataframe(summary, width="stretch", hide_index=True)
        chart = go.Figure(go.Bar(x=summary.symbol, y=summary.total_return, marker_color="#167d70"))
        chart.update_layout(height=320, yaxis_tickformat=".0%", title="区间收益")
        st.plotly_chart(chart, width="stretch")
    with quality:
        report = build_data_quality_report(frame)
        if report["status"] == "通过":
            st.success("常见质量检查通过。")
        else:
            st.warning("数据需复核。")
        st.dataframe(pd.DataFrame([report]), width="stretch", hide_index=True)


def render_comparison() -> None:
    st.title("策略比较")
    frame = load_frame(False, "comparison")
    if frame is None:
        return
    symbol = st.selectbox("标的", sorted(frame.symbol.unique()), key="comparison_symbol")
    selected = frame.loc[frame.symbol.eq(symbol)]
    cost = st.number_input("单次换手成本", min_value=0.0, max_value=0.02, value=0.001, step=0.0005, key="comparison_cost")
    rows = []
    chart = go.Figure()
    for strategy in STRATEGIES:
        result, metrics = run_backtest(generate_signal(selected, strategy.key), cost)
        rows.append({"策略": strategy.name, **metrics})
        chart.add_trace(go.Scatter(x=result.trade_date, y=result.equity, name=strategy.name))
    chart.update_layout(height=420, legend_orientation="h")
    st.plotly_chart(chart, width="stretch")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_project() -> None:
    st.title("Python 数据分析与研究工作台")
    st.write("金融日线数据应用案例。公开版本保留通用数据处理和分析方法，结果来自合成示例或本次导入的数据。")
    st.subheader("项目范围")
    st.dataframe(pd.DataFrame([
        {"模块": "数据处理", "产出": "多格式导入、字段标准化、按标的日期对齐与质量检查"},
        {"模块": "分析验证", "产出": "示例信号、成本回测、等权组合与风险统计"},
        {"模块": "工程实现", "产出": "独立依赖、可运行示例、自动化测试与交互图表"},
    ]), width="stretch", hide_index=True)
    st.subheader("分析口径")
    st.write("信号滞后一行参与收益计算，成本按持仓变化计入。收益采用收盘到收盘口径，不模拟下一开盘成交；组合是简化的动态等权收益合成。")
    st.write("年化使用252个交易日；此处夏普为年化复合收益除以年化波动、无风险收益取0，并非标准算术均值夏普。质量报告基于标准化后的数据，不保留已删除的重复行或无效日期。")
    st.subheader("限制")
    st.write("合成数据不是真实证券。示例策略不是私人研究模型复现，不包含真实历史收益。未模拟涨跌停、停牌、成交容量和完整现金账户。应用不下单。")


def main() -> None:
    local = Path(__file__).with_name("local_app.py")
    if os.environ.get("PORTFOLIO_MODE", "public").lower() == "local":
        if not local.is_file():
            raise RuntimeError("The public package does not include the private local workbench.")
        runpy.run_path(str(local), run_name="__main__")
        return
    st.set_page_config(page_title="Python Data Workbench", page_icon="Q", layout="wide")
    with st.sidebar:
        page = st.radio("页面", ["Quant Dashboard", "数据分析", "策略比较", "项目说明"])
    {"Quant Dashboard": render_dashboard, "数据分析": render_analysis, "策略比较": render_comparison, "项目说明": render_project}[page]()


if __name__ == "__main__":
    main()
