"""Compact research-work overview and one consistent bilingual detail view."""
from portfolio_app.research_help import help_link
from html import escape

import streamlit as st

from portfolio_app.project_dossiers import build_project_dossiers, _STATUS
from portfolio_app.project_evidence import build_project_evidence
from portfolio_app.project_evidence_view import _remembered_select, render_project_evidence
from portfolio_app.showcase import build_strategy_showcases
from portfolio_app.project_artifact_registry import list_project_artifacts
from portfolio_app.project_materials_view import render_project_artifacts
from portfolio_app.model_explanation_view import render_model_section


def render_project_dossiers(project_root, *, language="zh", local_results=False, embedded=False):
    records = build_project_dossiers(project_root, language=language)
    zh = language == "zh"
    layout_style = '' if embedded else '''
    [data-testid="stMainBlockContainer"]{max-width:1300px;padding-top:2.7rem;}
    [data-testid="stMainBlockContainer"] h1{font-size:1.7rem;}
    @media(max-width:640px){[data-testid="stMainBlockContainer"]{padding:2.5rem 1rem 1rem;}}
    '''
    st.html('<style>' + layout_style + '''
    .dossier-card{border:1px solid #dfe5ec;border-radius:10px;padding:15px 17px;margin-bottom:12px;background:#fff;overflow-wrap:anywhere;}
    .dossier-card h3{font-size:1rem;line-height:1.55;margin:6px 0 9px;color:#172b40;}
    .dossier-card p{font-size:.86rem;line-height:1.65;margin:7px 0;color:#45566a;}
    .dossier-card small{color:#64748b;font-size:.76rem;}
    .dossier-status{font-size:.74rem;border-radius:5px;padding:3px 6px;background:#edf5f3;color:#27675f;}
    .dossier-status.review_required{background:#fff3df;color:#875a08;}
    .dossier-status.unavailable{background:#eef0f3;color:#566070;}
    [data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] p{line-height:1.75;}
    [data-testid="stMainBlockContainer"] [data-testid="stCaptionContainer"]{overflow-wrap:anywhere;}
    @media(max-width:640px){.dossier-card{padding:12px;}}
    </style>''')
    st.html('''<style>
    .dossier-card:lang(en){word-break:normal;overflow-wrap:break-word;hyphens:auto;}
    .dossier-card:lang(zh){word-break:normal;line-break:strict;}
    .dossier-card h3{font-weight:650;}
    @media(max-width:640px){[data-testid="stMainBlockContainer"] h3{font-size:1.12rem;line-height:1.5;}}
    </style>''')
    heading = st.subheader if embedded else st.title
    heading("研究作品与工程实践" if zh else "Research Projects and Engineering Work")
    st.caption("模型原理 · 数据与交易时点 · 回测结果" if zh else "Python data analysis · Timing controls · Research validation · Visual delivery")
    def _explain_39():
        st.info("这是一个个人量化研究工作台，用于展示数据工程、研究验证、回测、组合分析和复现能力。公开策略是通用演示模板；历史研究项目的证据状态各不相同。合成数据和历史摘要不代表实时行情、真实账户收益或实盘成交。" if zh else
            "This is a personal quantitative research workbench for demonstrating data engineering, research validation, backtesting, portfolio analysis, and reproducibility. Public strategies are general demonstration templates; evidence status differs across historical research projects. Synthetic data and historical summaries are not live quotes, account returns, or live fills.")
        st.write("七个研究案例覆盖数据处理、方法实现、执行建模、稳健性检验和证据整理。按项目编号浏览；收益、资产和期间不同，不组成排行榜。" if zh else "Seven research cases cover data preparation, method implementation, execution modeling, robustness checks, and evidence organization. Browse in project order; assets, periods, and returns are not a ranking.")
        st.caption(records[0]["work_scope_note"])
        st.markdown("**展示标签**" if zh else "**Display labels**")
        st.caption("已验证：登记的公开证据可用；需复核：研究验收尚未通过；公开摘要：仅展示经过筛选的聚合摘要；演示案例：使用合成数据的通用功能示例；暂无公开证据：保留项目说明，但当前副本没有可展示的证据。" if zh else
            "Reviewed: registered public evidence is available; Review required: the research gate is still open; Reviewed summary: only curated aggregate evidence is shown; Demonstration: a generic feature example using synthetic data; No public evidence: the project description remains, but this copy has no evidence to display.")
        st.markdown("**公开边界**" if zh else "**Public disclosure boundary**")
        st.caption(("曲线读取仓库中的历史汇总结果；原始行情、模型权重和逐股仓位不包含在内。" if zh else "Curves use the bundled historical aggregates; raw market data, model weights and security-level positions are not included.") if local_results else
            ("公开展示只读取审查摘要；策略核心、参数、原始行情与标的级运行信息保持私有。" if zh else "The view reads reviewed public summaries. Strategy cores, exact settings, raw market data, and security-level runtime records remain private."))
    status_labels = {"all": "全部状态" if zh else "All statuses", **_STATUS[language]}
    model_column, status_column = st.columns([3, 1])
    with status_column:
        status_filter = _remembered_select("证据状态筛选" if zh else "Filter by evidence status", list(status_labels),
            name="dossier_status", language=language, labels=status_labels)
    records = [record for record in records if status_filter == "all" or record["evidence_status"] == status_filter]
    if not records:
        st.info("没有符合当前状态的项目，请调整筛选。" if zh else "No projects match this status. Change the filter to continue.")
        return None
    by_id = {record["model_id"]: record for record in records}
    options = list(by_id)
    saved = st.session_state.get("dossier_selected", options[0])
    widget_key = f"dossier_project_{language}"
    if st.session_state.get("dossier_widget_language") != language or st.session_state.get(widget_key) not in options:
        st.session_state[widget_key] = saved if saved in options else options[0]
    st.session_state["dossier_widget_language"] = language
    with model_column:
        selected = st.selectbox("选择项目" if zh else "Choose a project", options, filter_mode=None,
            format_func=lambda key: by_id[key]["title"], key=widget_key)
    st.session_state["dossier_selected"] = selected
    record = by_id[selected]
    st.html(f'''<article class="dossier-card" lang="{language}" data-project="{selected}">
        <small>{escape(record['category'])}</small>
        <span class="dossier-status {record['evidence_status']}">{escape(record['status_label'])}</span>
        <h3>{escape(record['title'])}</h3><p>{escape(record['question'])}</p>
        <p>{escape(record['data_summary'])}</p></article>''')
    cards = build_strategy_showcases(project_root, public_only=True)
    evidence = build_project_evidence(project_root, next(card for card in cards if card["model_id"] == selected), language=language)
    if local_results:
        from portfolio_app.local_project_curves import load_project_curve
        if selected == 'model2':
            curve = load_project_curve(project_root, selected, 'local_native_wfo')
            if curve['points']:
                evidence['layers'].append(dict(key='local_native_wfo',
                    label='原生引擎 · 年度滚动样本外' if zh else 'Native engine · Annual walk-forward OOS',
                    status='review_required', status_label='研究验收未通过' if zh else 'Gate review required',
                    period=f"{curve['points'][0]['date']} → {curve['points'][-1]['date']}",
                    cost_assumption='沿用原生引擎成本' if zh else 'Native engine costs',
                    limitations='2026-05-04 本地原生引擎研究，按已保存的逐年选参记录重建；与 2026-05-05 股票池验证摘要为不同批次。' if zh else 'Local native-engine research dated 2026-05-04, replayed from saved annual choices; separate from the pool validation batch dated 2026-05-05.',
                    source='本地逐日回测与年度选参记录' if zh else 'Local daily backtests and annual fold choices',metrics=curve['metrics'],curve=curve))
        for layer in evidence['layers']:
            if 'curve' not in layer:
                layer['curve'] = load_project_curve(project_root, selected, layer['key'])
            if layer['curve']['points']:
                points = layer['curve']['points']
                layer['period'] = f"{points[0]['date']} → {points[-1]['date']} · {len(points):,} " + ('个交易日' if zh else 'sessions')
                layer['source'] = '本地历史回测记录' if zh else 'Local historical backtest records'
    sections = sorted(record['sections'], key=lambda section: section['id'] != 'results')
    tabs = st.tabs([section["title"] for section in sections])
    for tab, section in zip(tabs, sections):
        with tab:
            if section["id"] == "results":
                render_project_evidence(evidence, model_id=selected, language=language)
            elif section["id"] == "artifacts":
                render_project_artifacts(project_root, list_project_artifacts(project_root, selected, language=language), language=language)
            elif section['id'] in {'data', 'methods', 'validation'}:
                render_model_section(selected, section['id'], language=language)
            else:
                for item in section["items"]:
                    st.markdown(f"- {item}")
    help_link('阅读说明、证据标签与展示边界' if zh else 'Reading guide and evidence boundaries', _explain_39, key='project_dossier_view.py_explain_39')
    return selected
