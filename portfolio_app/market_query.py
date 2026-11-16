"""Bounded Arrow scans pinned to a verified immutable daily snapshot."""
import time

import pandas as pd
import pyarrow.dataset as ds

from .instrument_master import _date
from .provider_normalize import source_previous_close, PREVIOUS_CLOSE_POLICY


def query_daily(store, snapshot_id, *, symbols, start, end, columns,
                max_rows=150000, max_bytes=96*1024*1024):
    _date(start)
    _date(end)
    if (type(max_rows) is not int or not 1<=max_rows<=5_000_000
            or type(max_bytes) is not int or not 1<=max_bytes<=512*1024*1024):
        raise ValueError('查询预算无效')
    symbols=sorted(set(symbols))
    columns=list(columns)
    if not symbols or not columns or len(columns)!=len(set(columns)) or start>end:
        raise ValueError('查询证券、日期或字段无效')
    manifest=store.open(snapshot_id)
    scope=manifest['range']
    if set(symbols)-set(scope['symbols']) or start<scope['start'] or end>scope['end']:
        raise ValueError('查询超出快照完整范围')
    started=time.perf_counter()
    # Check every referenced input, including the independent comparison evidence.
    for artifact in (*manifest['batch_ids'],*manifest['comparison_ids'],*manifest.get('reference_batch_ids',())):
        store.updates.verify_artifact(artifact)
    parts=[]
    rows=0
    bytes_used=0
    for artifact in manifest['batch_ids']:
        path=store.root/'batches'/artifact/'normalized.parquet'
        data=ds.dataset(path,format='parquet')
        scan_columns=[c for c in columns if c!='pre_close']
        if 'pre_close' in columns and 'source_pre_close' in data.schema.names and 'source_pre_close' not in scan_columns:
            scan_columns.append('source_pre_close')
        # Scan one key even for a legacy pre_close-only projection, preserving row counts.
        if not scan_columns:
            scan_columns=['ts_code']
        if not set(scan_columns)<=set(data.schema.names):
            raise ValueError('查询字段不在快照标准数据中')
        predicate=(ds.field('ts_code').isin(symbols)
            & (ds.field('trade_date')>=pd.Timestamp(start).to_datetime64())
            & (ds.field('trade_date')<=pd.Timestamp(end).to_datetime64()))
        for batch in data.scanner(columns=scan_columns,filter=predicate,batch_size=8192).to_batches():
            rows+=batch.num_rows
            bytes_used+=batch.nbytes
            if rows>max_rows or bytes_used>max_bytes:
                raise ValueError('查询结果超出预算，请缩小证券、日期或字段范围')
            part=batch.to_pandas()
            if 'pre_close' in columns:
                part['pre_close']=source_previous_close(part,'source_pre_close')
            part=part[columns]
            part.attrs={}
            parts.append(part)
    result=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=columns)
    sort=[c for c in ('trade_date','ts_code') if c in result]
    if sort:
        result=result.sort_values(sort).reset_index(drop=True)
    pandas_bytes=int(result.memory_usage(index=True,deep=True).sum())
    if pandas_bytes>max_bytes:
        raise ValueError('查询表格内存超出预算，请缩小范围')
    first_meta=store.updates.verify_artifact(manifest['batch_ids'][0])
    result.attrs=first_meta['frame_attrs'].copy()
    result.attrs['snapshot']=manifest['reference']
    result.attrs['research_dataset']=dict(dataset_id=manifest['dataset_id'],version=snapshot_id,
        price_basis='raw',source_kind='provider_snapshot')
    result.attrs['research_capabilities']=manifest['research_capabilities']
    result.attrs['previous_close_policy']=PREVIOUS_CLOSE_POLICY
    result.attrs['query']=dict(rows=len(result),arrow_bytes=bytes_used,pandas_bytes=pandas_bytes,
        elapsed_seconds=time.perf_counter()-started,backend='pyarrow.dataset',snapshot_id=snapshot_id)
    return result
