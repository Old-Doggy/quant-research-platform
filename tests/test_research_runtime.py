from threading import Event
import time

import pandas as pd
import pytest

from portfolio_app.research_result_cache import ResearchResultCache, build_research_cache_key
from portfolio_app.research_runtime import ResearchRunner, TaskJournal


def key(name='a'):
    return build_research_cache_key(dataset_id='demo', data_version=name,
                                   processing={}, engine_id='test.v1')


def finish(runner):
    deadline = time.monotonic() + 5
    while runner.snapshot()['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.01)
    return runner.snapshot()


def test_bounded_cache_owns_nested_values_and_evicts_lru():
    cache = ResearchResultCache(max_entries=2, max_bytes=100000)
    result = cache.submit(key(), lambda: {'nested': {'values': [1]}, 'frame': pd.DataFrame({'x': [1]})})
    result.value['nested']['values'][0] = 99
    result.value['frame'].loc[0, 'x'] = 99
    assert cache.lookup(key())['nested']['values'] == [1]
    assert cache.lookup(key())['frame'].x.tolist() == [1]
    cache.submit(key('b'), lambda: {'x': 2})
    cache.lookup(key())
    cache.submit(key('c'), lambda: {'x': 3})
    assert cache.lookup(key('b')) is None
    assert cache.stats().entries == 2 and cache.stats().evictions == 1
    tiny = ResearchResultCache(max_entries=2, max_bytes=100)
    tiny.submit(key(), lambda: {'huge': 'x' * 1000})
    assert tiny.lookup(key()) is None


def test_background_cancel_never_commits_even_if_compute_ignores_request(tmp_path):
    entered, release = Event(), Event()
    runner = ResearchRunner(journal=TaskJournal(tmp_path / 'tasks.sqlite'))
    def compute(token):
        token.report(.2, 'features')
        entered.set()
        release.wait(3)
        return {'answer': 42}
    runner.start(key(), compute)
    assert entered.wait(2)
    assert runner.snapshot()['progress'] == .2
    with pytest.raises(RuntimeError, match='running'):
        runner.start(key('b'), compute)
    runner.cancel()
    release.set()
    assert finish(runner)['status'] == 'cancelled'
    assert runner.cache.lookup(key()) is None
    assert runner.result() is None
    assert runner.journal.records()[0]['status'] == 'cancelled'


def test_repeat_hit_retains_previous_success_after_failure_and_cancel(tmp_path):
    runner = ResearchRunner(journal=TaskJournal(tmp_path / 'tasks.sqlite'))
    calls = []
    runner.start(key(), lambda t: calls.append(1) or {'answer': [42]})
    assert finish(runner)['status'] == 'succeeded'
    runner.start(key(), lambda t: calls.append(2) or {})
    assert finish(runner)['cache_hit'] is True
    assert calls == [1]
    runner.start(key('bad'), lambda t: (_ for _ in ()).throw(ValueError('bad input')))
    assert finish(runner)['status'] == 'failed'
    assert runner.last_success == {'answer': [42]}
    assert runner.journal.records()[0]['status'] == 'failed'


def test_journal_recovers_dead_worker_as_interrupted_not_success(tmp_path):
    journal = TaskJournal(tmp_path / 'tasks.sqlite')
    journal.begin('dead', key().key_id, pid=2147483647)
    journal.recover()
    assert journal.records()[0]['status'] == 'interrupted'
    assert journal.records()[0]['result_available'] is False
    assert 'answer' not in str(journal.records())


def test_journal_connections_close_after_success_and_rollback(tmp_path):
    import sqlite3
    path=tmp_path/'tasks.sqlite'
    journal=TaskJournal(path)
    journal.begin('one','key')
    with journal._connect() as closed:
        assert closed.execute('SELECT count(*) FROM tasks').fetchone()==(1,)
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        closed.execute('SELECT 1')
    with pytest.raises(RuntimeError):
        with journal._connect() as rolled_back:
            rolled_back.execute("DELETE FROM tasks")
            raise RuntimeError('rollback')
    assert len(journal.records())==1
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        rolled_back.execute('SELECT 1')
    moved=path.with_name('moved.sqlite')
    path.rename(moved)
    moved.unlink()


def test_journal_write_failure_does_not_commit_or_leave_running(tmp_path):
    journal = TaskJournal(tmp_path / 'tasks.sqlite')
    def fail_write(*args):
        raise OSError('disk unavailable')
    journal.finish = fail_write
    runner = ResearchRunner(journal=journal)
    runner.start(key(), lambda token: {'answer': 42})
    assert finish(runner)['status'] == 'failed'
    assert runner.result() is None
    assert runner.last_success is None
    assert runner.cache.lookup(key()) is None


def test_real_process_exit_recovers_only_metadata(tmp_path):
    import subprocess
    import sys
    path = tmp_path / 'tasks.sqlite'
    script = ('from portfolio_app.research_runtime import TaskJournal; '
              'import sys; TaskJournal(sys.argv[1]).begin("killed", "demo"); '
              'print("ready", flush=True); sys.stdin.read()')
    child = subprocess.Popen([sys.executable, '-c', script, str(path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        child.terminate()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    records = TaskJournal(path).records()
    assert len(records) == 1
    assert records[0]['status'] == 'interrupted'
    assert records[0]['result_available'] is False


def test_invalid_computation_never_marks_journal_success(tmp_path):
    runner = ResearchRunner(journal=TaskJournal(tmp_path / 'tasks.sqlite'))
    runner.start(key(), lambda token: object())
    assert finish(runner)['status'] == 'failed'
    assert runner.journal.records()[0]['status'] == 'failed'
    assert runner.cache.stats().entries == 0
