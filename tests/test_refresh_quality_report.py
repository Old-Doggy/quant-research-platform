def test_candidate_conflict_returns_actual_evidence_and_retains_current(tmp_path):
    from portfolio_app.snapshot_store import SnapshotStore
    from portfolio_app.free_refresh_plan import save_plan,run_plan
    from portfolio_app.providers.base import ProviderBatch
    from test_snapshot_store import setup_store,publish
    store,updates,ids,master,calendar=setup_store(tmp_path)
    original=publish(store,ids,master,calendar)
    shards=[dict(symbol='600000.SH',sessions=['2025-01-02'])]
    plan=save_plan(store,dataset_id='a-share',master=master,calendars={'SSE':calendar},references=[],
        shards=shards,start='2025-01-02',end='2025-01-02',symbols=['600000.SH'])
    class Provider:
        def __init__(self,index): self.index=index
        def daily(self,*a,**kw):
            batch=updates.read_artifact(ids[self.index])
            if self.index==1:
                batch.frame['close']=10.1
            return batch
    report=run_plan(tmp_path,plan,providers=dict(baostock=Provider(0),sina=Provider(1)))
    assert report['status']=='needs_review'
    assert report['checks']['coverage']['status']=='passed'
    assert report['checks']['comparison']['status']=='conflict'
    difference=next(r for r in report['checks']['comparison']['differences'] if r['field']=='close')
    assert difference['primary']==10. and difference['secondary']==10.1
    assert difference['symbol']=='600000.SH'
    assert store.current('a-share')['snapshot_id']==original['snapshot_id']
