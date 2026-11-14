"""Readable, source-grounded explanations for the local research projects."""
from html import escape

import streamlit as st

from .model_explanations import model_explanation
from .research_help import help_link


def render_model_section(model_id, section, *, language='zh'):
    notes = model_explanation(model_id, language=language)
    zh = language == 'zh'
    if section == 'methods':
        title = '从数据到持仓' if zh else 'From data to holdings'
        rows = notes['steps']
        style = 'model-flow'
    elif section == 'data':
        title = '输入数据如何参与研究' if zh else 'How the inputs are used'
        rows = notes['data']
        style = 'model-inputs'
    elif section == 'validation':
        title = '验证什么，怎样判断结果' if zh else 'What is tested and how to read it'
        rows = notes['validation']
        style = 'model-validation'
    else:
        raise ValueError('Unknown explanation section')
    cards = ''.join(
        f'<article class="model-note"><span class="model-step">{i:02d}</span>'
        f'<div><h4>{escape(label)}</h4><p>{escape(body)}</p></div></article>'
        for i, (label, body) in enumerate(rows, 1))
    lead = f'<p class="model-idea">{escape(notes["idea"])}</p>' if section == 'methods' else ''
    timing = ''
    if section in {'data', 'methods'}:
        timing = ('<div class="model-timing"><strong>' + ('时间顺序' if zh else 'Timing') +
                  '</strong><p>' + escape(notes['timing']) + '</p></div>')
    st.html(f'<section class="model-explanation" lang="{language}" data-model-notes="{model_id}" '
            f'data-section="{section}"><h3>{title}</h3>{lead}'
            f'<div class="{style}">{cards}</div>{timing}</section>')
    if section == 'methods':
        def sources():
            st.write('说明依据以下训练、回测和审计记录整理。历史净值的具体批次见结果页“数据说明”。' if zh else
                     'These notes refer to the training, backtest and audit records below. The result page identifies the historical curve and run.')
            for source in notes['sources']:
                st.text(source)
            st.caption('当前训练代码描述模型结构；历史曲线的检查点版本以该次运行记录为准。' if zh else
                       'Current training code describes the architecture; checkpoint identity follows the historical run record.')
        help_link('说明来源' if zh else 'Source references', sources,
                  key=f'model_notes_sources_{model_id}_{language}')
