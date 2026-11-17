"""Repeat production query, research, chart building and restore on bounded samples."""
import argparse
import json
import os
from pathlib import Path
import platform
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmark_market_query import peak_memory
from portfolio_app.data import read_market_file
from portfolio_app.market_query import query_daily
from portfolio_app.snapshot_store import SnapshotStore
from portfolio_app.portfolio_recipe import PortfolioRecipe
from portfolio_app.offline_execution import ExecutionSpec
from portfolio_app.portfolio_workspace import run_portfolio_workspace
from portfolio_app.research_charts import build_performance_chart
from portfolio_app.result_store import ResultStore
from portfolio_app.research_result_cache import build_research_cache_key


def measure(operation,check,repeats):
    values=[]
    for _ in range(repeats):
        started=time.perf_counter()
        result=operation()
        elapsed=time.perf_counter()-started
        check(result)
        values.append(elapsed)
    return dict(samples_seconds=values,first_call_seconds=values[0],
        repeat_p50_seconds=float(np.percentile(values[1:],50)),
        repeat_p95_seconds=float(np.percentile(values[1:],95)),peak_working_set_bytes=peak_memory())


def require(condition):
    if not condition:
        raise AssertionError('benchmark changed result semantics')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=21)
    args=parser.parse_args()
    if not 6<=args.repeats<=101:
        parser.error('repeats must be 6–101')
    if args.output.exists():
        parser.error('output must be new')
    args.output.mkdir(parents=True)
    market=SnapshotStore(args.state/'market_service')
    current=market.current('free-a-daily')
    scope=current['range']
    def query():
        return query_daily(market,current['snapshot_id'],symbols=scope['symbols'],start=scope['start'],end=scope['end'],
            columns=['symbol','trade_date','close','amount'])
    reference=query()
    result={}
    result['real_snapshot_query']=measure(query,lambda r:pd.testing.assert_frame_equal(r,reference),args.repeats)
    frame=read_market_file(Path(__file__).resolve().parents[1]/'portfolio_app/sample_data/quant_demo_multi_symbol.csv')
    symbols=sorted(frame.symbol.unique())[:3]
    common=set.intersection(*(set(frame.loc[frame.symbol.eq(s),'trade_date']) for s in symbols))
    frames={s:frame.loc[frame.symbol.eq(s)&frame.trade_date.isin(common)].copy() for s in symbols}
    recipe=PortfolioRecipe.from_dict(dict(recipe_id='benchmark',target_weights={s:.9/len(symbols) for s in symbols},
        cash_weight=.1,lot_size=100,min_rebalance_weight=.01))
    spec=ExecutionSpec('next_close','close','next_close',10.,0.,'cn_stock')
    def research():
        return run_portfolio_workspace(frames,recipe=recipe,spec=spec,strategy_key='trend',
            params={'fast_window':5,'slow_window':30},initial_cash=100000.)
    expected=research()
    def check_research(actual):
        pd.testing.assert_frame_equal(actual.accounting.ledger,expected.accounting.ledger,check_exact=True)
        require(actual.fills==expected.fills)
    result['synthetic_portfolio_research']=measure(research,check_research,args.repeats)
    ledger=expected.accounting.ledger
    def chart():
        return build_performance_chart(ledger,nav='unit_nav').to_json()
    result['plotly_build_and_json']=measure(chart,lambda r:require(len(json.loads(r)['data'])==2),args.repeats)
    store=ResultStore(args.output/'result-store')
    cache_key=build_research_cache_key(dataset_id='portfolio',data_version='benchmark',processing={},engine_id='test')
    store.save('benchmark-result',cache_key,{'baseline':expected})
    result['result_package_load']=measure(lambda:store.load('benchmark-result'),
        lambda r:check_research(r['baseline']),args.repeats)
    report=dict(schema='research-performance-observation.v1',python=sys.version,os=platform.platform(),
        cpu=platform.processor(),logical_cpus=os.cpu_count(),peak_working_set_bytes=peak_memory(),
        cache='OS filesystem cache not flushed; imports/input preparation excluded; sequential same process',
        scope=dict(query_rows=len(reference),query_symbols=len(scope['symbols']),snapshot=current['snapshot_id'],
            synthetic_research=True,research_sessions=len(ledger),research_symbols=len(frames),fills=len(expected.fills)),
        results=result,not_measured=['cold app start','full market query','network updates','browser paint',
            'full backup restore','sustained memory growth','p95 in production'])
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(scope=report['scope'],results={k:{f:v for f,v in r.items() if f!='samples_seconds'} for k,r in result.items()}),indent=2))


if __name__=='__main__':
    main()
