from pathlib import Path
import time

from streamlit.testing.v1 import AppTest


def test_completed_watch_uses_shared_selected_model_with_published_curve(tmp_path, monkeypatch):
    monkeypatch.setenv('PORTFOLIO_MODE', 'local')
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('PORTFOLIO_DATA_ROOT', str(tmp_path / 'no-market'))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'streamlit_app.py'),
                           default_timeout=30).run()
    app.button(key='submit_dashboard_research').click().run()
    for _ in range(50):
        if app.exception or app.tabs:
            break
        time.sleep(.1)
        app.run()
    assert not app.exception
    assert app.selectbox(key='dossier_project_zh').value == 'model1'
    assert not any('正式成本压力测试' in item.label for item in app.expander)
    project_tab = next(tab for tab in app.tabs if tab.label == '研究项目')
    assert len(project_tab.get('plotly_chart')) == 1
    app.selectbox(key='dossier_project_zh').set_value('model6').run()
    assert not app.exception
    app.selectbox(key='evidence_layer_model6_zh').set_value('cost_x2').run()
    assert not app.exception
    assert len(next(tab for tab in app.tabs if tab.label == '研究项目').get('plotly_chart')) == 1
    assert any('研究验收未通过' in item.value for item in app.markdown)
