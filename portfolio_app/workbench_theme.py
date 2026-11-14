"""The approved light research canvas and fixed navigation shell."""
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from .research_charts import FONT, PALETTE


def apply_workbench_theme() -> None:
    # Default styling also reaches evidence charts without altering their data.
    template = go.layout.Template(pio.templates['plotly_white'])
    template.layout.update(font=dict(family=FONT, size=14, color='#344763'),
        colorway=list(PALETTE), paper_bgcolor='#FFFFFF', plot_bgcolor='#FFFFFF',
        hoverlabel=dict(font=dict(family=FONT, size=14)),
        xaxis=dict(tickfont=dict(size=14), title=dict(font=dict(size=14)), automargin=True),
        yaxis=dict(tickfont=dict(size=14), title=dict(font=dict(size=14)), automargin=True,
                   gridcolor='#E4EAF2'))
    pio.templates['quant_research'] = template
    pio.templates.default = 'quant_research'
    st.html('<style>'+Path(__file__).with_name('workbench_theme.css').read_text(encoding='utf-8')+'</style>')


def render_sidebar_brand() -> None:
    st.html('''<div class="quant-brand"><span class="quant-brand-mark" aria-hidden="true">
    <i></i></span><div class="quant-brand-text"><strong>量化研究<span style="display:block">与可视化平台</span></strong><small>QUANT RESEARCH</small></div></div>''')
