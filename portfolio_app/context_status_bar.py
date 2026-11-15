"""Shared context status rendering for the local research workbench."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from html import escape

import streamlit as st
from portfolio_app.research_help import help_link

from portfolio_app.ui_copy import (
    build_context_status,
    context_research_state,
    display_dataset_id,
    resolve_data_source,
)


def select_context_data_source(
    *,
    workspace: str,
    public_mode: bool,
    session_state: Mapping[str, Any],
    local_data_available: bool,
) -> str:
    """Select a source from explicit route/session evidence, failing closed."""
    if workspace == "showcase":
        selected_source = "curated_research_summary"
    elif workspace in {"strategy", "portfolio", "factors"}:
        selected_source = "synthetic"
    elif workspace == "watch":
        selected_source = session_state.get("dashboard_source")
        if selected_source is None:
            selected_source = "本地行情" if not public_mode and local_data_available else "合成示例"
    elif workspace == "data":
        selected_source = session_state.get("analysis_source", "合成示例")
    else:
        selected_source = "synthetic"
    return {
        "合成示例": "synthetic",
        "synthetic": "synthetic",
        "文件导入": "file_import",
        "file_import": "file_import",
        "本地行情": "local_market",
        "local_market": "local_market",
        "公开研究摘要": "curated_research_summary",
        "curated_research_summary": "curated_research_summary",
    }.get(str(selected_source), "synthetic")


def current_context_research_state(route_state: Any, *, session_state: Mapping[str, Any]) -> str:
    """Read the latest lifecycle state without inferring from the page title."""
    workspace = route_state.active_workspace
    if workspace == 'strategy' and session_state.get('explicit_strategy_mode') == '因子选股':
        state = session_state.get('_factor_strategy_run')
        if state is not None:
            return context_research_state(getattr(state.status, 'value', state.status))
    state = session_state.get(f"research_run_state_{workspace}")
    if state is None and workspace == "portfolio":
        state = session_state.get("portfolio_workspace_run")
    if state is not None and hasattr(state, "status"):
        return context_research_state(getattr(state.status, "value", state.status))

    runner = session_state.get("_research_runner")
    owner = session_state.get("_research_task_owner")
    owner_workspace = owner[0] if isinstance(owner, tuple) and owner else None
    task = runner.snapshot() if runner is not None and hasattr(runner, "snapshot") else None
    task_workspace = {"watch": "dashboard", "factors": "factors"}.get(workspace)
    identity = session_state.get('_current_task_identity_' + str(task_workspace))
    saved = session_state.get('dashboard_research_submission') if workspace == 'watch' else session_state.get('factor_research_current')
    saved_identity = getattr(saved, 'key_id', None) if workspace == 'watch' else saved[0] if saved else None
    owned_current = task_workspace is not None and owner_workspace == task_workspace and (identity is None or owner[1] == identity)
    if task is not None and owned_current:
        task_status = task.get("status", "idle")
        if task_status in {"running", "queued"}:
            return "running"
        if task_status == "succeeded":
            return "result"
        if task_status in {"failed", "cancelled"}:
            return task_status
    if saved_identity is not None and identity is not None:
        return 'result' if saved_identity == identity else 'stale'
    return "draft"


def render_context_status_bar(
    route_state: Any,
    *,
    container: Any = None,
    session_state: Mapping[str, Any] | None = None,
    public_mode: bool = False,
    local_data_available: bool = False,
) -> None:
    """Render the shared six-field context bar after the workspace has rendered."""
    session_state = st.session_state if session_state is None else session_state
    target = container.container() if container is not None else st
    workspace = route_state.active_workspace
    actual = session_state.get(f'_actual_context_{workspace}', {})
    source = resolve_data_source(
        dataset_id=actual.get('dataset_id', route_state.context.dataset_id),
        selected_source=actual.get('source_kind') or select_context_data_source(
            workspace=workspace,
            public_mode=public_mode,
            session_state=session_state,
            local_data_available=local_data_available,
        ),
        public_only=public_mode,
        workspace=workspace,
    )
    state = current_context_research_state(route_state, session_state=session_state) if workspace in {
        "watch", "strategy", "portfolio", "factors", "experiments"
    } else "pending"
    status = build_context_status(
        workspace=workspace,
        dataset_id=display_dataset_id(actual.get('dataset_id', route_state.context.dataset_id), source),
        as_of=actual.get('as_of', route_state.context.as_of),
        data_source=source,
        price_basis=actual.get('price_basis', 'unspecified'),
        bar_period=actual.get('period', route_state.context.bar_period),
        state=state,
    )
    if actual.get('version'):
        status['data'] += f" / {actual['version']}"
    if actual.get('symbol'):
        status['data'] += f" · {actual['symbol']}"
    if workspace=='watch' and actual.get('source_kind')=='provider_snapshot':
        status['state']='行情浏览'
    if workspace == 'data' and actual.get('ready'):
        status['state'] = '数据已就绪 / Ready'
    if workspace == 'experiments':
        status.update(data='各运行独立数据 / Per-run datasets',
            as_of='以各运行期间为准 / Per-run periods',
            basis='以各运行清单为准 / Per-run manifests', state='记录核对 / Review')
    elif workspace == 'showcase':
        status.update(data='历史研究结果' if session_state.get('app_language', 'zh') == 'zh' else 'Historical research results',
            as_of='以所选模型期间为准' if session_state.get('app_language', 'zh') == 'zh' else 'Selected model period',
            basis='各情景独立成本' if session_state.get('app_language', 'zh') == 'zh' else 'Scenario-specific costs',
            state='本地浏览' if session_state.get('app_language', 'zh') == 'zh' else 'Local review')
    elif workspace in {'watch', 'factors', 'strategy', 'portfolio', 'data'} and not actual:
        status.update(data='尚无有效输入 / No valid input', as_of='等待数据 / Awaiting data',
            basis='尚未确认 / Unconfirmed', state='等待有效输入 / Awaiting valid input')
    if workspace == 'data' and session_state.get('data_service_tab', '更新') != '文件导入' and not public_mode:
        service = session_state.get('_data_service_context')
        if service:
            status.update(data=f"已核对行情 · {service['dataset_id']} / v{service['generation']}",
                as_of=service['as_of'], basis='原始价 · 日线', state='行情浏览')
        else:
            status.update(data='数据服务', as_of='以所选数据集为准', basis='按数据集查看', state='更新与核对')
    fields = (
        ("工作区 / Workspace", status["workspace"]),
        ("数据 / Data", status["data"]),
        ("截至 / As of", status["as_of"]),
        ("口径 / Basis", status["basis"]),
        ("状态 / State", status["state"]),
        ("模式 / Mode", status["mode"]),
    )
    if session_state.get('app_language', 'zh') == 'zh':
        # Keep complete data/version strings; shorten only the known UI glosses.
        import re
        fields = tuple((label.split(' / ')[0], re.sub(
            r' / (?:Watch|Factors|Strategy|Portfolio|Data|Experiments|Showcase|Synthetic demo|'
            r'Local market|Checked market data|File import|QFQ|HFQ|Raw|Synthetic|Daily|Weekly|Monthly|'
            r'Draft|Result|Stale|Running|Failed|Cancelled|Ready|Review|Pending|Unspecified|'
            r'Curated research summary|Per-run datasets|Per-run periods|Per-run manifests|'
            r'Historical offline research simulation)(?=\s*[·/]|$)', '', value))
            for label, value in fields)
        fields = tuple((label, value.split(' / As of ')[0].removeprefix('截至 ')
                        if label == '截至' else value) for label, value in fields)
    target.markdown(
        "<div class='quant-context-status'>"
        + "".join(f"<span{' data-context-field=mode' if label.startswith(('模式', 'Mode')) else ''}><b>{label}</b><br>{escape(value)}</span>" for label, value in fields)
        + "</div>",
        unsafe_allow_html=True,
    )
    if workspace in {"watch", "factors", "strategy", "portfolio", "experiments"}:
        def explain():
            st.write({'synthetic': '使用生成的示例行情。', 'local_market': '使用本地行情文件。',
                      'file_import': '使用本次导入的数据。',
                      'provider_snapshot':'使用已核对的原始日线快照，来源与版本保存在本机。'}.get(source, '使用公开研究摘要。'))
            st.write('公司行为和历史交易规则核验完成后开放研究。' if source=='provider_snapshot'
                else '结果为历史离线模拟。期间、价格口径和成本以当前运行记录为准。')
            if workspace == 'watch':
                st.write('成交量单位为股，成交额单位为元。' if source=='provider_snapshot'
                    else '成交量与成交额沿用源文件单位；缺失值显示为 —。')
            if workspace == 'experiments':
                st.write('各记录使用独立数据和期间，比较前请核对运行清单。')
        with target.container():
            help_link('数据与方法', explain, key='context_data_method')
