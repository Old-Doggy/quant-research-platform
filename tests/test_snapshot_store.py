import pandas as pd
import pytest


def setup_store(tmp_path):
    from portfolio_app.update_store import UpdateStore
    from portfolio_app.snapshot_store import SnapshotStore
    from portfolio_app.providers.base import ProviderBatch
    from test_data_update_flow import inputs
    from test_data_reconcile import frame
    update=UpdateStore(tmp_path)
    primary=frame(provider='baostock')
    secondary=frame(provider='sina')
    ids=[update.save_artifact(ProviderBatch(f,f.copy(),dict(provider=p,session='2025-01-02'), 'complete'))
         for f,p in [(primary,'baostock'),(secondary,'sina')]]
    master,calendar=inputs()
    return SnapshotStore(tmp_path),update,ids,master,calendar


def publish(store,ids,master,calendar,**options):
    return store.publish_daily(dataset_id='a-share',batch_ids=[ids[0]],comparison_ids=[ids[1]],
        master=master,calendars={'SSE':calendar},start='2025-01-02',end='2025-01-02',symbols=['600000.SH'],**options)


def test_publish_and_reopen_retains_inputs_and_old_snapshot_after_new_generation(tmp_path):
    from portfolio_app.providers.base import ProviderBatch
    store,updates,ids,master,calendar=setup_store(tmp_path)
    first=publish(store,ids,master,calendar)
    assert first['generation']==1
    assert store.current('a-share')['snapshot_id']==first['snapshot_id']
    assert first['research_capabilities']['price_browsing'] is True
    assert first['research_capabilities']['corporate_action_backtest'] is False
    assert store.read_frame(first['snapshot_id']).close.tolist()==[10.]
    other=[]
    for artifact in ids:
        b=updates.read_artifact(artifact)
        b.frame['close']=10.5
        other.append(updates.save_artifact(ProviderBatch(b.frame,b.raw,b.metadata,b.completeness)))
    second=publish(store,other,master,calendar)
    assert second['generation']==2
    assert store.current('a-share')['snapshot_id']==second['snapshot_id']
    assert store.read_frame(first['snapshot_id']).close.tolist()==[10.]
    assert store.read_frame(second['snapshot_id']).close.tolist()==[10.5]
    assert store.open(first['snapshot_id'])['checks']['coverage']['status']=='passed'


def test_incomplete_or_conflicting_batches_never_replace_current_snapshot(tmp_path):
    from portfolio_app.providers.base import ProviderBatch
    store,updates,ids,master,calendar=setup_store(tmp_path)
    first=publish(store,ids,master,calendar)
    b=updates.read_artifact(ids[1])
    b.frame['close']=10.1
    bad=updates.save_artifact(ProviderBatch(b.frame,b.raw,b.metadata,b.completeness))
    with pytest.raises(ValueError,match='核对|冲突'):
        publish(store,[ids[0],bad],master,calendar)
    with pytest.raises(ValueError,match='覆盖|缺口'):
        store.publish_daily(dataset_id='a-share',batch_ids=[ids[0]],comparison_ids=[ids[1]],
            master=master,calendars={'SSE':calendar},start='2025-01-02',end='2025-01-03',symbols=['600000.SH'])
    assert store.current('a-share')['snapshot_id']==first['snapshot_id']


def test_atomic_pointer_failure_keeps_old_snapshot_and_rollback_is_explicit(tmp_path,monkeypatch):
    import portfolio_app.snapshot_store as module
    store,updates,ids,master,calendar=setup_store(tmp_path)
    first=publish(store,ids,master,calendar)
    original=module._atomic_write_json
    def blocked(path,payload):
        if path.name=='current.json':
            raise PermissionError('simulated open file on Windows')
        return original(path,payload)
    with monkeypatch.context() as patch:
        patch.setattr(module,'_atomic_write_json',blocked)
        with pytest.raises(PermissionError):
            publish(store,ids,master,calendar)
    assert store.current('a-share')['snapshot_id']==first['snapshot_id']
    second=publish(store,ids,master,calendar)
    assert second['generation']>first['generation']
    store.rollback('a-share',first['snapshot_id'])
    assert store.current('a-share')['snapshot_id']==first['snapshot_id']


def test_tampered_batch_or_manifest_blocks_read_and_other_dataset_rollback(tmp_path):
    from pathlib import Path
    store,updates,ids,master,calendar=setup_store(tmp_path)
    result=publish(store,ids,master,calendar)
    with pytest.raises(ValueError):
        store.rollback('other',result['snapshot_id'])
    (tmp_path/'batches'/ids[0]/'normalized.parquet').write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        store.read_frame(result['snapshot_id'])


def test_browsing_snapshot_cannot_enter_research_until_required_event_status_rules_are_verified(tmp_path):
    from portfolio_app.research_integrity import audit_research_input
    store,updates,ids,master,calendar=setup_store(tmp_path)
    result=publish(store,ids,master,calendar)
    with pytest.raises(ValueError,match='公司行为|研究'):
        audit_research_input(store.read_frame(result['snapshot_id']))


def test_secondary_batch_corruption_invalidates_snapshot_verification(tmp_path):
    store,updates,ids,master,calendar=setup_store(tmp_path)
    result=publish(store,ids,master,calendar)
    (tmp_path/'batches'/ids[1]/'raw.parquet').write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        store.read_frame(result['snapshot_id'])
