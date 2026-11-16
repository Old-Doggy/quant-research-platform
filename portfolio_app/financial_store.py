"""Append-only financial observations backed by immutable raw provider batches."""
from contextlib import contextmanager
from datetime import datetime
import sqlite3
from pathlib import Path
import pandas as pd

from .snapshot_contracts import identity_hash
from .update_store import UpdateStore
from .providers.tushare_financial import FINANCIAL_PROFILES


class FinancialStore:
    def __init__(self,root):
        self.root=Path(root)
        self.updates=UpdateStore(root)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS financial_batches (artifact TEXT PRIMARY KEY, endpoint TEXT, symbol TEXT, fetched_at TEXT)')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.root/'financial.sqlite3',timeout=10)
        try:
            with db: yield db
        finally:
            db.close()

    def ingest(self,batch):
        meta=batch.metadata
        provider=meta.get('provider')
        from .providers.sina_financial import FIELDS
        profiles=FINANCIAL_PROFILES if provider=='tushare' else FIELDS if provider=='sina' else {}
        if meta.get('endpoint') not in profiles:
            raise ValueError('不是已识别财务来源批次')
        instant=datetime.fromisoformat(meta['fetched_at'])
        if instant.tzinfo is None:
            raise ValueError('财务观察时间缺少时区')
        if not batch.frame.empty:
            needed={'symbol','endpoint','period','ann_date','f_ann_date','report_type','update_flag','fetched_at','report_version'}
            if not needed<=set(batch.frame):
                raise ValueError('财务版本字段不完整')
            for row in batch.frame.to_dict('records'):
                if row['symbol']!=meta['symbol'] or row['endpoint']!=meta['endpoint'] or row['fetched_at']!=meta['fetched_at']:
                    raise ValueError('财务行与批次范围不符')
                values={k:(None if pd.isna(v) else v) for k,v in row.items() if k not in {'fetched_at','report_version'}}
                if row['report_version']!='financial-'+identity_hash(values):
                    raise ValueError('财务版本身份不符')
        artifact=self.updates.save_artifact(batch)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO financial_batches VALUES (?,?,?,?)',
                (artifact,meta['endpoint'],meta['symbol'],meta['fetched_at']))
        return artifact

    def observations(self, *, endpoint, symbol, provider='tushare'):
        from .providers.sina_financial import FIELDS
        profiles=FINANCIAL_PROFILES if provider=='tushare' else FIELDS if provider=='sina' else {}
        if endpoint not in profiles:
            raise ValueError('未知财务数据集')
        with self.connect() as db:
            refs=db.execute('SELECT artifact,fetched_at FROM financial_batches WHERE endpoint=? AND symbol=? ORDER BY fetched_at,artifact',
                (endpoint,symbol)).fetchall()
        rows=[]
        for artifact, fetched_at in refs:
            batch=self.updates.read_artifact(artifact)
            if batch.metadata.get('endpoint')!=endpoint or batch.metadata.get('symbol')!=symbol or batch.metadata.get('fetched_at')!=fetched_at:
                raise ValueError('财务索引与原始批次不一致')
            if batch.metadata.get('provider')!=provider:
                continue
            rows.extend({**{k:(None if pd.isna(v) else v) for k,v in r.items()},'artifact_id':artifact}
                for r in batch.frame.to_dict('records'))
        return rows
