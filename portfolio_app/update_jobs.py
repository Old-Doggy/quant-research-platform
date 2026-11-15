"""Bounded shard execution. A successful download never implies snapshot publication."""
from collections import Counter
import time

from .providers.base import ProviderError
from .update_store import UpdateBusy


def run_update(store, job, fetch, *, now=None, max_attempts=4, cancel=None):
    if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
        raise ValueError('更新重试次数必须为1至10')
    clock = (lambda: float(now)) if now is not None else time.time
    with store.lock(job):
        for part in store.shards(job):
            key = part['id']
            if part['status'] == 'running':
                store.record(job, key, 'pending', now=clock(), error_code='interrupted')
            elif part['status'] == 'succeeded':
                try:
                    store.read_artifact(part['artifact_id'])
                except (ValueError, OSError, KeyError):
                    store.record(job, key, 'needs_review', now=clock(), error_code='artifact_corrupt', artifact_id=part['artifact_id'])
                continue
            elif part['status'] not in {'pending','retry_wait'}:
                continue
            if part['next_retry'] > clock():
                continue
            if cancel and cancel():
                break
            store.record(job, key, 'running', now=clock(), start=True)
            try:
                batch = fetch(dict(part['payload']))
                artifact = store.save_artifact(batch)
            except ProviderError as exc:
                retry = exc.retryable and part['attempts'] + 1 < max_attempts
                store.record(job, key, 'retry_wait' if retry else 'failed', now=clock(),
                    error_code=exc.code, next_retry=clock() + min(3600, 30 * 2 ** min(part['attempts'], 7)) if retry else 0)
            except Exception:
                # Raw exception text can contain request credentials or private paths.
                store.record(job, key, 'failed', now=clock(), error_code='local_or_contract_error')
            else:
                store.record(job, key, 'succeeded' if batch.completeness == 'complete' else 'needs_review',
                    now=clock(), artifact_id=artifact)
        counts = dict(Counter(p['status'] for p in store.shards(job)))
        return dict(job_id=job, status='succeeded' if set(counts) == {'succeeded'} else 'partial', counts=counts)
