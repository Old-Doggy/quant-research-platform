"""Immutable CB observations indexed separately from executable research snapshots."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from .update_store import UpdateStore


class ConvertibleStore:
    def __init__(self,root):
        self.root=Path(root);self.updates=UpdateStore(root)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cb_batches (artifact TEXT PRIMARY KEY,symbol TEXT,endpoint TEXT,fetched_at TEXT)')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.root/'convertible.sqlite3',timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def validate_batch(self,batch):
        meta=batch.metadata
        if meta.get('provider')!='sina' or meta.get('endpoint') not in {'cb_raw_daily','cb_reference'}:
            raise ValueError('不是可转债观察批次')
        if not batch.frame.empty and not batch.frame.symbol.eq(meta['symbol']).all():
            raise ValueError('可转债证券与批次不符')
    def index_existing(self,artifact):
        batch=self.updates.read_artifact(artifact)
        self.validate_batch(batch)
        meta=batch.metadata
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO cb_batches VALUES (?,?,?,?)',
                (artifact,meta['symbol'],meta['endpoint'],meta['fetched_at']))
        return artifact

    def ingest(self,batch):
        self.validate_batch(batch)
        return self.index_existing(self.updates.save_artifact(batch))

    def records(self):
        with self.connect() as db:
            rows=db.execute('SELECT artifact,symbol,endpoint,fetched_at FROM cb_batches ORDER BY fetched_at DESC,artifact').fetchall()
        return [dict(artifact_id=a,symbol=s,endpoint=e,fetched_at=t) for a,s,e,t in rows]

    def load(self,artifact):
        batch=self.updates.read_artifact(artifact)
        with self.connect() as db:
            row=db.execute('SELECT symbol,endpoint,fetched_at FROM cb_batches WHERE artifact=?',(artifact,)).fetchone()
        if row!=tuple(batch.metadata.get(k) for k in ['symbol','endpoint','fetched_at']):
            raise ValueError('可转债索引与批次不一致')
        return batch
