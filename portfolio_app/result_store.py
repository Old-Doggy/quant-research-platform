"""Private durable result packages; SQLite index only references published bundles."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from .dataset_registry import _atomic_write_json
from .process_lock import process_lock
from .result_codec import ResultCodec
from .research_result_cache import build_research_cache_key
from .snapshot_contracts import identity_hash


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value):
        raise ValueError('结果身份无效')
    return value


class ResultStore:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / 'runs').mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS results (task_id TEXT PRIMARY KEY, key_id TEXT, workspace TEXT, created_at TEXT, checksum TEXT)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.root / 'results.sqlite3', timeout=10)
        try:
            with db: yield db
        finally:
            db.close()

    def _publish(self, temporary, target):
        os.replace(temporary, target)

    def save(self, task_id, key, value):
        _identifier(task_id)
        if self._key(asdict(key)) != key:
            raise ValueError('研究配置身份校验失败')
        if not isinstance(value, dict):
            raise TypeError('研究结果需要字典结构')
        with process_lock(self.root / 'locks' / (task_id + '.lock'), wait=True):
            # All partial files live outside runs; no index ever points into staging.
            with tempfile.TemporaryDirectory(prefix='.result-', dir=self.root) as temporary:
                temporary = Path(temporary)
                codec = ResultCodec(temporary)
                tree = codec.encode(value)
                content = dict(schema='research-result.v1', disclosure='private_local',
                    task_id=task_id, key=asdict(key), files=codec.files, value=tree)
                checksum = identity_hash(content)
                target = self.root / 'runs' / task_id
                if target.exists():
                    previous = self._manifest(task_id, indexed=False)
                    if previous['checksum'] != checksum:
                        raise ValueError('同一任务已有不同结果，不能覆盖')
                    # Validate existing arrays before recovering an unindexed committed package.
                    self._decode(previous, target)
                    manifest = previous
                else:
                    manifest = {**content, 'checksum': checksum, 'created_at': datetime.now(timezone.utc).isoformat()}
                    _atomic_write_json(temporary / 'manifest.json', manifest)
                    self._publish(temporary, target)
                self._index(task_id, key, manifest)
        return task_id

    @staticmethod
    def _key(payload):
        key = build_research_cache_key(**{k: v for k, v in payload.items() if k != 'key_id'})
        if key.key_id != payload['key_id']:
            raise ValueError('研究配置身份校验失败')
        return key

    def _index(self, task_id, key, manifest):
        with self._connect() as db:
            db.execute('INSERT OR IGNORE INTO results VALUES (?,?,?,?,?)',
                (task_id, key.key_id, key.dataset_id, manifest['created_at'], manifest['checksum']))

    def _manifest(self, task_id, *, indexed=True):
        _identifier(task_id)
        with self._connect() as db:
            row = db.execute('SELECT checksum,key_id,workspace FROM results WHERE task_id=?', (task_id,)).fetchone()
        if indexed and row is None: raise FileNotFoundError('研究结果未发布')
        manifest = json.loads((self.root / 'runs' / task_id / 'manifest.json').read_text(encoding='utf8'))
        content = {k: v for k, v in manifest.items() if k not in ('checksum', 'created_at')}
        if (manifest.get('schema') != 'research-result.v1' or manifest.get('disclosure') != 'private_local'
                or manifest.get('task_id') != task_id or identity_hash(content) != manifest.get('checksum')):
            raise ValueError('研究结果清单校验失败')
        if row and row != (manifest['checksum'], manifest['key']['key_id'], manifest['key']['dataset_id']):
            raise ValueError('研究结果索引校验失败')
        self._key(manifest['key'])
        return manifest

    def _decode(self, manifest, directory):
        codec = ResultCodec(directory)
        codec.files = manifest['files']
        return codec.decode(manifest['value'])

    def load(self, task_id, *, expected_key=None):
        manifest = self._manifest(task_id)
        if expected_key is not None and manifest['key'] != asdict(expected_key):
            raise ValueError('研究配置或计算版本与保存结果不符')
        return self._decode(manifest, self.root / 'runs' / task_id)

    def discard(self, task_id):
        """Withdraw index after task completion fails; retain immutable evidence."""
        _identifier(task_id)
        with self._connect() as db:
            db.execute('DELETE FROM results WHERE task_id=?', (task_id,))

    def latest(self, key):
        with self._connect() as db:
            row = db.execute('SELECT task_id FROM results WHERE key_id=? ORDER BY created_at DESC LIMIT 1',
                (key.key_id,)).fetchone()
        return self.load(row[0], expected_key=key) if row else None

    def records(self, *, workspace=None, limit=50):
        with self._connect() as db:
            rows = db.execute('SELECT task_id,key_id,workspace,created_at FROM results '
                + ('WHERE workspace=? ' if workspace is not None else '')
                + 'ORDER BY created_at DESC LIMIT ?',
                (*((workspace,) if workspace is not None else ()), min(100, max(1, int(limit))))).fetchall()
        return [dict(task_id=a, key_id=b, workspace=c, created_at=d) for a, b, c, d in rows]
