import pandas as pd
import pytest

from portfolio_app.providers.base import ProviderBatch, ProviderError


def shard(session):
    return dict(session=session)


def batch(value=10.):
    frame = pd.DataFrame(dict(ts_code=['600000.SH'], trade_date=['20250102'], close=[value]))
    return ProviderBatch(frame, frame.copy(), dict(provider='test', endpoint='daily', batch_id='test-1'), 'complete')


def create(store, *, mode='incremental'):
    return store.create(provider='test', dataset='daily', scope_hash='scope-v1', adapter_version='1.0',
        mode=mode, shards=[shard('2025-01-02'), shard('2025-01-03')])


def test_restart_retries_only_unfinished_shards_and_retains_failure_history(tmp_path):
    from portfolio_app.update_store import UpdateStore
    from portfolio_app.update_jobs import run_update
    store = UpdateStore(tmp_path)
    job = create(store)
    calls = []
    def fetch(part):
        calls.append(part['session'])
        if part['session'] == '2025-01-03':
            raise ProviderError('rate_limited', 'limit', retryable=True)
        return batch()
    first = run_update(store, job, fetch, now=100)
    assert first['status'] == 'partial'
    assert first['counts'] == dict(succeeded=1, retry_wait=1)
    reopened = UpdateStore(tmp_path)
    assert create(reopened) == job
    assert run_update(reopened, job, lambda p: calls.append(p['session']) or batch(), now=101)['status'] == 'partial'
    result = run_update(reopened, job, lambda p: calls.append(p['session']) or batch(), now=200)
    assert result['status'] == 'succeeded'
    assert calls == ['2025-01-02','2025-01-03','2025-01-03']
    assert [r['status'] for r in reopened.history(job)] == ['succeeded','retry_wait','succeeded']
    assert reopened.history(job)[1]['error_code'] == 'rate_limited'


def test_overlapping_worker_is_rejected_and_interrupted_shard_is_recovered(tmp_path):
    from portfolio_app.update_store import UpdateStore
    from portfolio_app.update_jobs import run_update, UpdateBusy
    store = UpdateStore(tmp_path)
    job = create(store)
    with store.lock(job):
        with pytest.raises(UpdateBusy):
            run_update(UpdateStore(tmp_path), job, lambda p: batch())
    def crash(part):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run_update(store, job, crash)
    result = run_update(UpdateStore(tmp_path), job, lambda p: batch())
    assert result['status'] == 'succeeded'
    assert any(r['error_code'] == 'interrupted' for r in store.history(job))


def test_partial_data_is_retained_as_review_and_never_published_as_success(tmp_path):
    from portfolio_app.update_store import UpdateStore
    from portfolio_app.update_jobs import run_update
    store = UpdateStore(tmp_path)
    job = create(store)
    partial = ProviderBatch(batch().frame, batch().raw, dict(missing_symbols=['000001.SZ']), 'partial')
    result = run_update(store, job, lambda p: partial)
    assert result['counts'] == dict(needs_review=2)
    assert result['status'] == 'partial'
    assert all(store.read_artifact(r['artifact_id']).completeness == 'partial' for r in store.shards(job))


def test_corrupt_completed_artifact_is_detected_before_resuming(tmp_path):
    from portfolio_app.update_store import UpdateStore
    from portfolio_app.update_jobs import run_update
    store = UpdateStore(tmp_path)
    job = create(store)
    run_update(store, job, lambda p: batch())
    artifact = store.shards(job)[0]['artifact_id']
    (tmp_path / 'batches' / artifact / 'raw.parquet').write_bytes(b'bad')
    calls = []
    result = run_update(store, job, lambda p: calls.append(p) or batch())
    assert result['status'] == 'partial'
    # Both shards referenced identical immutable bytes: both must be invalidated.
    assert result['counts'] == dict(needs_review=2)
    assert not calls


def test_request_identity_includes_revision_mode_and_scope_and_rejects_secret_params(tmp_path):
    from portfolio_app.update_store import UpdateStore
    store = UpdateStore(tmp_path)
    assert create(store) != create(store, mode='revision_check')
    with pytest.raises(ValueError):
        store.create(provider='test', dataset='daily', scope_hash='s', adapter_version='1',
            mode='incremental', shards=[dict(token='secret')])


def test_explicit_retry_retains_history_and_maximum_attempts_are_bounded(tmp_path):
    from portfolio_app.update_store import UpdateStore
    from portfolio_app.update_jobs import run_update
    store = UpdateStore(tmp_path)
    job = create(store)
    def offline(part):
        raise ProviderError('network_error', 'secret URL', retryable=True)
    assert run_update(store, job, offline, now=100, max_attempts=1)['counts'] == dict(failed=2)
    store.retry_failed(job)
    assert run_update(store, job, lambda p: batch(), now=101)['status'] == 'succeeded'
    assert len(store.history(job)) == 4
    assert all(row['error_code'] != 'secret URL' for row in store.history(job))


def test_batch_metadata_and_attrs_round_trip_without_mutating_source(tmp_path):
    from portfolio_app.update_store import UpdateStore
    store = UpdateStore(tmp_path)
    original = batch()
    original.frame.attrs['field_units'] = dict(close='CNY_per_share')
    saved = store.save_artifact(original)
    restored = store.read_artifact(saved)
    assert restored.frame.attrs == original.frame.attrs
    assert restored.raw.equals(original.raw)
    assert restored.metadata == original.metadata


def test_os_lock_blocks_another_process_and_releases_after_process_exit(tmp_path):
    import subprocess
    import sys
    from portfolio_app.update_store import UpdateStore
    store = UpdateStore(tmp_path)
    job = create(store)
    source = '''
import sys
from portfolio_app.update_store import UpdateStore, UpdateBusy
try:
    with UpdateStore(sys.argv[1]).lock(sys.argv[2]):
        pass
except UpdateBusy:
    raise SystemExit(7)
'''
    command = [sys.executable, '-c', source, str(tmp_path), job]
    with store.lock(job):
        assert subprocess.run(command, capture_output=True, timeout=15).returncode == 7
    assert subprocess.run(command, capture_output=True, timeout=15).returncode == 0


def test_cancel_leaves_unstarted_shards_pending_and_does_not_discard_completed(tmp_path):
    from portfolio_app.update_store import UpdateStore
    from portfolio_app.update_jobs import run_update
    store = UpdateStore(tmp_path)
    job = create(store)
    calls = []
    result = run_update(store, job, lambda p: calls.append(p) or batch(), cancel=lambda: bool(calls))
    assert result['counts'] == dict(succeeded=1, pending=1)
    assert run_update(store, job, lambda p: calls.append(p) or batch())['status'] == 'succeeded'
    assert len(calls) == 2
