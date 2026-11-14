import json
import logging
import time

from portfolio_app.research_runtime import ResearchRunner
from portfolio_app.research_result_cache import build_research_cache_key


SECRET = 'D:/private/account_998877/targets.csv token=do-not-log target_weights=secret'


def test_worker_snapshot_and_structured_logs_never_contain_exception_payload(caplog):
    runner = ResearchRunner()
    key = build_research_cache_key(dataset_id='demo', data_version='v1', processing={}, engine_id='test')
    with caplog.at_level(logging.WARNING, logger='portfolio_app.diagnostics'):
        runner.start(key, lambda token: (_ for _ in ()).throw(ValueError(SECRET)))
        deadline = time.monotonic() + 5
        while runner.snapshot()['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.01)
    task = runner.snapshot()
    assert task['status'] == 'failed'
    assert SECRET not in json.dumps(task)
    assert task['failure']['code'] == 'INPUT_INVALID'
    assert task['failure']['action']
    assert SECRET not in caplog.text


def test_safe_report_keeps_bounded_raw_details_only_in_internal_memory():
    from portfolio_app.research_diagnostics import ErrorReports
    reports = ErrorReports(max_details=2)
    first = reports.capture(ValueError(SECRET), operation='research')
    assert SECRET not in json.dumps(first)
    assert SECRET in reports.internal_detail(first['error_id'])
    reports.capture(PermissionError(SECRET), operation='import')
    latest = reports.capture(RuntimeError(SECRET), operation=SECRET)
    assert reports.internal_detail(first['error_id']) is None
    assert SECRET not in json.dumps(latest)
    assert latest['operation'] == 'research'


def test_disk_diagnostics_have_fixed_fields_and_no_raw_data(tmp_path):
    from portfolio_app.research_diagnostics import ErrorReports, diagnostic_handler
    logger = logging.getLogger('test.safe.diagnostics')
    logger.propagate = False
    path = tmp_path / 'diagnostics.jsonl'
    handler = diagnostic_handler(path)
    logger.addHandler(handler)
    try:
        report = ErrorReports(logger=logger).capture(OSError(SECRET), operation='archive')
        handler.flush()
        row = json.loads(path.read_text(encoding='utf8').strip())
        assert set(row) == {'schema', 'error_id', 'code', 'operation'}
        assert row['error_id'] == report['error_id']
        assert SECRET not in path.read_text(encoding='utf8')
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_sink_strips_injected_message_args_extras_and_traceback(tmp_path):
    from portfolio_app.research_diagnostics import diagnostic_handler
    handler = diagnostic_handler(tmp_path / 'diagnostics.jsonl')
    try:
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            import sys
            record = logging.LogRecord('test', logging.ERROR, SECRET, 1, SECRET, (), sys.exc_info())
            record.private_target = SECRET
            handler.handle(record)
        handler.flush()
        text = (tmp_path / 'diagnostics.jsonl').read_text(encoding='utf8')
        assert SECRET not in text
        assert json.loads(text)['code'] == 'TASK_FAILED'
    finally:
        handler.close()


def test_broken_log_sink_never_prints_raw_exception_or_breaks_capture(tmp_path, capsys, monkeypatch):
    from portfolio_app.research_diagnostics import ErrorReports, diagnostic_handler
    logger = logging.getLogger('test.broken.diagnostics')
    logger.propagate = False
    handler = diagnostic_handler(tmp_path / 'diagnostics.jsonl')
    logger.addHandler(handler)
    def fail(*args):
        raise OSError(SECRET)
    monkeypatch.setattr(handler, 'shouldRollover', fail)
    try:
        report = ErrorReports(logger=logger).capture(ValueError(SECRET))
        assert report['code'] == 'INPUT_INVALID'
        assert SECRET not in capsys.readouterr().err
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_worker_start_failure_is_safe_and_can_retry(monkeypatch):
    import portfolio_app.research_runtime as runtime
    original = runtime.Thread.start
    monkeypatch.setattr(runtime.Thread, 'start', lambda self: (_ for _ in ()).throw(RuntimeError(SECRET)))
    runner = ResearchRunner()
    key = build_research_cache_key(dataset_id='demo', data_version='v1', processing={}, engine_id='test')
    runner.start(key, lambda token: {'answer': 42})
    assert runner.snapshot()['status'] == 'failed'
    assert SECRET not in json.dumps(runner.snapshot())
    monkeypatch.setattr(runtime.Thread, 'start', original)
    runner.start(key, lambda token: {'answer': 42})
    deadline = time.monotonic() + 5
    while runner.snapshot()['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.01)
    assert runner.result() == {'answer': 42}


def test_safe_ui_import_error_does_not_echo_path_account_or_target(monkeypatch):
    from io import BytesIO
    from streamlit.testing.v1 import AppTest
    import portfolio_app.workbench_controls as controls
    def fail(source):
        raise PermissionError(SECRET)
    monkeypatch.setattr(controls, 'import_source_columns', fail)
    app = AppTest.from_string('''
import streamlit as st
from portfolio_app.workbench_controls import render_import_preview
render_import_preview(st.session_state['source'], key='acceptance')
''')
    source = BytesIO(b'invalid')
    source.name = 'sample.csv'
    app.session_state['source'] = source
    app.run()
    assert not app.exception
    shown = '\n'.join(item.value for kind in ('error', 'caption', 'warning') for item in app.get(kind))
    assert SECRET not in shown
    assert '诊断编号' in shown and '权限' in shown


def test_preview_service_returns_only_safe_error_report(monkeypatch):
    from io import BytesIO
    from portfolio_app.data_catalog import preview_market_import
    import portfolio_app.data_catalog as catalog
    monkeypatch.setattr(catalog, '_read_import_frame', lambda source: (_ for _ in ()).throw(ValueError(SECRET)))
    report = preview_market_import(BytesIO(b'invalid'))
    assert not report['can_import']
    assert SECRET not in str(report)
    assert report['failure']['code'] == 'INPUT_INVALID'


def test_diagnostic_log_rotation_is_bounded(tmp_path):
    from portfolio_app.research_diagnostics import diagnostic_handler
    handler = diagnostic_handler(tmp_path / 'diagnostics.jsonl')
    handler.maxBytes = 256
    try:
        for _ in range(20):
            record = logging.LogRecord('test', logging.WARNING, SECRET, 1,
                dict(error_id='a' * 32, code='TASK_FAILED', operation='research'), (), None)
            handler.handle(record)
        handler.flush()
        files = list(tmp_path.iterdir())
        assert len(files) == 3
        assert all(SECRET not in path.read_text(encoding='utf8') for path in files)
    finally:
        handler.close()


def test_experiment_save_failure_keeps_download_and_hides_raw_error(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import portfolio_app.experiment_view as view
    monkeypatch.setattr(view, 'build_experiment', lambda *a, **k: (_ for _ in ()).throw(PermissionError(SECRET)))
    app = AppTest.from_string('''
import streamlit as st
import pandas as pd
from pathlib import Path
from portfolio_app.experiment_view import render_experiments
render_experiments(pd.DataFrame(), {'strategy_key':'trend', 'mode':'single', 'symbols':['demo']}, Path(st.session_state['root']))
''')
    app.session_state['root'] = str(tmp_path)
    app.session_state['last_experiment_bytes'] = b'previous-success'
    app.run()
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state['last_experiment_bytes'] == b'previous-success'
    assert app.get('download_button')
    text = '\n'.join(item.value for kind in ('error', 'caption', 'warning') for item in app.get(kind))
    assert SECRET not in text


def test_local_boundary_hides_unexpected_error_and_leaves_navigation(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import portfolio_app.factor_research_view as view
    monkeypatch.setenv('PORTFOLIO_MODE', 'local')
    monkeypatch.setattr(view, 'render_factor_research', lambda *a, **k: (_ for _ in ()).throw(RuntimeError(SECRET)))
    app = AppTest.from_file(str(Path('portfolio_app/local_app.py').resolve()), default_timeout=30)
    app.query_params.update(workspace='factors', context_workspace='watch', dataset_id='seeded_demo',
                            as_of='2026-02-27', bar_period='1d', context_id='ctx-9b361f40afb37886', symbol='600000.SH')
    app.run()
    assert not app.exception
    assert app.sidebar.radio(key='workspace_route_selector')
    text = '\n'.join(item.value for kind in ('error', 'caption', 'info') for item in app.get(kind))
    assert SECRET not in text and '诊断编号' in text
