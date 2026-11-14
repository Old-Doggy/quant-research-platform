"""Checksum protected local archives and allowlisted public summaries."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .portfolio_workspace import ENGINE, LIMITATIONS


SUMMARY_FIELDS = ("total_return", "max_drawdown", "total_cost", "fills", "rejected", "sharpe")
PUBLIC_ENGINES = frozenset({"portfolio-workspace.v1", ENGINE})


def _clean(value: Any):
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _checksum(mode, payload):
    return hashlib.sha256(_canonical(dict(schema_version="portfolio-archive.v1", mode=mode, payload=payload))).hexdigest()


def create_portfolio_archive(result, *, mode):
    if mode not in {"private_local", "public_redacted"}:
        raise ValueError("unsupported archive mode")
    metrics = {key: result.metrics.get(key) for key in SUMMARY_FIELDS}
    payload = dict(engine=ENGINE, limitations=list(LIMITATIONS), outputs=dict(metrics=metrics))
    if mode == "private_local":
        payload.update(inputs=result.inputs, config=result.config)
        payload["outputs"].update(
            ledger=result.accounting.ledger.to_dict("records"), positions=result.positions.to_dict("records"),
            orders=result.orders, fills=result.fills,
            symbols=result.accounting.symbol_contribution.to_dict("records"),
            legs=result.accounting.leg_contribution.to_dict("records"),
            factors=result.accounting.factor_contribution.to_dict("records"),
            risk=result.accounting.risk, diagnostics=result.accounting.diagnostics)
    payload = json.loads(_canonical(_clean(payload)))
    archive = dict(schema_version="portfolio-archive.v1", mode=mode, payload=payload, checksum=_checksum(mode, payload))
    return load_portfolio_archive(archive)


def load_portfolio_archive(archive):
    if not isinstance(archive, dict) or archive.get("schema_version") != "portfolio-archive.v1":
        raise ValueError("invalid archive schema")
    mode = archive.get("mode")
    if mode not in {"private_local", "public_redacted"} or not isinstance(archive.get("payload"), dict):
        raise ValueError("invalid archive mode or payload")
    payload = archive["payload"]
    if archive.get("checksum") != _checksum(mode, payload):
        raise ValueError("archive checksum mismatch")
    if mode == "public_redacted":
        if set(payload) != {"engine", "limitations", "outputs"} or set(payload["outputs"]) != {"metrics"}:
            raise ValueError("public archive contains non-allowlisted fields")
        if set(payload["outputs"]["metrics"]) != set(SUMMARY_FIELDS):
            raise ValueError("public archive contains non-allowlisted metrics")
        for value in payload["outputs"]["metrics"].values():
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise ValueError("public metric must be finite numeric or null")
        if payload["engine"] not in PUBLIC_ENGINES or payload["limitations"] != list(LIMITATIONS):
            raise ValueError("public archive metadata is invalid")
    return json.loads(_canonical(archive))
