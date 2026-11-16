import pytest


def test_search_filters_metadata_without_loading_payloads():
    from portfolio_app.experiment_catalog import filter_records
    rows = [dict(task_id='alpha', workspace='portfolio', created_at='2025-01-02T00:00:00+00:00'),
        dict(task_id='beta', workspace='factors', created_at='2025-01-03T00:00:00+00:00')]
    assert [r['task_id'] for r in filter_records(rows, query='组合')] == ['alpha']
    assert filter_records(rows, query='BETA', workspace='factors') == [rows[1]]
    assert filter_records(rows, query='missing') == []
    assert filter_records(rows, workspace='portfolio') == [rows[0]]


def test_return_scatter_excludes_ic_and_corrupt_curves_and_keeps_negative_returns():
    from portfolio_app.experiment_catalog import experiment_points
    import pandas as pd
    projections = dict(loss=dict(curve=pd.DataFrame(dict(trade_date=['2025-01-02'],nav=[.8],drawdown=[-.2])),
        metrics={'sharpe':-1}), ic=dict(curve=None,metrics={}),
        invalid=dict(curve=pd.DataFrame(dict(trade_date=['2025-01-02'],nav=[-1.],drawdown=[-.2])),metrics={}))
    frame, omitted = experiment_points(projections)
    assert frame.task_id.tolist() == ['loss']
    assert frame.iloc[0].total_return == pytest.approx(-.2)
    assert frame.iloc[0].max_drawdown == pytest.approx(-.2)
    assert set(omitted) == {'ic','invalid'}


def test_failure_view_works_without_successful_results_and_never_echoes_raw_exception(tmp_path,monkeypatch):
    from portfolio_app.research_runtime import TaskJournal
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('PORTFOLIO_STATE_DIR', str(tmp_path))
    journal = TaskJournal(tmp_path/'workbench_tasks'/'tasks.sqlite')
    journal.begin('failed-one','key-one')
    journal.finish('failed-one','failed',failure=dict(error_id='a'*32,code='INPUT_INVALID',operation='research',
        exception='secret-token-and-path'))
    app=AppTest.from_string('from portfolio_app.result_history_view import render_result_history\nrender_result_history(public_mode=False)').run()
    assert not app.exception
    app.segmented_control(key='result_history_mode').set_value('任务状态').run()
    assert not app.exception and app.dataframe
    table=app.dataframe[0].value
    assert 'failed-one' in table.to_string()
    assert 'secret-token-and-path' not in table.to_string()


def test_scatter_and_search_are_lazy_and_corrupt_run_does_not_hide_valid_run(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_result_history import seed
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    store=seed(tmp_path)
    from portfolio_app.research_result_cache import build_research_cache_key
    store.save('broken-run', build_research_cache_key(dataset_id='portfolio', data_version='broken',
        processing={}, engine_id='test'), {'metrics':{}})
    (store.root/'runs'/'broken-run'/'manifest.json').write_text('{}',encoding='utf8')
    app=AppTest.from_string('from portfolio_app.result_history_view import render_result_history\nrender_result_history(public_mode=False)').run()
    app.text_input(key='result_history_search').set_value('does-not-exist').run()
    assert not app.exception and not app.get('plotly_chart')
    app.text_input(key='result_history_search').set_value('fixture').run()
    app.segmented_control(key='result_history_mode').set_value('收益与回撤').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    app.text_input(key='result_history_search').set_value('').run()
    assert not app.exception and len(app.get('plotly_chart'))==1
    assert any('无法读取' in caption.value for caption in app.caption)
