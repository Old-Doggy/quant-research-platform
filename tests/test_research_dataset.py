import pandas as pd
import pytest

from portfolio_app.research_dataset import activate_dataset, selected_dataset, record_context
from test_self_audit_regressions import bars


def test_registered_input_owned_copy_and_actual_context():
    source, session = bars(), {}
    activate_dataset(session, source, dataset_id='my_dataset', version='v002', source_kind='file_import')
    source.loc[0, 'close'] = 999
    selected = selected_dataset(session, lambda: pytest.fail('fell back to demo'))
    assert selected.loc[0, 'close'] != 999
    record_context(session, 'strategy', selected)
    actual = session['_actual_context_strategy']
    assert actual['dataset_id'] == 'my_dataset' and actual['version'] == 'v002'
    assert actual['as_of'] == selected.trade_date.max().date().isoformat()
    selected.loc[0, 'close'] = 333
    assert selected_dataset(session, lambda: None).loc[0, 'close'] != 333


def test_cannot_activate_bad_input_and_can_select_demo_explicitly():
    source, session = bars(), {}
    source.loc[0, 'high'] = 1
    with pytest.raises(ValueError, match='quality'):
        activate_dataset(session, source, dataset_id='bad', version='v001', source_kind='file_import')
    assert not session
    assert selected_dataset(session, lambda: 'demo') == 'demo'


def test_registered_selection_survives_navigation_widget_cleanup(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PORTFOLIO_MODE', 'local')
    app = AppTest.from_file(str(Path('portfolio_app/local_app.py').resolve()), default_timeout=30)
    activate_dataset(app.session_state, pd.concat([bars('AAA'), bars('BBB')], ignore_index=True),
        dataset_id='custom', version='v002', source_kind='file_import')
    app.query_params.update(workspace='factors')
    app.run()
    for workspace in ['strategy', 'portfolio', 'watch', 'factors']:
        app.radio(key='workspace_route_selector').set_value(workspace).run()
        assert not app.exception
        actual = app.session_state[f'_actual_context_{workspace}']
        assert actual['dataset_id'] == 'custom'
        assert app.session_state['_use_registered_research_dataset'] is True


def test_watch_source_preference_survives_navigation(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PORTFOLIO_MODE', 'local')
    app = AppTest.from_file(str(Path('portfolio_app/local_app.py').resolve()), default_timeout=30).run()
    app.selectbox(key='dashboard_source').select('合成示例').run()
    app.radio(key='workspace_route_selector').set_value('data').run()
    app.radio(key='workspace_route_selector').set_value('watch').run()
    assert not app.exception
    assert app.selectbox(key='dashboard_source').value == '合成示例'
    assert app.session_state['_actual_context_watch']['source_kind'] == 'synthetic'
