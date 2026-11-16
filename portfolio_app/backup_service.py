"""Private selected-input backups, verified before atomic publication or restore."""
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import tempfile

from .dataset_registry import _atomic_write_json
from .result_codec import file_hash
from .result_store import ResultStore
from .snapshot_contracts import identity_hash
from .snapshot_store import SnapshotStore


def _file(root,name):
    if not isinstance(name,str) or '\\' in name:
        raise ValueError('备份文件名无效')
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or ':' in name or name!=path.as_posix():
        raise ValueError('备份文件路径超出目录')
    result=root.joinpath(*path.parts)
    if not result.resolve().is_relative_to(root.resolve()) or result.is_symlink():
        raise ValueError('备份不能跟随目录外链接')
    return result


def _destination(source,target):
    source,target=Path(source).resolve(),Path(target).resolve()
    if target==source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('备份或恢复目录不能相互包含')
    if target.exists(): raise FileExistsError('目标目录已存在，未覆盖')
    target.parent.mkdir(parents=True,exist_ok=True)
    return source,target


def _validate_payload(root,payload):
    market=SnapshotStore(root/'market_service')
    for identifier in payload['snapshot_ids']:
        market.read_frame(identifier)
    results=ResultStore(root/'research_results')
    for identifier in payload['result_ids']:
        manifest=results._manifest(identifier,indexed=False)
        results._decode(manifest,results.root/'runs'/identifier)
    return market,results


def create_backup(root,target,*,snapshot_ids,result_ids,max_bytes=2_000_000_000):
    root,target=_destination(root,target)
    if type(max_bytes) is not int or max_bytes<=0 or not snapshot_ids and not result_ids:
        raise ValueError('需要选择备份内容并设置正容量预算')
    if len(snapshot_ids)!=len(set(snapshot_ids)) or len(result_ids)!=len(set(result_ids)):
        raise ValueError('备份身份重复')
    market=SnapshotStore(root/'market_service')
    results=ResultStore(root/'research_results')
    files=set()
    for identifier in snapshot_ids:
        manifest=market.open(identifier)
        market.read_frame(identifier)
        files.add(f'market_service/snapshots/{identifier}.json')
        for batch in (*manifest['batch_ids'],*manifest['comparison_ids'],*manifest.get('reference_batch_ids',())):
            market.updates.verify_artifact(batch)
            for name in ('manifest.json','raw.parquet','normalized.parquet'):
                files.add(f'market_service/batches/{batch}/{name}')
    for identifier in result_ids:
        manifest=results._manifest(identifier)
        results.load(identifier)
        files.add(f'research_results/runs/{identifier}/manifest.json')
        for name in manifest['files']:
            if not re.fullmatch(r'array-\d{4,}\.parquet',name):
                raise ValueError('结果文件名无效')
            files.add(f'research_results/runs/{identifier}/{name}')
    total=sum(_file(root,name).stat().st_size for name in files)
    if total>max_bytes: raise ValueError('备份超过容量预算')
    with tempfile.TemporaryDirectory(prefix='.backup-',dir=target.parent) as temp:
        staging=Path(temp)/'bundle'
        staging.mkdir()
        hashes={}
        for name in sorted(files):
            source=_file(root,name)
            before=file_hash(source)
            destination=_file(staging,name)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,destination)
            if before!=file_hash(destination) or before!=file_hash(source):
                raise ValueError('备份过程中源文件发生变化')
            hashes[name]=before
        payload=dict(schema='private-research-backup.v1',disclosure='private_local',
            snapshot_ids=list(snapshot_ids),result_ids=list(result_ids),files=hashes,total_bytes=total,
            scope='selected_immutable_snapshots_and_results',credentials='excluded')
        _validate_payload(staging,payload)
        # Validation creates disposable indexes; rebuild only on restore.
        for name in ('market_service/updates.sqlite3','market_service/snapshots.sqlite3','research_results/results.sqlite3'):
            _file(staging,name).unlink(missing_ok=True)
        _atomic_write_json(staging/'backup-manifest.json',{**payload,'checksum':identity_hash(payload)})
        os.rename(staging,target)
    return payload


def restore_backup(source,target,*,max_bytes=2_000_000_000):
    source,target=_destination(source,target)
    if type(max_bytes) is not int or max_bytes<=0:
        raise ValueError('恢复容量预算必须为正整数')
    payload=json.loads((source/'backup-manifest.json').read_text(encoding='utf8'))
    checksum=payload.pop('checksum',None)
    if (payload.get('schema')!='private-research-backup.v1' or payload.get('disclosure')!='private_local'
            or checksum!=identity_hash(payload) or not isinstance(payload.get('files'),dict)):
        raise ValueError('备份清单校验失败')
    total=0
    for name,digest in payload['files'].items():
        path=_file(source,name)
        if not name.startswith(('market_service/snapshots/snapshot-','market_service/batches/batch-',
                                'research_results/runs/')) or file_hash(path)!=digest:
            raise ValueError('备份文件缺失或校验失败')
        total+=path.stat().st_size
    if total!=payload['total_bytes'] or total>max_bytes:
        raise ValueError('备份容量校验失败或超过预算')
    with tempfile.TemporaryDirectory(prefix='.restore-',dir=target.parent) as temp:
        staging=Path(temp)/'state'
        staging.mkdir()
        for name in payload['files']:
            destination=_file(staging,name)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(_file(source,name),destination)
            if file_hash(destination)!=payload['files'][name]:
                raise ValueError('恢复文件校验失败')
        market,results=_validate_payload(staging,payload)
        latest={}
        for identifier in payload['snapshot_ids']:
            manifest=market.open(identifier)
            dataset=manifest['dataset_id']
            if dataset not in latest or manifest['generation']>latest[dataset]['generation']:
                latest[dataset]=manifest
        for dataset,manifest in latest.items():
            with market.connect() as db:
                db.execute('INSERT INTO generations VALUES (?,?)',(dataset,manifest['generation']))
            market.rollback(dataset,manifest['snapshot_id'])
        for identifier in payload['result_ids']:
            manifest=results._manifest(identifier,indexed=False)
            results._index(identifier,results._key(manifest['key']),manifest)
            results.load(identifier)
        _atomic_write_json(staging/'restore-receipt.json',{**payload,'checksum':identity_hash(payload)})
        os.rename(staging,target)
    return dict(status='restored',snapshots=len(payload['snapshot_ids']),results=len(payload['result_ids']))


def main():
    import argparse
    parser=argparse.ArgumentParser(description='备份选定研究数据，或恢复至新的本地目录')
    commands=parser.add_subparsers(dest='operation',required=True)
    create=commands.add_parser('create')
    create.add_argument('--root',required=True)
    create.add_argument('--target',required=True)
    create.add_argument('--snapshot',action='append',default=[])
    create.add_argument('--result',action='append',default=[])
    restore=commands.add_parser('restore')
    restore.add_argument('--source',required=True)
    restore.add_argument('--target',required=True)
    args=parser.parse_args()
    if args.operation=='create':
        value=create_backup(args.root,args.target,snapshot_ids=args.snapshot,result_ids=args.result)
        report=dict(status='backed_up',snapshots=len(value['snapshot_ids']),results=len(value['result_ids']),
            bytes=value['total_bytes'],disclosure=value['disclosure'])
    else:
        report=restore_backup(args.source,args.target)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
