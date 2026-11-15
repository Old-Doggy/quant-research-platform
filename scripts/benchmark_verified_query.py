"""Measure the production query including all batch hashes, on synthetic inputs."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from portfolio_app.dataset_registry import _atomic_write_json
from portfolio_app.market_query import query_daily
from portfolio_app.providers.base import ProviderBatch
from portfolio_app.snapshot_contracts import identity_hash,snapshot_from_hash
from portfolio_app.snapshot_store import SnapshotStore
from benchmark_market_query import peak_memory


def prepare(root):
    store=SnapshotStore(root)
    batches={p:[] for p in ('baostock','sina')}
    dates=pd.bdate_range('2025-01-02',periods=200)
    for part in range(10):
        codes=np.array([f'{600000+i:06d}.SH' for i in range(part*500,(part+1)*500)])
        price=np.tile(np.arange(200)/100+10,500)
        frame=pd.DataFrame(dict(ts_code=np.repeat(codes,200),trade_date=np.tile(dates,500),
            open=price,high=price+.1,low=price-.1,close=price,
            volume=np.repeat(np.arange(part*500,(part+1)*500)+1000,200)))
        frame['amount']=frame.volume*frame.close
        for name in batches:
            data=frame.copy()
            data.attrs=dict(field_units=dict(price='CNY_per_share',volume='shares',amount='CNY'),
                normalization=dict(profile=name+'.sdk.raw',version='1.0'),research_dataset=dict(price_basis='raw'))
            batches[name].append(store.updates.save_artifact(ProviderBatch(data,frame.copy(),dict(provider=name,synthetic=True),'complete')))
    # Explicit synthetic fixture: no production publication or market validation claims.
    payload=dict(schema_version='daily-snapshot-store.v1',dataset_id='synthetic-query-benchmark',generation=1,
        batch_ids=batches['baostock'],comparison_ids=batches['sina'],reference_batch_ids=[],
        range=dict(start=dates[0].strftime('%Y-%m-%d'),end=dates[-1].strftime('%Y-%m-%d'),
            symbols=[f'{600000+i:06d}.SH' for i in range(5000)]),
        research_capabilities=dict(price_browsing=True,corporate_action_backtest=False),
        validation_scope='synthetic_query_fixture_only',synthetic=True)
    reference=snapshot_from_hash(identity_hash(payload),dataset_id=payload['dataset_id'],generation=1,
        price_basis='raw',completeness='complete')
    manifest={**payload,'snapshot_id':reference.snapshot_id,'reference':asdict(reference)}
    _atomic_write_json(store.directory/(reference.snapshot_id+'.json'),manifest)
    return reference.snapshot_id


def measure(root,snapshot,count):
    store=SnapshotStore(root)
    codes=[f'{600000+i:06d}.SH' for i in range(count)]
    records=[]
    expected_dates=pd.bdate_range('2025-01-02',periods=200)
    indexes=np.flatnonzero((expected_dates>=pd.Timestamp('2025-03-03'))&(expected_dates<=pd.Timestamp('2025-04-30')))
    for label in ('first_process_read','repeat_read'):
        before=time.perf_counter()
        result=query_daily(store,snapshot,symbols=codes,start='2025-03-03',end='2025-04-30',
            columns=['ts_code','trade_date','close','volume'],max_rows=250000)
        elapsed=time.perf_counter()-before
        assert len(result)==count*len(indexes)
        assert np.allclose(result.close.to_numpy(),np.repeat(10+indexes/100,count))
        assert np.array_equal(result.volume.to_numpy(),np.tile(np.arange(count)+1000,len(indexes)))
        records.append(dict(run=label,seconds=elapsed,rows=len(result),
            hash=str(int(pd.util.hash_pandas_object(result,index=False).sum())),
            pandas_bytes=result.attrs['query']['pandas_bytes']))
    return dict(symbols=count,records=records,peak_working_set_bytes=peak_memory())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='output/verified-query-benchmark')
    parser.add_argument('--worker',type=int)
    parser.add_argument('--snapshot')
    args=parser.parse_args()
    root=Path(args.output).resolve()
    if args.worker:
        print(json.dumps(measure(root,args.snapshot,args.worker)))
        return
    snapshot=prepare(root)
    reports=[]
    for count in (10,100,5000):
        child=subprocess.run([sys.executable,__file__,'--output',str(root),'--worker',str(count),'--snapshot',snapshot],
            capture_output=True,text=True,timeout=120,check=True)
        reports.append(json.loads(child.stdout))
    report=dict(synthetic=True,rows_per_source=1000000,sources=2,scope='production query plus all raw/normalized artifact hash verification',
        publication_benchmarked=False,filesystem_cache='not_flushed',reports=reports)
    _atomic_write_json(root/'report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
