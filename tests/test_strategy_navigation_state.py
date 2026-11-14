from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_single_strategy_controls_survive_mode_and_workspace_switch(monkeypatch, tmp_path):
    monkeypatch.setenv('PORTFOLIO_MODE', 'local')
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path))
    app = AppTest.from_file(str(Path('portfolio_app/local_app.py').resolve()), default_timeout=60)
    app.run()
    app.radio(key='workspace_route_selector').set_value('strategy').run()
    app.number_input(key='explicit_cost_strategy').set_value(.002).run()
    original = app.selectbox(key='explicit_strategy_strategy').value
    symbol = app.selectbox(key='explicit_strategy_symbol').value
    app.button(key='run_explicit_strategy').click().run()
    run_count = app.session_state['research_run_state_strategy'].run_count
    app.radio(key='explicit_strategy_mode').set_value('因子选股').run()
    app.radio(key='workspace_route_selector').set_value('data').run()
    app.radio(key='workspace_route_selector').set_value('strategy').run()
    app.radio(key='explicit_strategy_mode').set_value('单股模板').run()
    assert not app.exception
    assert not app.error
    assert app.selectbox(key='explicit_strategy_strategy').value == original
    assert app.selectbox(key='explicit_strategy_symbol').value == symbol
    assert app.number_input(key='explicit_cost_strategy').value == .002
    assert app.session_state['research_run_state_strategy'].run_count == run_count


def test_cleaned_widget_values_restore_last_valid_single_draft(monkeypatch):
    from types import SimpleNamespace
    from portfolio_app import research_workspace as workspace

    # A browser rerun can expose None for a widget removed by the other mode.
    saved = {'explicit_strategy_strategy': 'trend', 'explicit_cost_strategy': .002}
    session = {**dict.fromkeys(saved), '_strategy_workspace_controls': saved.copy()}
    monkeypatch.setattr(workspace, 'st', SimpleNamespace(session_state=session), raising=False)
    seen = {}
    monkeypatch.setattr(workspace, '_render_explicit_research_workspace',
                        lambda route: seen.update({k: session[k] for k in saved}))
    workspace.render_explicit_research_workspace(SimpleNamespace(active_workspace='strategy'))
    assert seen == saved
    assert session['_strategy_workspace_controls'] == saved
