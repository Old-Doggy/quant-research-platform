import pandas as pd
from streamlit.testing.v1 import AppTest

from portfolio_app.research_result_cache import build_research_cache_key
from portfolio_app.result_store import ResultStore


def seed(root):
    store = ResultStore(root / 'research_results')
    key = build_research_cache_key(dataset_id='strategy', data_version='fixture',
        processing={'revision': 'old-version'}, engine_id='session-task.v1')
    store.save('fixture-run', key, {'strategy_key': 'trend', 'symbols': ('600000.SH',),
        'metrics': {'total_return': .12, 'max_drawdown': -.04},
        'result_payload': {'performance': {'curve': [
            {'date': '2025-01-02', 'nav': 1., 'drawdown': 0.},
            {'date': '2025-01-03', 'nav': 1.12, 'drawdown': 0.}]}},
        'run_manifest': {'fixture': True}})
    return store


def test_private_history_restores_chart_and_table_after_new_session(monkeypatch, tmp_path):
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path))
    seed(tmp_path)
    source = 'from portfolio_app.result_history_view import render_result_history\nrender_result_history(public_mode=False)'
    view = AppTest.from_string(source).run()
    assert not view.exception
    assert len(view.get('plotly_chart')) == 1
    assert any('保存结果' in c.value for c in view.caption)
    view.button_group(key='saved_result_display').set_value('表格').run()
    assert not view.exception and len(view.dataframe) >= 1
    restored = AppTest.from_string(source).run()
    assert not restored.exception and len(restored.get('plotly_chart')) == 1
    assert restored.session_state['saved_result_selected'] == 'fixture-run'


def test_public_history_never_reads_private_storage(monkeypatch):
    monkeypatch.setattr(ResultStore, '__init__', lambda *a: (_ for _ in ()).throw(AssertionError('private read')))
    view = AppTest.from_string('from portfolio_app.result_history_view import render_result_history\nrender_result_history(public_mode=True)').run()
    assert not view.exception
    assert not view.get('plotly_chart')


def test_corrupt_record_is_explicit_and_other_records_still_selectable(monkeypatch, tmp_path):
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path))
    store = seed(tmp_path)
    key = build_research_cache_key(dataset_id='portfolio', data_version='broken', processing={}, engine_id='test')
    store.save('broken', key, {'metrics': {}})
    (store.root / 'runs' / 'broken' / 'manifest.json').write_text('{}', encoding='utf8')
    view = AppTest.from_string('from portfolio_app.result_history_view import render_result_history\nrender_result_history(public_mode=False)').run()
    assert not view.exception and view.error
    view.selectbox(key='saved_result_selected').set_value('fixture-run').run()
    assert not view.exception and not view.error
    assert len(view.get('plotly_chart')) == 1


def test_history_projection_keeps_original_units_and_daily_series():
    from portfolio_app.result_history import result_projection
    from portfolio_app.portfolio_accounting import PortfolioAccountingResult
    from portfolio_app.portfolio_workspace import PortfolioWorkspaceResult
    ledger = pd.DataFrame({'trade_date': ['2025-01-02', '2025-01-03'], 'nav': [980., 1100.],
        'cash': [980., 1100.], 'drawdown': [-.02, 0.]})
    accounting = PortfolioAccountingResult(ledger, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}, {})
    result = PortfolioWorkspaceResult(accounting, pd.DataFrame(), [], [], {}, {'initial_cash': 1000.}, {})
    projection = result_projection({'baseline': result})
    assert projection['curve']['nav'].tolist() == [.98, 1.1]
    assert projection['curve']['drawdown'].tolist() == [-.02, 0.]
    assert projection['tables']['资金账本'].nav.tolist() == [980., 1100.]
    assert ledger.nav.tolist() == [980., 1100.]


def test_history_tabs_do_not_execute_hidden_session_audit(monkeypatch, tmp_path):
    from portfolio_app import archive_workspace
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path))
    seed(tmp_path)
    monkeypatch.setattr(archive_workspace, 'render_run_comparison',
        lambda **k: (_ for _ in ()).throw(AssertionError('hidden audit executed')))
    view = AppTest.from_string('''
from types import SimpleNamespace
from portfolio_app.archive_workspace import render_experiments_workspace
render_experiments_workspace(SimpleNamespace(active_workspace='experiments'), public_mode=False)
''').run()
    assert not view.exception
    assert len(view.get('plotly_chart')) == 1
