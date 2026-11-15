"""Historical pool/category records retain validity, availability and evidence scope."""
import json
from pathlib import Path

from .dataset_registry import _atomic_write_json
from .instrument_master import _date
from .snapshot_contracts import identity_hash


class MembershipStore:
    def __init__(self,root):
        self.directory=Path(root)/'memberships'
        self.directory.mkdir(parents=True,exist_ok=True)

    def save(self, *, dataset_id, classification_version, source, observed_on, rows, coverage,
             evidence_scope='observed_snapshot'):
        from .dataset_registry import _validate_dataset_id
        _validate_dataset_id(dataset_id)
        _validate_dataset_id(classification_version)
        _date(observed_on)
        if not source or evidence_scope not in {'observed_snapshot','verified_historical_intervals'}:
            raise ValueError('成分来源或历史证据范围无效')
        if not isinstance(coverage,dict) or set(coverage)!={'start','end','groups'}:
            raise ValueError('需要明确已核验分组及覆盖区间')
        _date(coverage['start']);_date(coverage['end'])
        if coverage['start']>coverage['end'] or not coverage['groups'] or len(set(coverage['groups']))!=len(coverage['groups']):
            raise ValueError('成分覆盖范围无效')
        if evidence_scope=='observed_snapshot' and coverage!=dict(start=observed_on,end=observed_on,groups=coverage['groups']):
            raise ValueError('观察快照覆盖只能是采集当日')
        normalized=[]
        for row in rows:
            if set(row)!={'symbol','group','valid_from','valid_until','announced_on','evidence_ref'}:
                raise ValueError('成分记录需要有效区间、公告时间和证据引用')
            for key in ('valid_from','announced_on'):_date(row[key])
            if row['valid_until'] is not None:_date(row['valid_until'])
            if not row['symbol'] or row['group'] not in coverage['groups'] or not row['evidence_ref']:
                raise ValueError('成分证券、分组或证据无效')
            if row['valid_until'] and row['valid_until']<=row['valid_from']:
                raise ValueError('成分有效区间必须为起日含、止日不含')
            if evidence_scope=='observed_snapshot' and (row['valid_from']!=observed_on or row['valid_until'] is not None):
                raise ValueError('当前成分快照不能冒充历史有效区间')
            normalized.append(dict(row))
        normalized.sort(key=lambda r:(r['group'],r['symbol'],r['valid_from']))
        identities=[(r['group'],r['symbol'],r['valid_from']) for r in normalized]
        if len(identities)!=len(set(identities)):
            raise ValueError('成分记录重复')
        for before,after in zip(normalized,normalized[1:]):
            if (before['symbol'],before['group'])==(after['symbol'],after['group']) and (
                before['valid_until'] is None or before['valid_until']>after['valid_from']):
                raise ValueError('同证券成分区间重叠')
        payload=dict(schema='historical-membership.v1',dataset_id=dataset_id,classification_version=classification_version,
            source=source,observed_on=observed_on,evidence_scope=evidence_scope,coverage=coverage,rows=normalized)
        identifier='membership-'+identity_hash(payload)
        _atomic_write_json(self.directory/(identifier+'.json'),payload)
        return identifier

    def open(self,identifier):
        import re
        if not isinstance(identifier,str) or not re.fullmatch(r'membership-[a-f0-9]{64}',identifier):
            raise ValueError('历史成分身份无效')
        payload=json.loads((self.directory/(identifier+'.json')).read_text(encoding='utf8'))
        if payload.get('schema')!='historical-membership.v1' or identifier!='membership-'+identity_hash(payload):
            raise ValueError('历史成分内容校验失败')
        return payload

    def members(self,identifier, *, group, session, master):
        _date(session)
        payload=self.open(identifier)
        coverage=payload['coverage']
        if group not in coverage['groups'] or not coverage['start']<=session<=coverage['end']:
            raise ValueError('历史成分覆盖不足，不能使用当前成分替代')
        if payload['evidence_scope']=='observed_snapshot' and session!=payload['observed_on']:
            raise ValueError('观察快照仅表示采集当日成分，不能前填或回填')
        instruments={r.symbol:r for r in master.records.values()}
        included=[]
        for row in payload['rows']:
            if row['group']!=group or not row['valid_from']<=session or (row['valid_until'] and session>=row['valid_until']):
                continue
            if row['announced_on']>=session:
                raise ValueError('成分变动缺少决策日前已可用的公告证据')
            instrument=instruments.get(row['symbol'])
            if instrument is None:
                raise ValueError('成分证券不在保留历史主表中')
            if instrument.listed_on>session or (instrument.delisted_on and instrument.delisted_on<=session):
                continue
            included.append(row['symbol'])
        return dict(symbols=sorted(included),session=session,group=group,membership_id=identifier,
            classification_version=payload['classification_version'],source=payload['source'],
            evidence_scope=payload['evidence_scope'],coverage=coverage)
