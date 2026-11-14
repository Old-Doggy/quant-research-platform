from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
from pathlib import Path
import platform
import uuid
import zipfile

import pandas as pd

from portfolio_app.data import OPTIONAL_COLUMNS, REQUIRED_PRICE_COLUMNS
from portfolio_app.research import run_portfolio_research, run_single_stock_research
from portfolio_app.strategies import normalize_strategy_params
from .research_integrity import audit_research_input
from .research_manifest import build_run_manifest, valid_manifest


MAX_ARCHIVE_BYTES = 100_000_000


def _engine_hash() -> str:
    root = Path(__file__).resolve().parent
    return hashlib.sha256(b"".join((root / name).read_bytes() for name in
                                  ("research.py", "backtest.py", "strategies.py", "data.py"))).hexdigest()


def _csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, float_format="%.17g").encode("utf-8")


def _read_csv(data: bytes) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(data), dtype={"symbol": str, "ts_code": str}, float_precision="round_trip")
    if "trade_date" in frame:
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    return frame


def _run(frame: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, dict]:
    mode = spec.get("mode")
    if mode not in {"single", "portfolio"}:
        raise ValueError("unknown experiment mode")
    symbols = spec["symbols"]
    if not isinstance(symbols, list) or not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("experiment requires distinct symbols")
    common = {"strategy_key": spec["strategy_key"], "params": normalize_strategy_params(spec["strategy_key"], spec.get("params")),
              "transaction_cost": float(spec["transaction_cost"])}
    if mode == "single":
        result = run_single_stock_research(frame.loc[frame["symbol"].eq(symbols[0])],
                                          start_date=spec.get("start_date"), end_date=spec.get("end_date"), **common)
        return result.frame, result.metrics
    frames = {}
    for symbol in symbols:
        leg = frame.loc[frame["symbol"].eq(symbol)].copy()
        if spec.get("start_date"):
            leg = leg.loc[leg["trade_date"] >= pd.Timestamp(spec["start_date"])]
        if spec.get("end_date"):
            leg = leg.loc[leg["trade_date"] <= pd.Timestamp(spec["end_date"])]
        frames[symbol] = leg.tail(int(spec.get("lookback", len(leg))))
        if frames[symbol].empty:
            raise ValueError("experiment contains an empty portfolio leg")
    result = run_portfolio_research(frames, target_weights=spec["weights"], cash_weight=spec.get("cash_weight", 0), **common)
    return result.frame, result.diagnostics["metrics"]


def build_experiment(frame: pd.DataFrame, spec: dict, *, name: str = "Research run") -> bytes:
    """Create a local-only reproducible archive; never include unknown source columns."""
    audit_research_input(frame)
    allowed = set(REQUIRED_PRICE_COLUMNS) | set(OPTIONAL_COLUMNS) | {"symbol", "return"}
    source = frame.loc[frame["symbol"].isin(spec["symbols"]), [key for key in frame.columns if key in allowed]].copy()
    source = source.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)
    data = _csv(source)
    # Execute the serialized input, so the archive is the exact replay boundary.
    result, metrics = _run(_read_csv(data), spec)
    result = result[[key for key in ("trade_date", "equity", "benchmark_equity", "drawdown", "strategy_return", "daily_return") if key in result]]
    result_data = _csv(result)
    manifest = {
        "schema": 1, "id": uuid.uuid4().hex, "name": str(name).strip()[:100] or "Research run",
        "created_at": datetime.now(timezone.utc).isoformat(), "disclosure_mode": "private_local",
        "execution_model": "next_day_close" if spec['mode'] == 'single' else "lagged_signal_close_to_close_proxy",
        "engine_sha256": _engine_hash(), "python_version": platform.python_version(), "pandas_version": pd.__version__,
        "data_sha256": hashlib.sha256(data).hexdigest(), "result_sha256": hashlib.sha256(result_data).hexdigest(),
        "spec": spec, "metrics": metrics,
        "limitations": ["Local archive contains source market data; do not publish without reviewing redistribution rights.",
                        "Offline next-session simulation or explicit legacy proxy; not actual exchange fills."],
    }
    manifest['run_manifest'] = build_run_manifest(frame=_read_csv(data),
        engine_id='experiment-close-proxy.v1', features={'strategy': spec['strategy_key']},
        labels={'kind': 'none'}, execution={'model': manifest['execution_model'], 'mode': spec['mode']},
        parameters=spec, cost={'turnover': spec['transaction_cost']},
        evaluation='fixed_parameter', processing={'version': 1,
            'evaluation_period': {'start': str(result.trade_date.min().date()),
                                  'end': str(result.trade_date.max().date())}})
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2))
        out.writestr("data.csv", data)
        out.writestr("result.csv", result_data)
    return archive.getvalue()


def open_experiment(archive: bytes) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("experiment archive is too large")
    with zipfile.ZipFile(BytesIO(archive)) as source:
        if sorted(source.namelist()) != ["data.csv", "manifest.json", "result.csv"]:
            raise ValueError("unexpected experiment archive members")
        if sum(info.file_size for info in source.infolist()) > MAX_ARCHIVE_BYTES:
            raise ValueError("expanded experiment archive is too large")
        manifest = json.loads(source.read("manifest.json"))
        data, result = source.read("data.csv"), source.read("result.csv")
    if manifest.get("schema") != 1 or manifest.get("disclosure_mode") != "private_local":
        raise ValueError("unsupported experiment contract")
    if hashlib.sha256(data).hexdigest() != manifest["data_sha256"] or hashlib.sha256(result).hexdigest() != manifest["result_sha256"]:
        raise ValueError("experiment checksum mismatch")
    return manifest, _read_csv(data), _read_csv(result)


def reproduce_experiment(archive: bytes) -> pd.DataFrame:
    manifest, data, expected = open_experiment(archive)
    if manifest["engine_sha256"] != _engine_hash():
        raise ValueError("计算版本已变化，不能声称按原版本复现")
    provenance = manifest.get('run_manifest')
    if provenance is not None:
        if not valid_manifest(provenance):
            raise ValueError('运行清单校验失败')
        current = build_run_manifest(frame=data, engine_id='experiment-close-proxy.v1',
            features={}, labels={}, execution={}, parameters={}, cost={}, evaluation={}, processing={})
        if current['hashes']['engine'] != provenance['hashes']['engine'] or current['runtime'] != provenance['runtime']:
            raise ValueError('引擎或依赖环境已变化，不能声称按原版本复现')
    result, _ = _run(data, manifest["spec"])
    return result[list(expected.columns)].reset_index(drop=True)


def save_experiment(root: Path, archive: bytes) -> Path:
    manifest, _, _ = open_experiment(archive)
    identifier = str(manifest["id"])
    if len(identifier) != 32 or any(character not in "0123456789abcdef" for character in identifier):
        raise ValueError("invalid experiment id")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{identifier}.zip"
    with destination.open("xb") as output:
        output.write(archive)
    return destination
