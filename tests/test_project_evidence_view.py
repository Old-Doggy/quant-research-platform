from io import BytesIO
import json
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def evidence_app(model):
    return AppTest.from_string(f"""
from pathlib import Path
from portfolio_app.showcase import build_strategy_showcases
from portfolio_app.project_evidence import build_project_evidence
from portfolio_app.project_evidence_view import render_project_evidence
from portfolio_app.local_project_curves import load_project_curve
root=Path({str(ROOT)!r})
card=next(c for c in build_strategy_showcases(root,public_only=True) if c['model_id']=={model!r})
view=build_project_evidence(root,card)
for layer in view['layers']:
    layer['curve']=load_project_curve(root,{model!r},layer['key'])
render_project_evidence(view,model_id={model!r},language='zh')
""").run()


def test_cost_switch_keeps_exact_numeric_metrics_and_download(monkeypatch):
    import streamlit as st
    captures=[]
    original=st.download_button
    def capture(label,data,*args,**kwargs):
        captures.append((label,data))
        return original(label,data,*args,**kwargs)
    monkeypatch.setattr(st,'download_button',capture)
    app=evidence_app('model1')
    app.segmented_control(key='evidence_page_model1_zh').set_value('cost').run()
    assert not app.exception
    assert len(app.get('plotly_chart'))==1 and not app.dataframe
    app.segmented_control(key='evidence_display_model1_cost_zh').set_value('table').run()
    assert not app.exception and not app.get('plotly_chart')
    table=app.dataframe[0].value
    source=pd.read_csv(ROOT/'public_evidence/model1_summary.csv')
    assert table['年化收益'].tolist()==pytest.approx(source.annual_return.tolist())
    assert pd.api.types.is_numeric_dtype(table['夏普'])
    exported=pd.read_csv(BytesIO(captures[-1][1]))
    pd.testing.assert_frame_equal(exported,table,check_exact=False,rtol=1e-12,atol=1e-12)


def test_annual_switch_retains_negative_partial_year_and_selected_download(monkeypatch):
    import streamlit as st
    captures=[]
    original=st.download_button
    def capture(label,data,*args,**kwargs):
        captures.append((label,data))
        return original(label,data,*args,**kwargs)
    monkeypatch.setattr(st,'download_button',capture)
    app=evidence_app('model3')
    app.segmented_control(key='evidence_page_model3_zh').set_value('annual').run()
    assert not app.exception and not app.dataframe
    app.segmented_control(key='evidence_display_model3_annual_zh').set_value('table').run()
    table=app.dataframe[0].value
    assert table.loc[table['年度']=='2022','年化收益'].iloc[0]<0
    app.selectbox(key='evidence_year_model3_zh').set_value('2026').run()
    table=app.dataframe[0].value
    assert table['年度'].tolist()==['2026']
    assert table['覆盖'].tolist()==['不完整'] and table['交易日'].tolist()==[77]
    exported=pd.read_csv(BytesIO(captures[-1][1]),dtype={'年度':str})
    pd.testing.assert_frame_equal(exported,table,check_exact=False,rtol=1e-12,atol=1e-12)


def test_curve_download_keeps_every_original_point_and_first_day(monkeypatch):
    import streamlit as st
    captures=[]
    original=st.download_button
    def capture(label,data,*args,**kwargs):
        captures.append((label,data))
        return original(label,data,*args,**kwargs)
    monkeypatch.setattr(st,'download_button',capture)
    app=evidence_app('model1')
    assert not app.exception
    app.segmented_control(key='project_curve_display_model1_zh').set_value('table').run()
    original_curve=json.loads((ROOT/'public_evidence/curves/model1--base.json').read_text(encoding='utf-8'))
    exported=pd.read_csv(BytesIO(captures[-1][1]))
    assert len(exported)==len(original_curve['points'])
    assert exported['日期'].tolist()==[p['date'] for p in original_curve['points']]
    assert exported['净值'].tolist()==pytest.approx([p['value'] for p in original_curve['points']],abs=1e-12)
    assert exported['回撤'].tolist()==pytest.approx([p['drawdown'] for p in original_curve['points']],abs=1e-12)


def test_annual_chart_preserves_sign_units_and_partial_year_without_inference():
    from portfolio_app.project_evidence_view import _annual_chart
    from portfolio_app.project_evidence import build_project_evidence
    from portfolio_app.showcase import build_strategy_showcases
    card=next(c for c in build_strategy_showcases(ROOT,public_only=True) if c['model_id']=='model3')
    rows=build_project_evidence(ROOT,card)['annual']
    figure=_annual_chart(rows,zh=False,revision='sample')
    assert list(figure.data[0].y)==[r['metrics']['annual_return'] for r in rows]
    assert list(figure.data[0].marker.pattern.shape)==['/' if r['incomplete'] else '' for r in rows]
    assert figure.data[0].y[[r['year'] for r in rows].index('2022')]<0
    assert figure.data[0].customdata[-1][1]==77
    assert 'Partial year' in figure.data[0].customdata[-1][2]
    assert figure.layout.yaxis.tickformat=='.0%'


def test_incomparable_costs_and_missing_annual_do_not_gain_comparison_or_download():
    app=evidence_app('model7')
    for page in ['cost','annual']:
        app.segmented_control(key='evidence_page_model7_zh').set_value(page).run()
        assert not app.exception and not app.get('plotly_chart')
        assert not app.get('download_button')
