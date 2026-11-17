import pandas as pd
from streamlit.testing.v1 import AppTest


def view_source():
    return '''
from test_portfolio_workspace import inputs,run
import portfolio_app.portfolio_workspace_view as page
from portfolio_app.research_run_state import begin_run,complete_run
frames,_,_=inputs()
result=run()
def completed(state,compute,**kwargs):
    if state.result is None:
        state=complete_run(begin_run(state),dict(baseline=result,scenarios=__import__('pandas').DataFrame()))
    return state
page.background_run=completed
page.render_portfolio_workspace(__import__('pandas').concat(frames.values()),context_id='panel-fixture',public_mode=True)
'''


def test_portfolio_has_four_primary_views_and_only_active_view_draws():
    app=AppTest.from_string(view_source()).run()
    assert not app.exception
    assert [t.label for t in app.tabs]==['净值表现','收益归因','持仓交易','风险分析']
    assert len(app.get('plotly_chart'))==1
    app.session_state['portfolio_main_view']='风险分析'
    app.run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    assert any('截至' in c.value for c in app.caption)
    app.segmented_control(key='portfolio_risk_detail').set_value('流动性与容量').run()
    assert not app.exception and len(app.get('plotly_chart'))==0
    assert any('未保存成交额输入' in c.value for c in app.caption)
    app.session_state['portfolio_main_view']='持仓交易'
    app.run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    app.segmented_control(key='portfolio_holdings_detail').set_value('成交与拒单').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    app.segmented_control(key='portfolio_order_display').set_value('表格').run()
    assert not app.exception and len(app.get('plotly_chart'))==0
    app.session_state['portfolio_main_view']='收益归因'
    app.run()
    assert not app.exception and len(app.get('plotly_chart'))==2
    app.segmented_control(key='portfolio_attribution_detail').set_value('策略贡献').run()
    assert not app.exception and len(app.get('plotly_chart'))==1


def test_portfolio_archive_remains_available_without_generating_hidden_downloads(monkeypatch):
    import portfolio_app.portfolio_workspace_view as page
    calls=[];original=page.create_portfolio_archive
    monkeypatch.setattr(page,'create_portfolio_archive',lambda *a,**k:(calls.append(k['mode']),original(*a,**k))[1])
    app=AppTest.from_string(view_source()).run()
    assert not app.exception and calls==[]
    app.segmented_control(key='portfolio_performance_detail').set_value('研究归档').run()
    assert not app.exception and calls==['public_redacted']
    assert len(app.get('download_button'))==1
