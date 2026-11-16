"""Experiment and showcase workspace route adapters."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import streamlit as st

from portfolio_app.research_audit_view import render_run_comparison
from portfolio_app.showcase_workspace import render_showcase_workspace as _render_showcase

T = TypeVar("T")


def render_experiments_workspace(
    route_state: Any,
    *,
    public_mode: bool,
    render_body: Callable[[Any, bool], T] | None = None,
) -> T | None:
    """Render experiment records only when the router selected experiments."""
    if getattr(route_state, "active_workspace", None) != "experiments":
        raise ValueError("experiments workspace requires the experiments route")
    if render_body is not None:
        return render_body(route_state, public_mode)
    st.title("实验记录")
    history, audit = st.tabs(['已保存结果', '口径核对'], on_change='rerun', key='experiments_view')
    if history.open:
        with history:
            from .result_history_view import render_result_history
            render_result_history(public_mode=public_mode)
    if audit.open:
        with audit:
            render_run_comparison(public_mode=public_mode)
    return None


def render_showcase_workspace(
    route_state: Any,
    *,
    root: str | Path,
    language: str,
    mode: str,
    render_body: Callable[[Any, str | Path, str, str], T] | None = None,
) -> T | None:
    """Render the showcase only when the router selected showcase."""
    if getattr(route_state, "active_workspace", None) != "showcase":
        raise ValueError("showcase workspace requires the showcase route")
    if render_body is not None:
        return render_body(route_state, root, language, mode)
    _render_showcase(root, language=language, mode=mode)
    st.caption(
        "下载的原始证据文件保留源文件语言。"
        if language == "zh"
        else "Downloaded evidence files retain their original source language."
    )
    return None
