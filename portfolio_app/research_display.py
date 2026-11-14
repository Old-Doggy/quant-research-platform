"""Bound presentation payloads without altering research samples or statistics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def check_research_size(frame, *, max_rows=150000, max_bytes=96 * 1024 * 1024):
    if len(frame) > max_rows or int(frame.memory_usage(index=True, deep=True).sum()) > max_bytes:
        raise ValueError('研究样本超过本地内存预算，请缩小标的或日期范围后重试。')


def page_frame(frame, *, page, page_size=100):
    if type(page) is not int or page < 0 or page_size not in (50, 100, 200):
        raise ValueError('invalid page or page size')
    return frame.iloc[page * page_size:(page + 1) * page_size].copy()


def envelope_sample(frame, *, value, max_points=600):
    """Retain bucket min/max and one missing-value marker, plus endpoints."""
    if max_points < 5:
        raise ValueError('at least five points required')
    if len(frame) <= max_points:
        return frame.copy()
    indices = {0, len(frame) - 1}
    for bucket in np.array_split(np.arange(1, len(frame) - 1), max(1, (max_points - 2) // 3)):
        values = pd.to_numeric(frame.iloc[bucket][value], errors='coerce').to_numpy()
        finite = np.isfinite(values)
        if finite.any():
            available = bucket[finite]
            indices.add(int(available[np.argmin(values[finite])]))
            indices.add(int(available[np.argmax(values[finite])]))
        if not finite.all():
            indices.add(int(bucket[np.flatnonzero(~finite)[0]]))
    return frame.iloc[sorted(indices)].copy()


def render_paged_table(frame, *, key, label=None):
    import streamlit as st
    if label:
        st.caption(label)
    if len(frame) > 100:
        pages = (len(frame) + 99) // 100
        widget = key + '_page'
        if st.session_state.get(widget, 1) > pages:
            st.session_state[widget] = 1
        page = st.number_input('页码', 1, pages, 1, key=widget)
        shown = page_frame(frame, page=int(page) - 1)
        st.caption(f'共 {len(frame):,} 行 · 第 {page}/{pages} 页 · 每页最多 100 行；导出保留完整结果。')
    else:
        shown = frame
    st.dataframe(shown, hide_index=True, width='stretch')


def prepared_download(*, key, identity, build):
    """Retain only the latest serialized archive per download, not every rerun."""
    import streamlit as st
    saved = st.session_state.get(key)
    if saved is None or saved[0] != identity:
        saved = (identity, build())
        st.session_state[key] = saved
    return saved[1]
