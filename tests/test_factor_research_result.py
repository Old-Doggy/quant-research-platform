from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_research_result import (
    FactorResearchResultError,
    build_factor_numerical_exit,
    build_factor_research_result,
)


def frame(*, signal: bool = True, constant: bool = False, empty: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-02", periods=8)
    rows: list[dict[str, object]] = []
    for day_index, date in enumerate(dates):
        for asset_index in range(4):
            factor = float(asset_index + day_index / 10)
            label = factor / 10 if signal else float((asset_index * 3 + day_index * 7) % 11) / 10
            if constant:
                factor = 1.0
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"A{asset_index}",
                    "factor": factor if not empty else np.nan,
                    "forward_label": label if not empty else np.nan,
                    "factor_available_at": date - pd.Timedelta(days=1),
                    "label_available_at": date + pd.Timedelta(days=1),
                }
            )
    return pd.DataFrame(rows)


def test_research_result_is_immutable_serializable_and_fingerprinted() -> None:
    result = build_factor_research_result(
        result_id="run-demo-001",
        data_fingerprint="data-abc",
        factor_fingerprint="factor-abc",
        label_fingerprint="label-abc",
        processing_fingerprint="processing-abc",
        engine_id="factor_engine",
        engine_version="1.0.0",
        diagnostics={"valid_sessions": 8, "quality_status": "READY"},
        payload={"ic_mean": 0.25, "warnings": []},
    )

    payload = result.to_dict()
    assert payload["schema_version"] == "factor-research-result.v1"
    assert payload["status"] == "COMPLETE"
    assert payload["fingerprints"]["data"] == "data-abc"
    assert result.to_json()
    with pytest.raises(TypeError):
        result.diagnostics["new_key"] = 1

    restored = result.from_dict(payload)
    assert restored.to_dict() == payload


def test_result_rejects_private_paths_executable_values_and_non_finite_output() -> None:
    with pytest.raises(FactorResearchResultError, match="private"):
        build_factor_research_result(
            result_id="run-1",
            data_fingerprint="data",
            factor_fingerprint="factor",
            label_fingerprint="label",
            processing_fingerprint="processing",
            engine_id="engine",
            engine_version="1",
            diagnostics={"source_file": "C:/private/input.csv"},
            payload={},
        )
    with pytest.raises(FactorResearchResultError, match="serializable"):
        build_factor_research_result(
            result_id="run-2",
            data_fingerprint="data",
            factor_fingerprint="factor",
            label_fingerprint="label",
            processing_fingerprint="processing",
            engine_id="engine",
            engine_version="1",
            diagnostics={"callback": lambda: None},
            payload={},
        )
    with pytest.raises(FactorResearchResultError, match="finite"):
        build_factor_research_result(
            result_id="run-3",
            data_fingerprint="data",
            factor_fingerprint="factor",
            label_fingerprint="label",
            processing_fingerprint="processing",
            engine_id="engine",
            engine_version="1",
            diagnostics={},
            payload={"ic_mean": np.nan},
        )


def test_numerical_exit_distinguishes_signal_noise_constant_and_empty() -> None:
    signal = build_factor_numerical_exit(frame(signal=True))
    noise = build_factor_numerical_exit(frame(signal=False))
    constant = build_factor_numerical_exit(frame(constant=True))
    empty = build_factor_numerical_exit(frame(empty=True))

    assert signal.status == "PASS"
    assert signal.signal_assessment == "known_signal_fixture"
    assert noise.status == "PASS"
    assert noise.signal_assessment == "weak_or_noise_fixture"
    assert constant.status == "FAIL"
    assert constant.failure_reason == "constant_factor"
    assert empty.status == "FAIL"
    assert empty.failure_reason == "no_valid_observations"


def test_numerical_exit_blocks_factor_future_availability_and_preserves_evidence() -> None:
    future = frame()
    future["factor_available_at"] = future["trade_date"] + pd.Timedelta(days=1)
    result = build_factor_numerical_exit(future)

    assert result.status == "FAIL"
    assert result.failure_reason == "future_factor_availability"
    assert result.evidence["future_factor_rows"] == len(future)
