from threading import Event
import time

import pandas as pd

from portfolio_app.research_result_cache import build_research_cache_key
from portfolio_app.research_runtime import ResearchRunner, TaskJournal
from portfolio_app.result_store import ResultStore


def key(version='one'):
    return build_research_cache_key(dataset_id='strategy', data_version=version,
        processing={'revision': 'test'}, engine_id='session-task.v1')


def finish(runner):
    deadline = time.monotonic() + 5
    while runner.snapshot()['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.01)
    return runner.snapshot()


def test_success_persists_before_delivery_and_restart_reuses_only_exact_key(tmp_path):
    root = tmp_path / 'results'
    journal = TaskJournal(tmp_path / 'tasks.sqlite')
    runner = ResearchRunner(journal=journal, result_store=ResultStore(root))
    task = runner.start(key(), lambda token: {'frame': pd.DataFrame({'nav': [1., 1.2]})})
    assert finish(runner)['status'] == 'succeeded'
    # Never polling result() still saves it, including browser abandonment.
    assert ResultStore(root).load(task)['frame'].nav.tolist() == [1., 1.2]
    assert journal.records()[0]['status'] == 'succeeded'
    assert journal.records()[0]['result_id'] == task
    assert journal.records()[0]['result_available'] is True
    second = ResearchRunner(journal=journal, result_store=ResultStore(root))
    restored = second.restore(key())
    assert restored['frame'].nav.tolist() == [1., 1.2]
    assert second.restore(key('changed')) is None
    restored['frame'].iloc[0, 0] = 999
    assert second.restore(key())['frame'].iloc[0, 0] == 1.


def test_save_failure_does_not_commit_cache_success_or_replace_previous(tmp_path, monkeypatch):
    store = ResultStore(tmp_path / 'results')
    runner = ResearchRunner(journal=TaskJournal(tmp_path / 'tasks.sqlite'), result_store=store)
    runner.start(key(), lambda token: {'answer': 42})
    assert finish(runner)['status'] == 'succeeded'
    monkeypatch.setattr(store, 'save', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    runner.start(key('new'), lambda token: {'answer': 43})
    assert finish(runner)['status'] == 'failed'
    assert runner.last_success == {'answer': 42}
    assert runner.cache.lookup(key('new')) is None
    assert runner.result() is None
    assert runner.journal.records()[0]['status'] == 'failed'
    assert runner.journal.records()[0]['failure']['code'] == 'STORAGE_ERROR'
    assert 'disk full' not in str(runner.journal.records())
    assert len(store.records()) == 1


def test_cancelled_worker_cannot_write_any_result(tmp_path):
    entered, release = Event(), Event()
    store = ResultStore(tmp_path / 'results')
    runner = ResearchRunner(result_store=store)
    def compute(token):
        entered.set()
        release.wait(3)
        return {'answer': 99}
    runner.start(key(), compute)
    assert entered.wait(2)
    runner.cancel()
    release.set()
    assert finish(runner)['status'] == 'cancelled'
    assert store.records() == []


def test_corrupt_latest_result_never_silently_restores_older_result(tmp_path):
    store = ResultStore(tmp_path / 'results')
    runner = ResearchRunner(result_store=store)
    runner.start(key(), lambda token: {'answer': 42})
    assert finish(runner)['status'] == 'succeeded'
    latest = runner.start(key(), lambda token: {})
    assert finish(runner)['status'] == 'succeeded'
    (store.root / 'runs' / latest / 'manifest.json').write_text('{}', encoding='utf8')
    import pytest
    with pytest.raises(ValueError):
        ResearchRunner(result_store=store).restore(key())


def test_journal_failure_withdraws_saved_result_and_cache(tmp_path, monkeypatch):
    store = ResultStore(tmp_path / 'results')
    journal = TaskJournal(tmp_path / 'tasks.sqlite')
    runner = ResearchRunner(journal=journal, result_store=store)
    monkeypatch.setattr(journal, 'finish', lambda *a: (_ for _ in ()).throw(OSError('journal failed')))
    runner.start(key(), lambda token: {'answer': 42})
    assert finish(runner)['status'] == 'failed'
    assert store.records() == []
    assert runner.restore(key()) is None
    assert runner.cache.lookup(key()) is None


def test_existing_metadata_only_task_database_migrates_without_losing_history(tmp_path):
    import sqlite3
    path = tmp_path / 'tasks.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY,key_id TEXT,pid INTEGER,status TEXT,updated REAL)')
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', ('legacy', 'old', 0, 'succeeded', 1.))
    journal = TaskJournal(path)
    row = journal.records()[0]
    assert row['task_id'] == 'legacy' and row['status'] == 'succeeded'
    assert not row['result_available'] and row['result_id'] is None
