"""Stable snapshot identities; completeness is a declaration, never inferred."""
from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import re


def _plain(value):
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def identity_hash(value):
    return hashlib.sha256(json.dumps(_plain(value), ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def frame_provenance(frame):
    fields = ('research_timing', 'research_dataset', 'snapshot', 'corporate_actions',
              'instrument_rules', 'session_calendar', 'return_contract', 'action_coverage', 'field_units', 'normalization')
    return _plain({k: frame.attrs[k] for k in fields if k in frame.attrs})


@dataclass(frozen=True)
class SnapshotReference:
    snapshot_id: str
    dataset_id: str
    generation: int
    content_sha256: str
    price_basis: str
    completeness: str = 'unverified'
    schema_version: str = 'snapshot.v1'

    def __post_init__(self):
        if (not isinstance(self.dataset_id, str) or not self.dataset_id.strip()
                or type(self.generation) is not int or self.generation < 1
                or not isinstance(self.content_sha256, str) or not re.fullmatch('[a-f0-9]{64}', self.content_sha256)
                or self.price_basis not in {'raw', 'raw_ohlcv', 'qfq', 'hfq', 'synthetic', 'unspecified', 'unknown'}
                or self.completeness not in {'unverified', 'partial', 'complete'}
                or self.schema_version != 'snapshot.v1'):
            raise ValueError('snapshot reference is invalid')
        payload = asdict(self)
        payload.pop('snapshot_id')
        if self.snapshot_id != 'snapshot-' + identity_hash(payload):
            raise ValueError('snapshot identity does not match its content')

    @classmethod
    def from_dict(cls, value):
        try:
            return cls(**value)
        except TypeError as exc:
            raise ValueError('snapshot reference fields are invalid') from exc


def snapshot_from_hash(content_sha256, *, dataset_id, generation, price_basis, completeness='unverified'):
    payload = dict(dataset_id=dataset_id, generation=generation, content_sha256=content_sha256,
        price_basis=price_basis, completeness=completeness, schema_version='snapshot.v1')
    return SnapshotReference(snapshot_id='snapshot-' + identity_hash(payload), **payload)


def build_frame_snapshot(frame, *, dataset_id, generation, price_basis, completeness='unverified'):
    from .research_result_cache import build_data_fingerprint
    owned = frame.copy(deep=True)
    # A new reference must not depend recursively on a previous reference.
    owned.attrs.pop('snapshot', None)
    owned.attrs.pop('research_dataset', None)
    return snapshot_from_hash(build_data_fingerprint(owned).removeprefix('data-'),
        dataset_id=dataset_id, generation=generation, price_basis=price_basis, completeness=completeness)
