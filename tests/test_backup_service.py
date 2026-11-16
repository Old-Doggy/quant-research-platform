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


def seed_observations(root):
    from test_convertible_data import reference_batch
    from test_etf_data import source
    from portfolio_app.convertible_store import ConvertibleStore
    from portfolio_app.etf_research import ETFStore
    from portfolio_app.providers.etf import SinaETF
    from portfolio_app.financial_store import FinancialStore
    from test_sina_financial import batch as financial_batch
    cb=ConvertibleStore(root/'convertible_service').ingest(reference_batch())
    etf=ETFStore(root/'etf_service').ingest(SinaETF(transport=lambda **kw:source()).daily(
        '510300.SH',start='2025-01-02',end='2025-01-03'))
    financial=FinancialStore(root/'financial_service').ingest(financial_batch())
    return dict(convertible=[cb],etf=[etf],financial=[financial])


def test_selected_observations_restore_raw_batches_and_rebuild_indexes(tmp_path,monkeypatch):
    from portfolio_app.backup_service import create_backup,restore_backup
    from portfolio_app.convertible_store import ConvertibleStore
    from portfolio_app.etf_research import ETFStore
    from portfolio_app.financial_store import FinancialStore
    root=tmp_path/'state';selected=seed_observations(root)
    receipt=create_backup(root,tmp_path/'backup',snapshot_ids=[],result_ids=[],observation_ids=selected)
    assert receipt['observation_ids']==selected
    assert not any(name.endswith('.sqlite3') for name in receipt['files'])
    for service in ['convertible','etf','financial']:
        (root/(service+'_service')/(service+'.sqlite3')).write_bytes(b'broken')
    from portfolio_app.update_store import UpdateStore
    monkeypatch.setattr(UpdateStore,'save_artifact',lambda *a:pytest.fail('restore rewrote immutable parquet'))
    restore_backup(tmp_path/'backup',tmp_path/'restored')
    cb=ConvertibleStore(tmp_path/'restored'/'convertible_service')
    assert cb.load(selected['convertible'][0]).metadata['events'][0]['price']==20.
    assert cb.records()[0]['artifact_id']==selected['convertible'][0]
    etf=ETFStore(tmp_path/'restored'/'etf_service')
    assert etf.load(selected['etf'][0]).frame.volume.tolist()==[1000,2000]
    rows=FinancialStore(tmp_path/'restored'/'financial_service').observations(endpoint='income',symbol='600000.SH',provider='sina')
    assert rows and {r['artifact_id'] for r in rows}==set(selected['financial'])


def test_observation_selection_validates_service_and_artifact_coverage(tmp_path):
    from portfolio_app.backup_service import create_backup,restore_backup
    from portfolio_app.snapshot_contracts import identity_hash
    root=tmp_path/'state';selected=seed_observations(root)
    for invalid in [dict(secret=['x']),dict(etf=selected['convertible']),dict(etf=selected['etf']*2)]:
        with pytest.raises(ValueError):
            create_backup(root,tmp_path/'invalid',snapshot_ids=[],result_ids=[],observation_ids=invalid)
    create_backup(root,tmp_path/'backup',snapshot_ids=[],result_ids=[],observation_ids=selected)
    path=tmp_path/'backup'/'backup-manifest.json'
    value=json.loads(path.read_text());value.pop('checksum')
    removed=next(k for k in value['files'] if k.endswith('raw.parquet'))
    value['total_bytes']-=(tmp_path/'backup'/removed).stat().st_size
    del value['files'][removed]
    path.write_text(json.dumps({**value,'checksum':identity_hash(value)}))
    with pytest.raises(ValueError): restore_backup(tmp_path/'backup',tmp_path/'restored')
    assert not (tmp_path/'restored').exists()
