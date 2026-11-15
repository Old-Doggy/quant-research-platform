"""Local Streamlit component hosting the existing offline chart renderer."""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from .chart_bridge import chart_bridge_html
from .chart_events import accept_chart_event, chart_identity

_component = components.declare_component('quant_chart', path=str(Path(__file__).with_name('chart_component')))


def render_interactive_chart(payload: dict, *, height: int, key: str):
    identity = chart_identity(payload)
    state_key = f'_chart_selection_{key}'
    old = st.session_state.get(state_key, {})
    previous_sequence = old.get('sequence', 0) if old.get('chart_id') == identity else 0
    value = _component(html=chart_bridge_html({**payload, 'selection_bridge': {'chart_id': identity}}, height=height),
                       height=height, chart_id=identity, key=f'{key}-{identity}', default=None)
    accepted = accept_chart_event(value, chart_id=identity, symbol=str(payload['symbol']),
        dates={bar['time'] for bar in payload.get('bars', [])}, last_sequence=previous_sequence)
    if accepted:
        st.session_state[state_key] = accepted
    current = st.session_state.get(state_key)
    return current if current and current.get('chart_id') == identity else None
