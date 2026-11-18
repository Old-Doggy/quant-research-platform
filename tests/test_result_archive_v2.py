from io import BytesIO
import json
from zipfile import ZipFile

import pandas as pd
import pytest


def seed(root):
    from test_result_history import seed as history_seed
    store=history_seed(root)
    value=store.load('fixture-run')
    value['audit_frame']=pd.DataFrame({'date':pd.date_range('2025-01-02',periods=2),'value':[1.,1.12]})
    store.save('portable-run',store._key(store._manifest('fixture-run')['key']),value)
    return store


def test_private_result_zip_restores_original_identity_arrays_and_reopens(tmp_path):
    from portfolio_app.result_archive_v2 import export_result,import_result
    from portfolio_app.result_store import ResultStore
    source=seed(tmp_path/'source')
    data=export_result(source,'portable-run')
    target=ResultStore(tmp_path/'target')
    assert import_result(target,data)=='portable-run'
    assert import_result(target,data)=='portable-run'
    assert len(target.records())==1
    before=source.load('portable-run');after=target.load('portable-run')
    pd.testing.assert_frame_equal(before.pop('audit_frame'),after.pop('audit_frame'),check_exact=True)
    assert before==after
    assert ResultStore(tmp_path/'target').records()[0]['created_at']==source._manifest('portable-run')['created_at']
    with ZipFile(BytesIO(data)) as archive:
        assert json.loads(archive.read('archive.json'))['disclosure']=='private_local'
        assert 'curve.csv' in archive.namelist()
        curve=pd.read_csv(archive.open('curve.csv'))
        assert curve.nav.tolist()==[1.,1.12]


@pytest.mark.parametrize('change',['array','traversal','duplicate','extra','budget','conflict'])
def test_bad_zip_or_conflicting_run_never_replaces_saved_result(tmp_path,change):
    from portfolio_app.result_archive_v2 import export_result,import_result
    from portfolio_app.result_store import ResultStore
    source=seed(tmp_path/'source');data=export_result(source,'portable-run')
    target=ResultStore(tmp_path/'target')
    if change=='conflict':
        manifest=source._manifest('portable-run')
        target.save('portable-run',source._key(manifest['key']),{'metrics':{'total_return':999}})
    elif change!='budget':
        with ZipFile(BytesIO(data)) as archive: files={name:archive.read(name) for name in archive.namelist()}
        if change=='array': files[next(k for k in files if k.endswith('.parquet'))]=b'broken'
        if change=='traversal': files['../outside']=b'bad'
        if change=='extra': files['unlisted.txt']=b'bad'
        buffer=BytesIO()
        with ZipFile(buffer,'w') as archive:
            for name,value in files.items(): archive.writestr(name,value)
            if change=='duplicate':
                with pytest.warns(UserWarning,match='Duplicate'):
                    archive.writestr('archive.json',files['archive.json'])
        data=buffer.getvalue()
    with pytest.raises(ValueError): import_result(target,data,max_bytes=1 if change=='budget' else 64_000_000)
    assert len(target.records())==(1 if change=='conflict' else 0)
    if change=='conflict': assert target.load('portable-run')['metrics']['total_return']==999
    assert not (tmp_path/'outside').exists()


def test_result_zip_export_budget_and_corruption_are_checked(tmp_path):
    from portfolio_app.result_archive_v2 import export_result
    source=seed(tmp_path)
    with pytest.raises(ValueError): export_result(source,'portable-run',max_bytes=1)
    next((source.root/'runs'/'portable-run').glob('*.parquet')).write_bytes(b'broken')
    with pytest.raises(ValueError): export_result(source,'portable-run')


@pytest.mark.parametrize('field,value', [('files', 'matching_names'), ('files', None), ('task_id', [])])
def test_malformed_archive_metadata_has_consistent_error_and_no_published_result(tmp_path, field, value):
    from portfolio_app.result_archive_v2 import export_result, import_result
    from portfolio_app.result_store import ResultStore
    source = seed(tmp_path/'source')
    with ZipFile(BytesIO(export_result(source, 'portable-run'))) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    meta = json.loads(files['archive.json'])
    meta[field] = list(meta['files']) if value == 'matching_names' else value
    files['archive.json'] = json.dumps(meta).encode()
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    target = ResultStore(tmp_path/'target')
    with pytest.raises(ValueError):
        import_result(target, buffer.getvalue())
    assert target.records() == []


def test_history_archive_is_prepared_on_demand_and_empty_store_can_import(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from portfolio_app.result_archive_v2 import export_result
    monkeypatch.setenv('PORTFOLIO_STATE_DIR',str(tmp_path))
    source='from portfolio_app.result_history_view import render_result_history\nrender_result_history(public_mode=False)'
    empty=AppTest.from_string(source).run()
    assert not empty.exception and empty.button(key='saved_result_import')
    seed(tmp_path)
    calls=[]
    def build(*a,**kw):
        calls.append(1);return export_result(*a,**kw)
    monkeypatch.setattr('portfolio_app.result_archive_v2.export_result',build)
    view=AppTest.from_string(source).run()
    assert not view.exception and calls==[]
    view.button(key='saved_result_prepare_zip').click().run()
    assert not view.exception and len(calls)==1
    assert view.get('download_button')
    view.run()
    assert len(calls)==1
