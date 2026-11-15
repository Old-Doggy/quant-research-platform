"""Atomic publication of checked daily batches; old snapshots remain addressable."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3

import pandas as pd

from .dataset_registry import _atomic_write_json, _validate_dataset_id
from .data import build_data_quality_report
from .data_reconcile import compare_daily_sources, check_daily_coverage
from .snapshot_contracts import identity_hash, snapshot_from_hash, SnapshotReference
from .update_store import UpdateStore, UpdateBusy


class SnapshotStore:
    def __init__(self, root):
        self.root = Path(root)
        self.updates = UpdateStore(root)
        self.directory = self.root / 'snapshots'
        self.directory.mkdir(exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS generations (dataset TEXT PRIMARY KEY, value INTEGER)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root/'snapshots.sqlite3',timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _lock(self, dataset):
        _validate_dataset_id(dataset)
        path = self.directory/dataset
        path.mkdir(exist_ok=True)
        with (path/'publish.lock').open('a+b') as handle:
            if handle.tell()==0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            acquired=False
            try:
                try:
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    acquired=True
                except OSError as exc:
                    raise UpdateBusy('此数据集正在发布或回退') from exc
                yield
            finally:
                if acquired:
                    handle.seek(0)
                    if os.name=='nt':
                        msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                    else:
                        fcntl.flock(handle,fcntl.LOCK_UN)

    def _frames(self, artifacts):
        if not artifacts or len(artifacts)!=len(set(artifacts)):
            raise ValueError('快照批次为空或重复')
        batches=[self.updates.read_artifact(a) for a in artifacts]
        providers={b.metadata.get('provider') for b in batches}
        if len(providers)!=1 or None in providers or any(b.completeness!='complete' for b in batches):
            raise ValueError('快照批次来源不一致或记录覆盖未完成')
        attrs=batches[0].frame.attrs
        for batch in batches:
            if batch.frame.attrs.get('field_units')!=attrs.get('field_units'):
                raise ValueError('快照批次单位不一致')
            if batch.frame.attrs.get('normalization',{}).get('profile')!=attrs.get('normalization',{}).get('profile'):
                raise ValueError('快照批次输出精度profile不一致，需分数据集核对')
            if batch.frame.attrs.get('research_dataset',{}).get('price_basis')!='raw':
                raise ValueError('快照只接受原始日线')
        parts=[]
        for batch in batches:
            part=batch.frame.copy(deep=True)
            part.attrs={}
            parts.append(part)
        frame=pd.concat(parts,ignore_index=True).sort_values(['ts_code','trade_date']).reset_index(drop=True)
        frame.attrs=dict(attrs)
        if frame.duplicated(['ts_code','trade_date']).any() or build_data_quality_report(frame)['status']!='通过':
            raise ValueError('快照行情结构、数值或唯一键检查未通过')
        return frame,next(iter(providers))

    def inspect_daily(self, *, batch_ids, comparison_ids, master, calendars, start, end, symbols):
        primary,provider=self._frames(batch_ids)
        secondary,other=self._frames(comparison_ids)
        coverage=check_daily_coverage(primary,master=master,calendars=calendars,
            start=start,end=end,symbols=symbols)
        comparison=compare_daily_sources(primary,secondary,primary_provider=provider,secondary_provider=other)
        return dict(coverage=coverage,comparison=comparison)

    def publish_daily(self, *, dataset_id, batch_ids, comparison_ids, master, calendars,
                      start, end, symbols, reference_batch_ids=()):
        _validate_dataset_id(dataset_id)
        checks=self.inspect_daily(batch_ids=batch_ids,comparison_ids=comparison_ids,master=master,
            calendars=calendars,start=start,end=end,symbols=symbols)
        coverage,comparison=checks['coverage'],checks['comparison']
        provider,other=comparison['primary_provider'],comparison['secondary_provider']
        if coverage['status']!='passed':
            raise ValueError('行情覆盖有缺口或冲突，未发布快照')
        if comparison['status']!='passed':
            raise ValueError('跨源核对不完整或冲突，未发布快照')
        for artifact in reference_batch_ids:
            self.updates.verify_artifact(artifact)
        with self._lock(dataset_id):
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT value FROM generations WHERE dataset=?',(dataset_id,)).fetchone()
                generation=(row[0] if row else 0)+1
                db.execute('INSERT OR REPLACE INTO generations VALUES (?,?)',(dataset_id,generation))
            payload=dict(schema_version='daily-snapshot-store.v1',dataset_id=dataset_id,generation=generation,
                batch_ids=list(batch_ids),comparison_ids=list(comparison_ids),provider=provider,
                reference_batch_ids=list(reference_batch_ids),
                comparison_provider=other,range=dict(start=start,end=end,symbols=sorted(set(symbols))),
                instrument_master=master.to_dict(),calendars={m:c.to_dict() for m,c in sorted(calendars.items())},
                checks=dict(coverage=coverage,comparison=comparison),
                research_capabilities=dict(price_browsing=True,corporate_action_backtest=False,
                    point_in_time_financial=False),validation_scope='raw_daily_prices_and_coverage')
            reference=snapshot_from_hash(identity_hash(payload),dataset_id=dataset_id,generation=generation,
                price_basis='raw',completeness='complete')
            manifest={**payload,'snapshot_id':reference.snapshot_id,'reference':reference.__dict__}
            _atomic_write_json(self.directory/(reference.snapshot_id+'.json'),manifest)
            # The only publication point. Failure leaves current readers on the old manifest.
            pointer=dict(dataset_id=dataset_id,snapshot_id=reference.snapshot_id,generation=generation)
            _atomic_write_json(self.directory/dataset_id/'current.json',
                {**pointer,'checksum':identity_hash(pointer)})
            return manifest

    def open(self, snapshot_id):
        if not isinstance(snapshot_id,str) or not re.fullmatch(r'snapshot-[a-f0-9]{64}',snapshot_id):
            raise ValueError('快照身份无效')
        manifest=json.loads((self.directory/(snapshot_id+'.json')).read_text(encoding='utf8'))
        reference=SnapshotReference.from_dict(manifest['reference'])
        payload={k:v for k,v in manifest.items() if k not in {'reference','snapshot_id'}}
        if (reference.snapshot_id!=snapshot_id or manifest['snapshot_id']!=snapshot_id
                or reference.content_sha256!=identity_hash(payload)
                or reference.dataset_id!=manifest['dataset_id'] or reference.generation!=manifest['generation']):
            raise ValueError('快照清单校验失败')
        return manifest

    def current(self,dataset_id):
        _validate_dataset_id(dataset_id)
        path=self.directory/dataset_id/'current.json'
        if not path.exists():
            return None
        pointer=json.loads(path.read_text(encoding='utf8'))
        if pointer.pop('checksum',None)!=identity_hash(pointer):
            raise ValueError('当前快照指针校验失败')
        manifest=self.open(pointer['snapshot_id'])
        if manifest['dataset_id']!=dataset_id or manifest['generation']!=pointer['generation']:
            raise ValueError('当前快照范围不符')
        return manifest

    def read_frame(self,snapshot_id):
        manifest=self.open(snapshot_id)
        try:
            frame,_=self._frames(manifest['batch_ids'])
            for artifact in (*manifest['comparison_ids'],*manifest.get('reference_batch_ids',())):
                self.updates.read_artifact(artifact)
        except (OSError,ValueError,KeyError) as exc:
            raise ValueError('快照底层批次缺失或校验失败') from exc
        frame.attrs['snapshot']=manifest['reference']
        frame.attrs['research_dataset']=dict(dataset_id=manifest['dataset_id'],version=snapshot_id,
            price_basis='raw',source_kind='provider_snapshot')
        frame.attrs['research_capabilities']=manifest['research_capabilities']
        return frame

    def rollback(self,dataset_id,snapshot_id):
        manifest=self.open(snapshot_id)
        if manifest['dataset_id']!=dataset_id:
            raise ValueError('不能回退到其他数据集')
        self.read_frame(snapshot_id)
        with self._lock(dataset_id):
            pointer=dict(dataset_id=dataset_id,snapshot_id=snapshot_id,generation=manifest['generation'])
            _atomic_write_json(self.directory/dataset_id/'current.json',
                {**pointer,'checksum':identity_hash(pointer)})
