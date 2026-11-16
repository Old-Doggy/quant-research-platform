"""Immutable observed ETF batches and descriptive raw-price comparisons."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from .update_store import UpdateStore


class ETFStore:
    def __init__(self,root):
        self.root=Path(root)
        self.updates=UpdateStore(root)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS etf_batches (artifact TEXT PRIMARY KEY,symbol TEXT,fetched_at TEXT)')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.root/'etf.sqlite3',timeout=10)
        try:
            with db: yield db
        finally: db.close()

    def ingest(self,batch):
        meta=batch.metadata
        if meta.get('provider')!='sina' or meta.get('endpoint')!='etf_raw_daily':
            raise ValueError('不是ETF观察批次')
        if not batch.frame.empty and not batch.frame.symbol.eq(meta['symbol']).all():
            raise ValueError('ETF证券与批次不符')
        artifact=self.updates.save_artifact(batch)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO etf_batches VALUES (?,?,?)',(artifact,meta['symbol'],meta['fetched_at']))
        return artifact

    def records(self):
        with self.connect() as db:
            rows=db.execute('SELECT artifact,symbol,fetched_at FROM etf_batches ORDER BY fetched_at DESC,artifact').fetchall()
        return [dict(artifact_id=a,symbol=s,fetched_at=t) for a,s,t in rows]

    def load(self,artifact):
        batch=self.updates.read_artifact(artifact)
        with self.connect() as db:
            row=db.execute('SELECT symbol,fetched_at FROM etf_batches WHERE artifact=?',(artifact,)).fetchone()
        if row!=(batch.metadata.get('symbol'),batch.metadata.get('fetched_at')) or batch.metadata.get('endpoint')!='etf_raw_daily':
            raise ValueError('ETF索引与批次不一致')
        return batch


def compare_etf_prices(frames):
    rows=[];curves={}
    for symbol,frame in frames.items():
        data=frame.copy(deep=True).sort_values('trade_date')
        data['trade_date']=pd.to_datetime(data.trade_date,errors='raise')
        data['close']=pd.to_numeric(data.close,errors='raise')
        if (data.empty or data.trade_date.isna().any() or data.trade_date.duplicated().any()
                or not np.isfinite(data.close).all() or data.close.le(0).any()):
            raise ValueError('ETF价格日期或数值无效')
        data['price_index']=data.close/data.close.iloc[0]
        data['price_drawdown']=data.price_index/data.price_index.cummax()-1
        curves[symbol]=data
        rows.append(dict(symbol=symbol,start=data.trade_date.iloc[0].date().isoformat(),end=data.trade_date.iloc[-1].date().isoformat(),
            observed_sessions=len(data),price_return=float(data.price_index.iloc[-1]-1),
            max_price_drawdown=float(data.price_drawdown.min())))
    return dict(curves=curves,summary=pd.DataFrame(rows),basis='unadjusted_price_change_excluding_distributions')
