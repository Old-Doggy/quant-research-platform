"""Session-owned, explicitly selected research input shared by workspaces."""
from __future__ import annotations

import pandas as pd

from .data import build_data_quality_report
from .research_result_cache import build_data_fingerprint


def activate_dataset(session, frame, *, dataset_id, version, source_kind, price_basis='unspecified', generation=1):
    if frame is None or frame.empty or build_data_quality_report(frame)['status'] != '通过':
        raise ValueError('dataset quality must pass before research')
    owned = frame.copy(deep=True)
    from dataclasses import asdict
    from .snapshot_contracts import build_frame_snapshot
    snapshot = build_frame_snapshot(owned, dataset_id=dataset_id, generation=generation, price_basis=price_basis)
    owned.attrs['snapshot'] = asdict(snapshot)
    metadata = dict(dataset_id=dataset_id, version=version, source_kind=source_kind,
                    price_basis=price_basis, fingerprint=build_data_fingerprint(owned),
                    snapshot_id=snapshot.snapshot_id, dataset_generation=generation)
    owned.attrs['research_dataset'] = metadata
    session['_registered_research_dataset'] = owned
    session['_use_registered_research_dataset'] = True
    return metadata


def selected_dataset(session, fallback):
    frame = session.get('_registered_research_dataset')
    if session.get('_use_registered_research_dataset') and isinstance(frame, pd.DataFrame):
        return frame.copy(deep=True)
    return fallback()


def dataset_metadata(frame):
    return dict(frame.attrs.get('research_dataset') or dict(
        dataset_id='seeded-demo', version='v001', source_kind='synthetic', price_basis='synthetic'))


def record_context(session, workspace, frame, *, source_kind=None, price_basis=None, period='1d', symbol=None):
    metadata = dataset_metadata(frame)
    if not frame.attrs.get('research_dataset') and source_kind in {'file_import', 'local_market'}:
        metadata.update(dataset_id=source_kind, version='未登记')
    session[f'_actual_context_{workspace}'] = dict(
        dataset_id=metadata['dataset_id'], version=metadata['version'],
        source_kind=source_kind or metadata['source_kind'],
        price_basis=price_basis or metadata['price_basis'], period=period,
        snapshot_id=metadata.get('snapshot_id'), dataset_generation=metadata.get('dataset_generation'),
        as_of=pd.to_datetime(frame.trade_date).max().date().isoformat(), symbol=symbol)
