"""Content-keyed local price reads; a path or timestamp alone is not a version."""
from dataclasses import asdict
import hashlib
import io
from pathlib import Path

import streamlit as st

from .data import read_market_file
from .snapshot_contracts import snapshot_from_hash


@st.cache_data(show_spinner=False, max_entries=8)
def _read_content(payload, name, basis, revision):
    source = io.BytesIO(payload)
    source.name = name
    frame = read_market_file(source)
    snapshot = snapshot_from_hash(hashlib.sha256(payload).hexdigest(), dataset_id='local_market',
        generation=1, price_basis=basis)
    frame.attrs['snapshot'] = asdict(snapshot)
    frame.attrs['research_dataset'] = dict(dataset_id='local_market', version=snapshot.snapshot_id,
        source_kind='local_market', price_basis=basis, snapshot_id=snapshot.snapshot_id,
        dataset_generation=snapshot.generation)
    return frame


def cached_local_symbol(data_root, symbol, adjusted):
    if not isinstance(symbol, str) or any(c in symbol for c in '/\\:') or symbol in {'.', '..'}:
        raise ValueError('invalid symbol')
    if adjusted not in {'raw', 'qfq', 'hfq'}:
        raise ValueError('unknown price basis')
    path = Path(data_root) / f'daily_{adjusted}_merged' / f'{symbol}.parquet'
    # Read exactly once; the bytes used as the key are also the bytes parsed.
    payload = path.read_bytes()
    root = Path(__file__).parent
    revision = hashlib.sha256(b''.join((root / name).read_bytes() for name in
        ('data.py', 'data_catalog.py', 'market_file_cache.py', 'snapshot_contracts.py'))).hexdigest()
    return _read_content(payload, path.name, adjusted, revision)
