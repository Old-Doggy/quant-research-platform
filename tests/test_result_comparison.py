import pandas as pd
import pytest


def projection(dates,nav):
    from test_research_manifest import manifest
    return dict(curve=pd.DataFrame(dict(trade_date=pd.to_datetime(dates),nav=nav,
        drawdown=[0.]*len(nav))),metrics={},parameters=dict(strategy='trend'),manifest=manifest())


def test_comparison_preserves_period_and_initial_costs_and_marks_incomparable():
    from portfolio_app.result_comparison import compare_projections,comparison_curve
    first=projection(['2025-01-02','2025-01-03'],[.99,1.1])
    second=projection(['2025-01-03','2025-01-06'],[1.,.9])
    result=compare_projections({'a':first,'b':second})
    assert result['comparable'] is False
    assert result['summary'].start.tolist()==['2025-01-02','2025-01-03']
    assert result['curves']['a'].nav.iloc[0]==.99
    assert len(result['curves']['a'])==2
    assert 'period' in result['differences']
    chart=comparison_curve(result)
    assert list(chart.data[0].y)==[.99,1.1]
    assert first['curve'].nav.iloc[0]==.99


def test_same_dates_require_same_manifest_basis_and_parameters_differ_explicitly():
    from portfolio_app.result_comparison import compare_projections
    a=projection(['2025-01-02','2025-01-03'],[1.,1.1])
    b=projection(['2025-01-02','2025-01-03'],[1.,1.2])
    b['parameters']={'strategy':'reversal'}
    result=compare_projections({'a':a,'b':b})
    assert result['comparable'] is True and 'parameters' in result['differences']
    b['manifest']={'snapshot':'new'}
    assert compare_projections({'a':a,'b':b})['comparable'] is False
    a['manifest']=b['manifest']=None
    assert compare_projections({'a':a,'b':b})['comparable'] is False


def test_comparison_does_not_rank_factor_ic_as_nav_or_hide_bad_curve():
    from portfolio_app.result_comparison import compare_projections
    a=projection(['2025-01-02'],[1.])
    with pytest.raises(ValueError):
        compare_projections({'ic':dict(curve=None),'a':a})
    for value in [None,0.,float('inf')]:
        bad=projection(['2025-01-02'],[value])
        with pytest.raises(ValueError):
            compare_projections({'a':a,'bad':bad})
    with pytest.raises(ValueError):
        compare_projections({str(i):a for i in range(5)})


def test_comparison_view_switches_and_keeps_original_dates(tmp_path,monkeypatch):
    from test_result_history import seed
    from streamlit.testing.v1 import AppTest
    from portfolio_app.research_result_cache import build_research_cache_key
    store=seed(tmp_path)
    value=store.load('fixture-run')
    value['result_payload']['performance']['curve'][0]['date']='2024-12-31'
    store.save('second-run',build_research_cache_key(dataset_id='strategy',data_version='second',
        processing={},engine_id='fixture'),value)
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    app=AppTest.from_string('from portfolio_app.result_history_view import render_result_history\nrender_result_history(public_mode=False)').run()
    app.button_group(key='result_history_mode').set_value('多次比较').run()
    assert not app.exception and not app.get('plotly_chart')
    app.multiselect(key='result_compare_selection').set_value(['fixture-run','second-run']).run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    assert any('日期不同' in c.value for c in app.caption)
    app.button_group(key='result_compare_display').set_value('表格').run()
    assert not app.exception and len(app.dataframe)==2
    assert len(app.dataframe[0].value)==4
