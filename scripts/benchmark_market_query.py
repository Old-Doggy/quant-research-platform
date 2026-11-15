"""Synthetic million-row scan comparison; never uses private market inputs."""
import argparse
import ctypes
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


def peak_memory():
    if sys.platform != 'win32':
        return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
            *[(name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize',
                'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]]
    current=ctypes.windll.kernel32.GetCurrentProcess
    current.restype=wintypes.HANDLE
    result=Counters()
    result.cb=ctypes.sizeof(result)
    memory_info=ctypes.windll.psapi.GetProcessMemoryInfo
    memory_info.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    memory_info.restype=wintypes.BOOL
    if memory_info(current(),ctypes.byref(result),result.cb):
        return result.PeakWorkingSetSize
    return None


def run(path,backend,count):
    codes=[f'{600000+i:06d}.SH' for i in range(count)]
    start,end=pd.Timestamp('2025-03-03'),pd.Timestamp('2025-04-30')
    columns=['ts_code','trade_date','close','volume']
    files=sorted(path.glob('part-*.parquet'))
    def query():
        if backend=='pandas':
            data=pd.concat([pd.read_parquet(p) for p in files],ignore_index=True)
            return data.loc[data.ts_code.isin(codes)&data.trade_date.between(start,end),columns]
        if backend=='arrow':
            data=ds.dataset(files,format='parquet')
            predicate=ds.field('ts_code').isin(codes)&(ds.field('trade_date')>=start.to_datetime64())&(ds.field('trade_date')<=end.to_datetime64())
            return data.to_table(columns=columns,filter=predicate).to_pandas()
        import duckdb
        with duckdb.connect() as connection:
            return connection.execute('SELECT ts_code,trade_date,close,volume FROM read_parquet(?) '
                'WHERE ts_code IN (SELECT unnest(?)) AND trade_date BETWEEN ? AND ?',
                [[str(p) for p in files],codes,start,end]).df()
    records=[]
    for label in ('first_process_read','repeat_read'):
        started=time.perf_counter()
        data=query().sort_values(['trade_date','ts_code']).reset_index(drop=True)
        elapsed=time.perf_counter()-started
        digest=int(pd.util.hash_pandas_object(data,index=False).sum())
        records.append(dict(run=label,seconds=elapsed,rows=len(data),data_hash=str(digest)))
    return dict(backend=backend,symbols=count,runs=records,peak_working_set_bytes=peak_memory())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='output/query-benchmark')
    parser.add_argument('--worker',choices=['pandas','arrow','duckdb'])
    parser.add_argument('--symbols',type=int,default=10)
    args=parser.parse_args()
    root=Path(args.output).resolve()
    if args.worker:
        print(json.dumps(run(root,args.worker,args.symbols)))
        return
    root.mkdir(parents=True,exist_ok=True)
    dates=pd.bdate_range('2025-01-02',periods=200)
    for part in range(10):
        codes=np.array([f'{600000+i:06d}.SH' for i in range(part*500,(part+1)*500)])
        frame=pd.DataFrame(dict(ts_code=np.repeat(codes,200),trade_date=np.tile(dates,500),
            close=np.tile(np.arange(200)/100+10,500),volume=np.repeat(np.arange(500)+1000,200)))
        frame.to_parquet(root/f'part-{part:02d}.parquet',index=False,row_group_size=20000)
    reports=[]
    for backend in ('pandas','arrow','duckdb'):
        for count in (10,100,5000):
            child=subprocess.run([sys.executable,__file__,'--output',str(root),'--worker',backend,'--symbols',str(count)],
                capture_output=True,text=True,timeout=60)
            if child.returncode:
                raise RuntimeError(child.stderr)
            reports.append(json.loads(child.stdout))
    for count in (10,100,5000):
        hashes={r['runs'][0]['data_hash'] for r in reports if r['symbols']==count}
        if len(hashes)!=1:
            raise ValueError('Backend results differ')
    report=dict(python=platform.python_version(),machine=platform.machine(),rows=1000000,
        synthetic=True,filesystem_cache='not_flushed; first process read is not a guaranteed cold disk read',
        scope='scan_only; excludes snapshot hash verification and publication',reports=reports)
    (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
