"""Portable private result bundles with bounded, allowlisted ZIP import."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
from zipfile import BadZipFile,ZipFile,ZIP_DEFLATED

from .process_lock import process_lock
from .result_history import result_projection
from .result_store import ResultStore,_identifier


def _json(value):
    return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')


def export_result(store,task_id,*,max_bytes=64_000_000):
    manifest=store._manifest(task_id)
    value=store.load(task_id)
    directory=store.root/'runs'/task_id
    names=['manifest.json',*manifest['files']]
    if any(not re.fullmatch(r'array-\d{4,}\.parquet',n) for n in manifest['files']):
        raise ValueError('结果文件名无效')
    if type(max_bytes) is not int or max_bytes<=0 or sum((directory/n).stat().st_size for n in names)>max_bytes:
        raise ValueError('归档超过容量预算')
    files={f'result/{name}':(directory/name).read_bytes() for name in names}
    if any(hashlib.sha256(files['result/'+n]).hexdigest()!=digest for n,digest in manifest['files'].items()):
        raise ValueError('结果数组校验失败')
    projection=result_projection(value)
    for key in ('curve','ic'):
        frame=projection[key]
        if frame is not None:
            files[key+'.csv']=frame.to_csv(index=False).encode('utf-8-sig')
    metadata=dict(schema='private-result-archive.v1',disclosure='private_local',task_id=task_id,
        files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()})
    files['archive.json']=_json(metadata)
    if sum(map(len,files.values()))>max_bytes: raise ValueError('归档超过容量预算')
    buffer=BytesIO()
    with ZipFile(buffer,'w',compression=ZIP_DEFLATED) as archive:
        for name,data in files.items(): archive.writestr(name,data)
    return buffer.getvalue()


def import_result(store,data,*,max_bytes=64_000_000):
    if type(max_bytes) is not int or max_bytes<=0 or len(data)>max_bytes:
        raise ValueError('归档超过容量预算')
    try:
        return _import_result(store,data,max_bytes)
    except (BadZipFile,KeyError,UnicodeError,json.JSONDecodeError,TypeError) as exc:
        raise ValueError('归档结构或内容无效') from exc


def _import_result(store,data,max_bytes):
    with ZipFile(BytesIO(data)) as archive:
        infos=archive.infolist();names=[i.filename for i in infos]
        if (len(infos)>4096 or len(names)!=len(set(names)) or 'archive.json' not in names
                or sum(i.file_size for i in infos)>max_bytes or any(i.flag_bits&1 for i in infos)):
            raise ValueError('归档数量、重复文件或容量无效')
        allowed=lambda n:n in {'archive.json','curve.csv','ic.csv','result/manifest.json'} or bool(re.fullmatch(r'result/array-\d{4,}\.parquet',n))
        if not all(allowed(n) for n in names): raise ValueError('归档包含未知文件或路径')
        if archive.getinfo('archive.json').file_size>1_000_000: raise ValueError('归档索引过大')
        meta=json.loads(archive.read('archive.json'))
        if not isinstance(meta, dict) or not isinstance(meta.get('files'), dict):
            raise ValueError('归档索引结构无效')
        task_id=_identifier(meta['task_id'])
        if (meta.get('schema')!='private-result-archive.v1' or meta.get('disclosure')!='private_local'
                or set(meta['files'])!=set(names)-{'archive.json'}):
            raise ValueError('归档清单与文件不符')
        # Write to an isolated result store; never extract user-provided paths.
        with tempfile.TemporaryDirectory(prefix='.import-',dir=store.root) as temp:
            staging=ResultStore(Path(temp))
            directory=staging.root/'runs'/task_id;directory.mkdir()
            for name,digest in meta['files'].items():
                body=archive.read(name)
                if hashlib.sha256(body).hexdigest()!=digest: raise ValueError('归档文件校验失败')
                if name.startswith('result/'):
                    (directory/name.removeprefix('result/')).write_bytes(body)
            manifest=staging._manifest(task_id,indexed=False)
            if set(manifest['files'])!={n.removeprefix('result/') for n in names if n.endswith('.parquet')}:
                raise ValueError('结果数组清单不完整')
            if any(hashlib.sha256((directory/n).read_bytes()).hexdigest()!=digest for n,digest in manifest['files'].items()):
                raise ValueError('结果数组校验失败')
            staging._decode(manifest,directory)
            key=store._key(manifest['key'])
            with process_lock(store.root/'locks'/(task_id+'.lock'),wait=True):
                target=store.root/'runs'/task_id
                if target.exists():
                    old=store._manifest(task_id,indexed=False)
                    if old['checksum']!=manifest['checksum']: raise ValueError('已有同名研究，内容不同，未覆盖')
                    store._decode(old,target)
                    manifest=old
                else:
                    os.rename(directory,target)
                store._index(task_id,key,manifest)
            store.load(task_id)
            return task_id
