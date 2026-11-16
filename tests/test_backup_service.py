import json
import sqlite3

import pandas as pd
import pytest


def seed(tmp_path):
    from test_snapshot_store import setup_store,publish
    from test_result_history import seed as seed_result
    root=tmp_path/'state'
    store,updates,ids,master,calendar=setup_store(root/'market_service')
    manifest=publish(store,ids,master,calendar)
    results=seed_result(root)
    (root/'.env').write_text('SENSITIVE_SENTINEL=not-for-backup')
    return root,store,manifest,results


def test_selected_snapshot_results_restore_after_damaged_live_db(tmp_path):
    from portfolio_app.backup_service import create_backup,restore_backup
    from portfolio_app.snapshot_store import SnapshotStore
    from portfolio_app.result_store import ResultStore
    root,store,manifest,results=seed(tmp_path)
    expected=store.read_frame(manifest['snapshot_id'])
    receipt=create_backup(root,tmp_path/'backup',snapshot_ids=[manifest['snapshot_id']],result_ids=['fixture-run'])
    assert receipt['disclosure']=='private_local'
    assert not any('.env' in name or 'tasks.sqlite' in name for name in receipt['files'])
    (root/'research_results'/'results.sqlite3').write_bytes(b'damaged-database')
    restore_backup(tmp_path/'backup',tmp_path/'restored')
    pd.testing.assert_frame_equal(SnapshotStore(tmp_path/'restored'/'market_service').read_frame(manifest['snapshot_id']),expected)
    assert ResultStore(tmp_path/'restored'/'research_results').load('fixture-run')['metrics']=={'total_return':.12,'max_drawdown':-.04}
    assert SnapshotStore(tmp_path/'restored'/'market_service').current('a-share')['snapshot_id']==manifest['snapshot_id']
    with sqlite3.connect(tmp_path/'restored'/'research_results'/'results.sqlite3') as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_corrupt_file_or_path_escape_does_not_publish_restore(tmp_path):
    from portfolio_app.backup_service import create_backup,restore_backup
    root,store,manifest,results=seed(tmp_path)
    receipt=create_backup(root,tmp_path/'backup',snapshot_ids=[manifest['snapshot_id']],result_ids=['fixture-run'])
    file=next(name for name in receipt['files'] if name.endswith('.parquet'))
    (tmp_path/'backup'/file).write_bytes(b'broken')
    with pytest.raises(ValueError):
        restore_backup(tmp_path/'backup',tmp_path/'restored')
    assert not (tmp_path/'restored').exists()
    with pytest.raises(ValueError):
        create_backup(root,root/'nested',snapshot_ids=[manifest['snapshot_id']],result_ids=[])
    with pytest.raises(ValueError):
        create_backup(root,tmp_path/'too-small',snapshot_ids=[manifest['snapshot_id']],result_ids=[],max_bytes=1)
    assert not (tmp_path/'too-small').exists()


def test_existing_target_never_overwritten_and_backup_manifest_tamper_rejected(tmp_path):
    from portfolio_app.backup_service import create_backup,restore_backup
    root,store,manifest,results=seed(tmp_path)
    create_backup(root,tmp_path/'backup',snapshot_ids=[manifest['snapshot_id']],result_ids=[])
    target=tmp_path/'existing'
    target.mkdir()
    (target/'mine.txt').write_text('keep')
    with pytest.raises(FileExistsError):
        restore_backup(tmp_path/'backup',target)
    assert (target/'mine.txt').read_text()=='keep'
    path=tmp_path/'backup'/'backup-manifest.json'
    value=json.loads(path.read_text())
    value['files']['../escape']='0'*64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        restore_backup(tmp_path/'backup',tmp_path/'restored')
