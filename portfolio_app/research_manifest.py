"""Versioned local provenance and fail-closed comparison of research runs."""
from __future__ import annotations

import copy
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import re

import pandas as pd


SCHEMA = 'run-manifest.v1'
_ENGINE_FILES = ('research.py', 'backtest.py', 'strategies.py', 'indicators.py',
                 'single_stock_performance.py', 'offline_performance.py',
                 'factor_compute.py', 'factor_labels.py', 'factor_analysis.py',
                 'factor_group_analysis.py', 'factor_stability.py', 'factor_research_job.py',
                 'portfolio_workspace.py', 'portfolio_accounting.py', 'portfolio_orders.py',
                 'portfolio_recipe.py', 'offline_execution.py', 'offline_ledger.py',
                 'offline_market_rules.py', 'validation.py', 'research_integrity.py',
                 'research_manifest.py', 'data.py', 'indicator_math.py',
                 'factor_contracts.py', 'factor_workspace.py', 'factor_processing.py', 'strategy_catalog.py', 'return_series.py',
                 'corporate_actions.py', 'entitlement_ledger.py',
                 'instrument_rules.py',
                 'market_sessions.py',
                 'factor_research_result.py', 'portfolio.py', 'portfolio_attribution.py',
                 'portfolio_risk.py', 'performance_metrics.py', 'factor_rank_strategy.py')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def semantic_hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def frame_hash(frame):
    data = frame.reset_index(drop=True).reindex(sorted(frame.columns), axis=1)
    schema = [(str(c), str(data[c].dtype)) for c in data]
    digest = hashlib.sha256(_json(schema).encode())
    digest.update(pd.util.hash_pandas_object(data, index=False).to_numpy().tobytes())
    return digest.hexdigest()


def _runtime():
    libraries = {}
    for name in ('numpy', 'pandas', 'streamlit', 'plotly'):
        try:
            libraries[name] = version(name)
        except PackageNotFoundError:
            libraries[name] = 'not-installed'
    return dict(python=platform.python_version(), libraries=libraries)


def build_run_manifest(*, frame, engine_id, features, labels, execution, parameters,
                       cost, evaluation, processing):
    """Hash exact supplied input and definitions; never serialize raw parameters/paths.

    Input history includes warm-up; evaluation period may be supplied separately in
    processing. The manifest is local-only even when the input happens to be a demo.
    """
    if frame.empty or 'trade_date' not in frame or not engine_id:
        raise ValueError('manifest requires dated input and an engine')
    dates = pd.to_datetime(frame.trade_date, errors='raise')
    processing = dict(processing)
    if frame.attrs.get('research_dataset'):
        processing['dataset_version'] = frame.attrs['research_dataset']
    runtime = _runtime()
    root = Path(__file__).parent
    engine_sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                      for name in _ENGINE_FILES if (root / name).is_file()}
    hashes = dict(data=semantic_hash(dict(values=frame_hash(frame),
                  timing=frame.attrs.get('research_timing', {}))), feature=semantic_hash(features),
                  label=semantic_hash(labels), execution=semantic_hash(execution),
                  parameters=semantic_hash(parameters), processing=semantic_hash(processing),
                  engine=semantic_hash(dict(identity=engine_id, sources=engine_sources)))
    period = processing.get('evaluation_period') or dict(
        start=dates.min().isoformat(), end=dates.max().isoformat())
    basis = dict(data=hashes['data'], period=period, cost=semantic_hash(cost),
                 engine=hashes['engine'], runtime=semantic_hash(runtime),
                 label=hashes['label'], execution=hashes['execution'],
                 processing=hashes['processing'], evaluation=semantic_hash(evaluation),
                 universe=semantic_hash(sorted(frame.symbol.astype(str).unique()) if 'symbol' in frame else []))
    payload = dict(schema_version=SCHEMA, disclosure='private_local', runtime=runtime,
                   engine=dict(identity=engine_id, sources=[dict(module=name, sha256=digest)
                       for name, digest in engine_sources.items()]),
                   hashes=hashes, basis=basis)
    return {**payload, 'checksum': semantic_hash(payload)}


def valid_manifest(manifest):
    try:
        payload = {key: value for key, value in manifest.items() if key != 'checksum'}
        return (manifest.get('schema_version') == SCHEMA and manifest.get('disclosure') == 'private_local'
                and set(manifest['basis']) == {'data', 'period', 'cost', 'engine', 'runtime',
                    'label', 'execution', 'processing', 'evaluation', 'universe'}
                and set(manifest['hashes']) == {'data', 'feature', 'label', 'execution', 'parameters', 'processing', 'engine'}
                and all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v)
                        for v in manifest['hashes'].values())
                and manifest['runtime'].get('python')
                and all(value is not None for value in manifest['basis'].values())
                and manifest.get('checksum') == semantic_hash(payload))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def export_run_manifest(manifest, *, mode, local_access):
    if not valid_manifest(manifest):
        raise ValueError('invalid run manifest')
    if mode == 'private_local':
        if not local_access:
            raise PermissionError('local manifest access required')
        return copy.deepcopy(manifest)
    if mode not in {'public_demo', 'public_redacted'}:
        raise ValueError('unsupported disclosure mode')
    # A private fingerprint can reveal membership or low-entropy parameter values.
    return dict(schema_version=SCHEMA, disclosure=mode,
                reproducibility='Local provenance retained; public fingerprints withheld.')


def compare_run_manifests(manifests):
    if not manifests:
        raise ValueError('select at least one run')
    fields = ('data', 'period', 'cost', 'engine', 'runtime', 'label', 'execution',
              'processing', 'evaluation', 'universe')
    valid = [valid_manifest(m) for m in manifests]
    differences = []
    if not all(valid):
        differences.append(dict(field='manifest', reason='缺少完整清单、仅有脱敏摘要或校验失败'))
    else:
        for field in fields:
            values = [m['basis'][field] for m in manifests]
            if any(value != values[0] for value in values[1:]):
                differences.append(dict(field=field, reason='比较口径不一致', values=values))
    return dict(ranking_allowed=all(valid) and not differences,
                differences=differences,
                runs=[dict(index=i + 1, verified=ok,
                    basis=copy.deepcopy(m['basis']) if ok else None) for i, (m, ok) in enumerate(zip(manifests, valid))])
