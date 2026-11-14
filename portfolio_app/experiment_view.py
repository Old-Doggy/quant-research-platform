from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from portfolio_app.experiments import build_experiment, open_experiment, reproduce_experiment, save_experiment
from .research_manifest import compare_run_manifests
from .research_diagnostics import show_safe_error
from .research_charts import style_chart, CHART_CONFIG


def render_experiments(source: pd.DataFrame, spec: dict, root: Path) -> None:
    st.subheader("实验记录")
    policy = '下一交易日收盘模拟' if spec['mode'] == 'single' else '滞后信号收盘收益代理'
    st.caption(f"本地研究包含输入行情、参数与结果，不属于公开作品产物。执行口径：{policy}，不是实盘成交。")
    name = st.text_input("实验名称", value=f"{spec['strategy_key']} · {'组合' if spec['mode'] == 'portfolio' else spec['symbols'][0]}")
    if st.button("保存当前实验", icon=":material/save:"):
        try:
            archive = build_experiment(source, spec, name=name)
            destination = save_experiment(root, archive)
            st.session_state["last_experiment_bytes"] = archive
            st.success(f"已保存到本地实验库：{destination.name}")
        except (ValueError, OSError) as exc:
            show_safe_error(exc, operation='archive')
    if "last_experiment_bytes" in st.session_state:
        st.download_button("下载本地研究包（含行情）", st.session_state["last_experiment_bytes"],
                           file_name="private-local-experiment.zip", mime="application/zip", icon=":material/download:")
    runs = []
    for path in sorted(root.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)[:50]:
        try:
            manifest, _, result = open_experiment(path.read_bytes())
            runs.append((path, manifest, result))
        except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
            show_safe_error(exc, operation='archive')
            st.warning('已跳过无效实验；其他已保存记录仍可查看。')
    if not runs:
        st.info("实验库暂无记录。")
        return
    index = st.multiselect("对比已保存实验", list(range(len(runs))), default=[0],
                           format_func=lambda value: f"{runs[value][1]['name']} · {runs[value][1]['created_at'][:19]}", filter_mode=None)
    if index:
        comparison = compare_run_manifests([runs[number][1].get('run_manifest', {}) for number in index])
        if not comparison['ranking_allowed']:
            st.warning('口径不一致或旧实验缺少完整清单：禁止直接排名，仅按选择顺序并排查看。')
            st.dataframe(pd.DataFrame(comparison['differences']).drop(columns=['values'], errors='ignore'),
                         hide_index=True, width='stretch')
        else:
            st.caption('运行清单核验通过：数据、期间、成本和引擎口径一致。')
        rows, figure = [], go.Figure()
        for number in index:
            _, manifest, result = runs[number]
            metrics = manifest["metrics"]
            rows.append({"实验": manifest["name"], "类型": manifest["spec"]["mode"],
                         "成本": f"{manifest['spec']['transaction_cost']:.2%}",
                         "数据指纹": manifest["data_sha256"][:12],
                         "收益": f"{metrics['total_return']:.2%}", "最大回撤": f"{metrics['max_drawdown']:.2%}",
                         "起始日": str(result["trade_date"].min().date()), "截止日": str(result["trade_date"].max().date())})
            figure.add_trace(go.Scatter(x=result["trade_date"], y=result["equity"], name=f"{manifest['name']} {number + 1}",
                mode='lines', connectgaps=False,
                hovertemplate='%{x|%Y-%m-%d}<br>单位净值 %{y:.4f}<extra>%{fullData.name}</extra>'))
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("不同数据指纹、标的、区间或成本的实验不构成同口径收益排名。")
        style_chart(figure, title='已保存实验 · 单位净值', height=400, revision='experiment-comparison')
        figure.update_xaxes(tickformat='%Y-%m', hoverformat='%Y-%m-%d', nticks=6)
        st.plotly_chart(figure, width="stretch", key="experiment-comparison", config=CHART_CONFIG)
    selected = st.selectbox("复现已保存实验", list(range(len(runs))), format_func=lambda value: runs[value][1]["name"], filter_mode=None)
    if st.button("重新计算并核对", icon=":material/replay:"):
        try:
            replay = reproduce_experiment(runs[selected][0].read_bytes())
            pd.testing.assert_frame_equal(runs[selected][2], replay, check_dtype=False, check_exact=False, rtol=1e-10, atol=1e-10)
            st.success("重新计算与保存结果一致。")
        except (ValueError, AssertionError, OSError) as exc:
            show_safe_error(exc, operation='replay')
