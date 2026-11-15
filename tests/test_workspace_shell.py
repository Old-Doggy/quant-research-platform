from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_collapsing_parameters_keeps_the_strategy_draft(monkeypatch, tmp_path):
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('PORTFOLIO_MODE', 'local')
    monkeypatch.setenv('PORTFOLIO_DATA_ROOT', str(tmp_path / 'no-market'))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'streamlit_app.py'), default_timeout=30)
    app.run()
    app.radio(key='workspace_route_selector').set_value('strategy').run()
    app.selectbox(key='explicit_strategy_strategy').select('mean_reversion').run()
    original = app.session_state['research_run_state_strategy'].draft_fingerprint
    app.button(key='parameters_toggle_strategy').click().run()
    assert not app.exception
    assert app.session_state['_parameters_collapsed_strategy']
    assert app.button(key='parameters_toggle_strategy').label == '展开参数'
    assert app.selectbox(key='explicit_strategy_strategy').value == 'mean_reversion'
    assert app.session_state['research_run_state_strategy'].draft_fingerprint == original
    app.button(key='parameters_toggle_strategy').click().run()
    assert not app.exception
    assert app.button(key='parameters_toggle_strategy').label == '收起参数'
    assert app.selectbox(key='explicit_strategy_strategy').value == 'mean_reversion'
    assert app.session_state['research_run_state_strategy'].draft_fingerprint == original
