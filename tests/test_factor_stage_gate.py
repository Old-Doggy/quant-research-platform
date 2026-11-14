from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_compute import BASIC_FACTOR_SPECS
from portfolio_app.factor_contracts import (
    ContractViolation,
    DisclosureStatus,
    FactorDirection,
    FactorSpec,
    FactorStatus,
)
from portfolio_app.factor_stage_gate import (
    FactorStageGateError,
    build_factor_stage_report,
)


def bars(rows: int = 80) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-02", periods=rows)
    close = pd.Series(np.linspace(10.0, 18.0, rows), dtype=float)
    return pd.DataFrame(
        {
            "trade_date": dates,
            "symbol": "AAA",
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "vol": np.arange(1000, 1000 + rows, dtype=float),
            "amount": close * np.arange(1000, 1000 + rows, dtype=float),
        }
    )


def test_public_factor_stage_report_passes_with_complete_contract_matrix() -> None:
    report = build_factor_stage_report(bars(), specs=BASIC_FACTOR_SPECS)

    assert report.status == "PASS"
    assert report.public_factor_count == 12
    assert report.computable_factor_ids == tuple(spec.factor_id for spec in BASIC_FACTOR_SPECS)
    assert report.unit_matrix["basic.return_20d"]["close"] == "currency_per_share"
    assert report.availability_matrix["basic.return_20d"]["available_at"] == "2026-10-29T00:00:00Z"
    assert report.missing_matrix["basic.return_20d"]["missing_count"] == 20
    assert report.missing_matrix["basic.return_20d"]["warmup_expected"] is True
    assert report.numerical_checks["all_outputs_present"] is True
    assert report.numerical_checks["finite_valid_values"] is True
    assert report.privacy_hits == ()


def test_public_summary_contains_contract_evidence_without_private_material() -> None:
    report = build_factor_stage_report(bars(), specs=BASIC_FACTOR_SPECS)

    payload = report.to_dict()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "PASS"
    assert len(payload["public_factors"]) == 12
    assert {"factor_id", "family", "input_units", "output_unit", "available_at", "missing_value_policy"}.issubset(payload["public_factors"][0])
    for forbidden in ("expression", "source_files", "parameters", "account", "C:\\", "/Users/"):
        assert forbidden not in serialized


def test_design_only_private_specs_are_not_publicly_computable() -> None:
    private = FactorSpec(
        factor_id="private.design.001",
        name="Private Design",
        version="1.0.0",
        family="private_family",
        input_fields=("close",),
        input_units={"close": "currency_per_share"},
        output_unit="return",
        direction=FactorDirection.TWO_SIDED,
        window=5,
        available_at="2026-10-29T00:00:00Z",
        price_convention="raw_ohlcv",
        missing_value_policy="preserve_nan",
        compute_status=FactorStatus.DESIGN_ONLY,
        disclosure_status=DisclosureStatus.PRIVATE,
        data_dependencies=("private_source",),
        asset_scope=("equity",),
    )

    report = build_factor_stage_report(bars(), specs=(*BASIC_FACTOR_SPECS, private))

    assert report.public_factor_count == 12
    assert "private.design.001" not in report.computable_factor_ids
    assert report.private_factor_count == 1
    assert "private.design.001" in report.status_counts[FactorStatus.DESIGN_ONLY.value]


def test_computable_spec_with_missing_input_is_a_gate_failure() -> None:
    broken = list(BASIC_FACTOR_SPECS)
    broken[0] = FactorSpec(
        **{**broken[0].to_dict(), "input_fields": ("close", "private_field"), "input_units": {"close": "currency_per_share", "private_field": "unknown"}}
    )

    with pytest.raises(FactorStageGateError, match="input"):
        build_factor_stage_report(bars(), specs=tuple(broken))


def test_public_factor_output_is_missing_when_required_data_is_absent() -> None:
    frame = bars().drop(columns="amount")
    specs = tuple(spec for spec in BASIC_FACTOR_SPECS if spec.factor_id == "basic.return_20d")

    report = build_factor_stage_report(frame, specs=specs)

    assert report.status == "PASS"
    assert report.numerical_checks["all_outputs_present"] is True
    assert report.missing_matrix["basic.return_20d"]["missing_count"] == 20


def test_public_factor_required_input_missing_blocks_stage_gate() -> None:
    frame = bars().drop(columns="close")
    specs = tuple(spec for spec in BASIC_FACTOR_SPECS if spec.factor_id == "basic.return_20d")

    with pytest.raises(FactorStageGateError, match="input"):
        build_factor_stage_report(frame, specs=specs)


def test_report_rejects_duplicate_public_factor_ids_and_invalid_status_claims() -> None:
    with pytest.raises(FactorStageGateError, match="duplicate"):
        build_factor_stage_report(bars(), specs=(*BASIC_FACTOR_SPECS, BASIC_FACTOR_SPECS[0]))

    invalid = list(BASIC_FACTOR_SPECS)
    invalid[0] = FactorSpec(**{**invalid[0].to_dict(), "compute_status": FactorStatus.COMPUTABLE, "input_fields": ("private_field",), "input_units": {"private_field": "unknown"}})
    with pytest.raises(FactorStageGateError, match="input"):
        build_factor_stage_report(bars(), specs=tuple(invalid))


def test_report_rejects_nonfinite_factor_values_and_future_availability() -> None:
    frame = bars()
    frame.loc[30, "close"] = np.inf
    with pytest.raises(FactorStageGateError, match="finite"):
        build_factor_stage_report(frame, specs=BASIC_FACTOR_SPECS)

    future = FactorSpec(**{**BASIC_FACTOR_SPECS[0].to_dict(), "available_at": "2027-01-01T00:00:00Z"})
    with pytest.raises(FactorStageGateError, match="availability"):
        build_factor_stage_report(bars(), specs=(future,))
