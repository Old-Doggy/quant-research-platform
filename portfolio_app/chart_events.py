"""Validate chart selections before they change a workspace's browsing state."""
from collections.abc import Mapping, Collection
from datetime import date
import hashlib
import json


def chart_identity(payload: Mapping) -> str:
    serialized = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
    return 'chart-' + hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:24]


def accept_chart_event(raw, *, chart_id: str, symbol: str, dates: Collection[str],
                       last_sequence: int = 0) -> dict | None:
    if not isinstance(raw, Mapping):
        return None
    if type(raw.get('version')) is not int or raw['version'] != 1:
        return None
    if raw.get('chart_id') != chart_id or raw.get('symbol') != symbol:
        return None
    if raw.get('source') not in {'kline', 'plotly'} or raw.get('kind') not in {'date', 'event'}:
        return None
    sequence = raw.get('sequence')
    if type(sequence) is not int or sequence <= last_sequence:
        return None
    selected_date = raw.get('date')
    if not isinstance(selected_date, str) or len(selected_date) != 10 or selected_date not in dates:
        return None
    try:
        date.fromisoformat(selected_date)
    except ValueError:
        return None
    return {key: raw[key] for key in ('version', 'source', 'chart_id', 'symbol', 'sequence', 'date', 'kind')}


def plotly_date_event(raw, *, chart_id: str, symbol: str, sequence: int) -> dict | None:
    if not isinstance(raw, Mapping):
        return None
    selection = raw.get('selection')
    if not isinstance(selection, Mapping):
        return None
    points = selection.get('points')
    if not isinstance(points, list) or not points or not isinstance(points[0], Mapping):
        return None
    value = points[0].get('x')
    if not isinstance(value, str):
        return None
    return dict(version=1, source='plotly', chart_id=chart_id, symbol=symbol,
                sequence=sequence, date=value[:10], kind='date')
