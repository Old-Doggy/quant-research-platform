"""Explicit result tree codec; Parquet arrays and allowlisted Python value types."""
from dataclasses import fields, is_dataclass
from datetime import date, datetime
import hashlib
import json
import math
import re

import numpy as np
import pandas as pd


def _types():
    # Never import a module/class named by a saved document.
    from .research import SingleStockResearchResult
    from .portfolio import PortfolioResearchResult
    from .portfolio_workspace import PortfolioWorkspaceResult
    from .portfolio_accounting import PortfolioAccountingResult
    from .temporal_contracts import SessionCalendar
    from .snapshot_contracts import SnapshotReference
    from .corporate_actions import CorporateAction
    return {c.__name__: c for c in (SingleStockResearchResult, PortfolioResearchResult,
        PortfolioWorkspaceResult, PortfolioAccountingResult, SessionCalendar, SnapshotReference, CorporateAction)}


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class ResultCodec:
    def __init__(self, directory):
        self.directory = directory
        self.files = {}

    def encode(self, value, depth=0):
        if depth > 60:
            raise ValueError('结果嵌套层数过多')
        child = lambda v: self.encode(v, depth + 1)
        if value is None or type(value) in (str, bool, int):
            return ['scalar', value]
        if value is pd.NA: return ['missing', 'NA']
        if value is pd.NaT: return ['missing', 'NaT']
        if isinstance(value, np.generic): return child(value.item())
        if isinstance(value, float):
            return ['scalar', value] if math.isfinite(value) else ['nonfinite',
                'nan' if math.isnan(value) else ('inf' if value > 0 else '-inf')]
        if isinstance(value, pd.Timestamp): return ['timestamp', value.isoformat()]
        if isinstance(value, datetime): return ['datetime', value.isoformat()]
        if isinstance(value, date): return ['date', value.isoformat()]
        if isinstance(value, (pd.DataFrame, pd.Series)):
            name = f'array-{len(self.files):04d}.parquet'
            # Reserve before recursively encoding attrs that may themselves contain arrays.
            self.files[name] = None
            attrs = child(value.attrs)
            owned = value.copy(deep=True)
            owned.attrs = {}
            frame = owned.to_frame(name='value') if isinstance(value, pd.Series) else owned
            object_columns = []
            for position in range(len(frame.columns)):
                if frame.iloc[:, position].dtype == object:
                    object_columns.append(position)
                    encoded = [json.dumps(child(v), ensure_ascii=False, allow_nan=False) for v in frame.iloc[:, position]]
                    frame.isetitem(position, pd.Series(encoded, index=frame.index, dtype=object))
            # Own the handle so Arrow errors close it before Windows staging cleanup.
            with (self.directory / name).open('w+b') as stream:
                frame.to_parquet(stream, index=True)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            self.files[name] = file_hash(self.directory / name)
            return ['series' if isinstance(value, pd.Series) else 'frame',
                name, attrs, child(value.name) if isinstance(value, pd.Series) else None, object_columns]
        if is_dataclass(value) and type(value).__name__ in _types() and _types()[type(value).__name__] is type(value):
            return ['record', type(value).__name__, {f.name: child(getattr(value, f.name)) for f in fields(value)}]
        if isinstance(value, dict): return ['mapping', [[child(k), child(v)] for k, v in value.items()]]
        if isinstance(value, (tuple, list)):
            return ['tuple' if isinstance(value, tuple) else 'list', [child(v) for v in value]]
        raise TypeError('结果包含尚未支持的保存类型')

    def decode(self, node, depth=0):
        if depth > 60 or not isinstance(node, list) or not node:
            raise ValueError('结果结构无效')
        child = lambda v: self.decode(v, depth + 1)
        kind = node[0]
        if kind == 'scalar' and len(node) == 2 and (node[1] is None or type(node[1]) in (str, bool, int, float)):
            return node[1]
        if kind == 'nonfinite' and len(node) == 2 and node[1] in ('nan', 'inf', '-inf'): return float(node[1])
        if kind == 'missing' and len(node) == 2 and node[1] in ('NA', 'NaT'): return pd.NA if node[1] == 'NA' else pd.NaT
        if kind in ('timestamp', 'datetime', 'date') and len(node) == 2:
            return {'timestamp': pd.Timestamp, 'datetime': datetime.fromisoformat, 'date': date.fromisoformat}[kind](node[1])
        if kind == 'mapping' and len(node) == 2: return {child(k): child(v) for k, v in node[1]}
        if kind in ('tuple', 'list') and len(node) == 2:
            result = [child(v) for v in node[1]]
            return tuple(result) if kind == 'tuple' else result
        if kind == 'record' and len(node) == 3 and node[1] in _types():
            return _types()[node[1]](**{k: child(v) for k, v in node[2].items()})
        if kind in ('frame', 'series') and len(node) in (4, 5):
            name = node[1]
            if not isinstance(name, str) or not re.fullmatch(r'array-\d{4,}\.parquet', name) or name not in self.files:
                raise ValueError('结果数组引用无效')
            if file_hash(self.directory / name) != self.files[name]:
                raise ValueError('结果数组校验失败')
            frame = pd.read_parquet(self.directory / name)
            for position in node[4] if len(node) == 5 else []:
                decoded = [child(json.loads(v)) for v in frame.iloc[:, position]]
                frame.isetitem(position, pd.Series(decoded, index=frame.index, dtype=object))
            value = frame.iloc[:, 0].rename(child(node[3])) if kind == 'series' else frame
            value.attrs = child(node[2])
            return value
        raise ValueError('结果类型或结构尚未支持')
