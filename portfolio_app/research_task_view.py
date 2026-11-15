"""Streamlit polling for a single session task; workers never call Streamlit."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from .research_manifest import computation_revision
from .research_result_cache import build_research_cache_key
from .research_runtime import ResearchRunner, TaskJournal
from .research_run_state import begin_run, complete_run, fail_run
from .research_diagnostics import configure_diagnostics, show_safe_error
from .ui_copy import format_research_status


def research_task_status_label(task):
    """Return one truthful bilingual label for a runner snapshot."""
    status = task.get('status', 'idle')
    if status == 'idle':
        return format_research_status('draft')
    if status == 'queued':
        return format_research_status('queued')
    if status == 'running':
        return format_research_status('running', phase=task.get('phase') or 'queued')
    if status == 'succeeded':
        return format_research_status('succeeded', cache_hit=bool(task.get('cache_hit')))
    if status == 'cancelled':
        return format_research_status('cancelled')
    if status == 'failed':
        return format_research_status('failed', recoverable=True)
    raise ValueError(f'unknown research task status: {status}')


def session_runner(*, public_mode=False):
    if '_research_runner' not in st.session_state:
        import sqlite3
        journal = None
        if not public_mode:
            try:
                from .state_paths import state_root
                configure_diagnostics(state_root() / 'workbench_tasks' / 'diagnostics.jsonl')
                journal = TaskJournal(state_root() / 'workbench_tasks' / 'tasks.sqlite')
            except (sqlite3.DatabaseError, OSError) as exc:
                show_safe_error(exc, operation='journal')
                st.session_state['_task_journal_unavailable'] = True
        st.session_state['_research_runner'] = ResearchRunner(journal=journal)
    if st.session_state.get('_task_journal_unavailable'):
        st.warning('任务记录不可用，未读取损坏内容；本次仅在内存运行，请下载结果并检查本地存储。')
    return st.session_state['_research_runner']


@st.fragment(run_every=.5)
def _task_progress(runner, workspace):
    task = runner.snapshot()
    if task['status'] != 'running':
        st.rerun()
    st.progress(task['progress'], text=f"{research_task_status_label(task)} · {task['elapsed']:.1f} 秒")
    if task['elapsed'] > 10:
        st.caption('研究仍在进行；可以取消，或切到看盘，已完成结果保留。')
    if st.button('取消当前研究', key='cancel_background_research_' + workspace, disabled=task['cancel_requested']):
        runner.cancel()
        st.rerun(scope='fragment')
    if task['cancel_requested']:
        st.caption('已请求取消，等待当前计算步骤结束；本次结果不会提交。')


def background_task(*, workspace, identity, compute, start=False, public_mode=False,
                    show_foreign_progress=True):
    """Return (current snapshot, successful result); reject other-workspace overlap."""
    st.session_state['_current_task_identity_' + workspace] = identity
    runner = session_runner(public_mode=public_mode)
    if start:
        if runner.snapshot()['status'] == 'running':
            st.warning('已有研究运行中，请先等待或取消；不会重复提交。')
        else:
            previous = runner.snapshot()
            previous_owner = st.session_state.get('_research_task_owner')
            if (previous['status'] in {'succeeded', 'failed', 'cancelled'} and previous_owner
                    and previous_owner[0] != workspace
                    and st.session_state.get('_delivered_task_' + previous_owner[0]) != previous['task_id']):
                # Preserve every terminal state before another workspace replaces
                # the runner, including failures/cancellations needed for retry.
                st.session_state['_completed_task_' + previous_owner[0]] = (
                    previous_owner[1], previous, runner.result())
            key = build_research_cache_key(dataset_id=workspace, data_version=identity,
                processing={'revision': computation_revision()}, engine_id='session-task.v1')
            runner.start(key, compute)
            st.session_state['_research_task_owner'] = (workspace, identity)
    owner = st.session_state.get('_research_task_owner')
    task = runner.snapshot()
    if owner != (workspace, identity):
        saved = st.session_state.get('_completed_task_' + workspace)
        if saved and saved[0] == identity:
            del st.session_state['_completed_task_' + workspace]
            st.session_state['_delivered_task_' + workspace] = saved[1]['task_id']
            return saved[1], saved[2]
        if task['status'] == 'running' and owner and owner[0] == workspace:
            runner.cancel()
            st.warning('配置或数据已改变，旧任务正在取消；不会套用旧配置结果。')
        if task['status'] == 'running' and show_foreign_progress:
            _task_progress(runner, workspace)
        return {'status': 'idle'}, None
    if task['status'] == 'running':
        _task_progress(runner, workspace)
        return task, None
    elif task['status'] == 'succeeded':
        st.caption(f"{research_task_status_label(task)} · {task['elapsed']:.2f} 秒")
    elif task['status'] == 'cancelled':
        st.info(f"{research_task_status_label(task)}；上次成功结果保留。")
    elif task['status'] == 'failed':
        st.error(f"{research_task_status_label(task)}；上次成功结果保留。")
        failure = task.get('failure') or {}
        st.caption(failure.get('action', '请检查数据或缩小范围后重试；本次不生成成功归档。'))
        if failure.get('error_id'):
            st.caption('诊断编号：' + failure['error_id'])
    delivered_key = '_delivered_task_' + workspace
    if task['status'] == 'succeeded' and st.session_state.get(delivered_key) != task['task_id']:
        result = runner.result()
        st.session_state[delivered_key] = task['task_id']
        return task, result
    return task, None


def background_run(state, compute, *, workspace, start=False, public_mode=False):
    """Adapt the existing run lifecycle without changing result contracts."""
    from .research_run_state import RunStatus
    runner = session_runner(public_mode=public_mode)
    pending_key = '_pending_run_' + workspace
    pending = st.session_state.get(pending_key)
    if pending and pending.draft_fingerprint == state.draft_fingerprint and pending.run_count > state.run_count:
        state = pending
    accepted = start and state.status is not RunStatus.RUNNING and runner.snapshot()['status'] != 'running'
    if accepted:
        state = begin_run(state)
        st.session_state[pending_key] = state
    task, result = background_task(workspace=workspace, identity=state.draft_fingerprint,
                                  compute=compute, start=accepted, public_mode=public_mode,
                                  show_foreign_progress=state.status is not RunStatus.RESULT)
    if state.status is RunStatus.RUNNING:
        if task['status'] == 'succeeded' and result is not None:
            state = complete_run(state, result)
        elif task['status'] in {'cancelled', 'failed'}:
            state = fail_run(state, '研究已取消' if task['status'] == 'cancelled' else '研究计算失败')
    if state.status in {RunStatus.RESULT, RunStatus.FAILED}:
        st.session_state.pop(pending_key, None)
    return state


def previous_result_selected(*, workspace, marker, available):
    """View-only recovery, scoped to a failed/stale attempt; never changes draft."""
    if not available:
        return False
    key = '_previous_result_view_' + workspace
    if st.button('查看上次成功结果', key=workspace + '_previous_result'):
        st.session_state[key] = marker
    if st.session_state.get(key) == marker:
        st.warning('上次成功结果 · 仅供查看；不代表当前配置或本次失败结果。')
        return True
    return False


def previous_run_view(state, *, workspace):
    from dataclasses import replace
    from .research_run_state import RunStatus
    if state.status not in {RunStatus.FAILED, RunStatus.STALE}:
        return state
    marker = (state.draft_fingerprint, state.run_count)
    if previous_result_selected(workspace=workspace, marker=marker, available=state.last_success is not None):
        return replace(state, status=RunStatus.RESULT, result=state.last_success, run_id=state.last_success_run_id)
    return state
