"""Local shard journal and immutable, checksummed provider batch artifacts."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

import pandas as pd

from .dataset_registry import _atomic_write_json
from .providers.base import ProviderBatch
from .snapshot_contracts import identity_hash, _plain


class UpdateBusy(ValueError):
    pass


def _safe_payload(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or any(word in key.lower() for word in ('token','secret','password','authorization','api_key')):
                raise ValueError('更新清单不能包含凭据')
            _safe_payload(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _safe_payload(item)


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class UpdateStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS shards (job TEXT, id TEXT, payload TEXT, status TEXT,
                    attempts INTEGER DEFAULT 0, next_retry REAL DEFAULT 0, artifact_id TEXT,
                    PRIMARY KEY(job,id));
                CREATE TABLE IF NOT EXISTS attempts (sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job TEXT, shard TEXT, attempt INTEGER, status TEXT, error_code TEXT,
                    recorded_at REAL, artifact_id TEXT);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'updates.sqlite3', timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, *, provider, dataset, scope_hash, adapter_version, mode, shards):
        if mode not in {'incremental','historical','revision_check'}:
            raise ValueError('未知更新模式')
        for value in (provider, dataset, scope_hash, adapter_version):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', value):
                raise ValueError('更新身份无效')
        shards = list(shards)
        if not shards or any(not isinstance(s, dict) or not s for s in shards):
            raise ValueError('更新需要非空分片')
        _safe_payload(shards)
        ids = [identity_hash(s) for s in shards]
        if len(ids) != len(set(ids)):
            raise ValueError('更新分片重复')
        request = dict(provider=provider, dataset=dataset, scope_hash=scope_hash,
            adapter_version=adapter_version, mode=mode, shards=shards)
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, allow_nan=False)
        job = 'update-' + identity_hash(request)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?)', (job, encoded))
            db.executemany('INSERT OR IGNORE INTO shards (job,id,payload,status) VALUES (?,?,?,?)',
                [(job, key, json.dumps(s, ensure_ascii=False, sort_keys=True), 'pending') for key, s in zip(ids, shards)])
        return job

    @contextmanager
    def lock(self, job):
        if not re.fullmatch(r'update-[a-f0-9]{64}', job):
            raise ValueError('更新任务身份无效')
        with self.connect() as db:
            if not db.execute('SELECT id FROM jobs WHERE id=?', (job,)).fetchone():
                raise ValueError('更新任务不存在')
        directory = self.root / 'locks'
        directory.mkdir(exist_ok=True)
        with (directory / (job + '.lock')).open('a+b') as handle:
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            acquired = False
            try:
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError as exc:
                    raise UpdateBusy('此更新任务正在运行') from exc
                yield
            finally:
                if acquired:
                    handle.seek(0)
                    if os.name == 'nt':
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)

    def shards(self, job):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM shards WHERE job=? ORDER BY rowid', (job,)).fetchall()
        return [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]

    def request(self, job):
        with self.connect() as db:
            row = db.execute('SELECT request FROM jobs WHERE id=?', (job,)).fetchone()
        if row is None:
            raise ValueError('更新任务不存在')
        request = json.loads(row[0])
        if 'update-' + identity_hash(request) != job:
            raise ValueError('更新任务清单校验失败')
        return request

    def history(self, job):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM attempts WHERE job=? ORDER BY sequence', (job,))]

    def retry_failed(self, job):
        with self.lock(job), self.connect() as db:
            # Completed shards and their artifacts stay untouched; attempts are historical.
            db.execute("UPDATE shards SET status='pending', next_retry=0 WHERE job=? AND status IN ('failed','needs_review')", (job,))

    def record(self, job, shard, status, *, now, error_code=None, artifact_id=None, next_retry=0, start=False):
        with self.connect() as db:
            db.execute('UPDATE shards SET status=?, attempts=attempts+?, next_retry=?, artifact_id=? WHERE job=? AND id=?',
                (status, int(start), next_retry, artifact_id, job, shard))
            attempt = db.execute('SELECT attempts FROM shards WHERE job=? AND id=?', (job, shard)).fetchone()[0]
            if not start:
                db.execute('INSERT INTO attempts (job,shard,attempt,status,error_code,recorded_at,artifact_id) VALUES (?,?,?,?,?,?,?)',
                    (job, shard, attempt, status, error_code, now, artifact_id))

    def save_artifact(self, batch):
        if not isinstance(batch, ProviderBatch) or batch.completeness not in {'complete','partial','unverified'}:
            raise ValueError('更新批次格式或完整度无效')
        metadata = _plain(batch.metadata)
        attrs = _plain(batch.frame.attrs)
        _safe_payload(metadata)
        _safe_payload(attrs)
        directory = self.root / 'batches'
        directory.mkdir(exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.batch-', dir=directory))
        try:
            for name, frame in [('raw', batch.raw), ('normalized', batch.frame)]:
                data = frame.copy(deep=True)
                data.attrs = {}
                data.to_parquet(temporary / (name + '.parquet'), index=False)
            payload = dict(schema_version='provider-batch.v1', metadata=metadata, frame_attrs=attrs,
                completeness=batch.completeness, files={name: _digest(temporary / name)
                    for name in ('raw.parquet', 'normalized.parquet')})
            artifact = 'batch-' + identity_hash(payload)
            _atomic_write_json(temporary / 'manifest.json', payload)
            target = directory / artifact
            if target.exists():
                self.read_artifact(artifact)
            else:
                try:
                    os.rename(temporary, target)
                except OSError:
                    if not target.exists():
                        raise
                    self.read_artifact(artifact)
            return artifact
        finally:
            # Only the generated staging directory can be removed, never a published batch.
            if temporary.exists() and temporary.resolve().parent == directory.resolve():
                shutil.rmtree(temporary)

    def read_artifact(self, artifact):
        if not isinstance(artifact, str) or not re.fullmatch(r'batch-[a-f0-9]{64}', artifact):
            raise ValueError('更新批次身份无效')
        directory = self.root / 'batches' / artifact
        payload = json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
        if ('batch-' + identity_hash(payload) != artifact or payload['schema_version'] != 'provider-batch.v1'
                or set(payload['files']) != {'raw.parquet', 'normalized.parquet'}
                or any(_digest(directory / name) != digest for name, digest in payload['files'].items())):
            raise ValueError('更新批次内容校验失败')
        frame, raw = pd.read_parquet(directory / 'normalized.parquet'), pd.read_parquet(directory / 'raw.parquet')
        frame.attrs = payload['frame_attrs']
        return ProviderBatch(frame, raw, payload['metadata'], payload['completeness'])
