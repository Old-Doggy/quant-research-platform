"""Small shared page primitives; research inputs stay in workspace code."""
from html import escape

import streamlit as st


def workspace_heading(title: str, description: str = '') -> None:
    st.title(title)
    if description:
        st.html(f'<div class="quant-workspace-heading"><p>{escape(description)}</p></div>')


def research_columns(workspace: str):
    """Keep the parameter widgets mounted when their panel is collapsed.

    Streamlit drops widget state when widgets are skipped. Rendering the same
    widgets into a closed popover preserves drafts and running-result identity.
    """
    key = f'_parameters_collapsed_{workspace}'
    def toggle_parameters():
        st.session_state[key] = not st.session_state.get(key, False)
    controls, toggle = st.columns([5, 1])
    with toggle:
        st.button('展开参数' if st.session_state.get(key) else '收起参数',
                  key=f'parameters_toggle_{workspace}', type='tertiary', width='stretch',
                  on_click=toggle_parameters)
    if st.session_state.get(key, False):
        with controls:
            settings = st.popover('研究参数', width='content')
        results = st.container()
    else:
        settings_column, results = st.columns([1, 3.5], gap='large')
        settings = settings_column.container(key=f'{workspace}_parameters')
    return settings, results
