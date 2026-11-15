"""Persistent security identity and dated observations, retaining inactive names."""
from dataclasses import asdict, dataclass
from datetime import date
import json
import copy
from pathlib import Path

from .dataset_registry import _atomic_write_json
from .snapshot_contracts import identity_hash


class InstrumentMasterError(ValueError):
    pass


def _date(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError('noncanonical')
    except (ValueError, TypeError) as exc:
        raise InstrumentMasterError('证券日期必须为YYYY-MM-DD') from exc
    return value


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    symbol: str
    name: str
    market: str
    asset_type: str
    subtype: str
    listed_on: str
    delisted_on: str | None
    provider: str
    provider_code: str

    def __post_init__(self):
        for name in ('instrument_id', 'symbol', 'name', 'subtype', 'provider', 'provider_code'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise InstrumentMasterError('证券身份、名称和来源代码不能为空')
        if self.market not in {'SSE', 'SZSE', 'BSE', 'HKEX', 'US'}:
            raise InstrumentMasterError('未知证券市场')
        if self.asset_type not in {'cn_stock', 'hk_stock', 'us_stock', 'etf', 'convertible', 'index'}:
            raise InstrumentMasterError('未知资产类别')
        _date(self.listed_on)
        if self.delisted_on is not None and _date(self.delisted_on) < self.listed_on:
            raise InstrumentMasterError('退市日在上市日前')


class InstrumentMaster:
    def __init__(self):
        self.records = {}
        self.aliases = {}
        self.changes = []

    def update(self, rows, *, observed_on, source, batch_id):
        _date(observed_on)
        if not source or not batch_id:
            raise InstrumentMasterError('证券批次缺少来源或身份')
        if self.changes and observed_on < self.changes[-1]['observed_on']:
            raise InstrumentMasterError('证券主表观察日期不能倒退')
        if any(c['batch_id'] == batch_id and c['source'] == source for c in self.changes):
            raise InstrumentMasterError('证券主表批次重复')
        try:
            incoming = tuple(r if isinstance(r, Instrument) else Instrument(**r) for r in rows)
        except TypeError as exc:
            raise InstrumentMasterError('证券主表字段无效') from exc
        staged, aliases = dict(self.records), dict(self.aliases)
        seen, added, renamed, delisted = set(), [], [], []
        for item in incoming:
            identity = item.instrument_id
            if identity in seen:
                raise InstrumentMasterError('同批证券ID冲突')
            seen.add(identity)
            key = (item.provider, item.provider_code)
            if key in aliases and aliases[key] != identity:
                raise InstrumentMasterError('供应商证券代码冲突')
            if any(r.symbol == item.symbol and r.instrument_id != identity for r in staged.values()):
                raise InstrumentMasterError('标准证券代码冲突')
            previous = staged.get(identity)
            if previous:
                if (previous.market, previous.asset_type, previous.listed_on) != (item.market, item.asset_type, item.listed_on):
                    raise InstrumentMasterError('证券身份属性冲突，需人工核对')
                if previous.name != item.name:
                    renamed.append(identity)
                if previous.delisted_on and item.delisted_on != previous.delisted_on:
                    raise InstrumentMasterError('不能清除已记录退市日期；需显式更正批次')
            else:
                added.append(identity)
            if item.delisted_on and (not previous or not previous.delisted_on):
                delisted.append(identity)
            staged[identity] = item
            aliases[key] = identity
        missing = sorted(r.instrument_id for r in self.records.values() if r.provider in {i.provider for i in incoming}
                         and r.instrument_id not in seen)
        change = dict(observed_on=observed_on, source=source, batch_id=batch_id, added=sorted(added),
            renamed=sorted(renamed), delisted=sorted(delisted), missing=missing,
            observations=[asdict(r) for r in incoming])
        self.records, self.aliases = staged, aliases
        self.changes.append(change)
        return copy.deepcopy(change)

    def listed_at(self, session):
        _date(session)
        return [r for _, r in sorted(self.records.items()) if r.listed_on <= session
                and (r.delisted_on is None or session < r.delisted_on)]

    def resolve_provider(self, provider, code):
        return self.records[self.aliases[(provider, code)]]

    def name_as_observed(self, instrument_id, session):
        _date(session)
        name = None
        for change in self.changes:
            if change['observed_on'] > session:
                break
            for row in change['observations']:
                if row['instrument_id'] == instrument_id:
                    name = row['name']
        return name

    def to_dict(self):
        return dict(schema_version='instrument-master.v1', records=[asdict(r) for _, r in sorted(self.records.items())],
            aliases=[dict(provider=p, code=c, instrument_id=i) for (p, c), i in sorted(self.aliases.items())],
            changes=copy.deepcopy(self.changes))

    def save(self, path):
        payload = self.to_dict()
        _atomic_write_json(Path(path), {**payload, 'checksum': identity_hash(payload)})

    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text(encoding='utf8'))
        checksum = payload.pop('checksum', None)
        if checksum != identity_hash(payload) or payload.get('schema_version') != 'instrument-master.v1':
            raise InstrumentMasterError('证券主表校验失败')
        result = cls()
        for change in payload['changes']:
            result.update(change['observations'], observed_on=change['observed_on'], source=change['source'], batch_id=change['batch_id'])
        if result.to_dict() != payload:
            raise InstrumentMasterError('证券主表历史与当前记录校验不一致')
        return result
