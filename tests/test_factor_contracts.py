from __future__ import annotations

import pytest

from portfolio_app.factor_contracts import (
    ContractViolation,
    DisclosureStatus,
    FactorDirection,
    FactorSpec,
    FactorStatus,
    LabelSpec,
    ProcessingSpec,
)


def make_factor(**overrides: object) -> FactorSpec:
    values: dict[str, object] = {
        "factor_id": "demo.momentum.20d",
        "name": "20D Momentum",
        "version": "1.0.0",
        "family": "price_momentum",
        "input_fields": ("close",),
        "input_units": {"close": "price"},
        "output_unit": "return",
        "direction": FactorDirection.HIGHER_IS_BETTER,
        "window": 20,
        "available_at": "2026-01-01T00:00:00Z",
        "price_convention": "raw_close",
        "missing_value_policy": "preserve_nan",
        "compute_status": FactorStatus.COMPUTABLE,
        "disclosure_status": DisclosureStatus.PUBLIC_DEMO,
        "data_dependencies": ("demo_daily_ohlcv",),
        "asset_scope": ("equity",),
    }
    values.update(overrides)
    return FactorSpec(**values)


def test_factor_spec_serializes_required_semantics() -> None:
    payload = make_factor().to_dict()

    assert payload["factor_id"] == "demo.momentum.20d"
    assert payload["version"] == "1.0.0"
    assert payload["direction"] == "higher_is_better"
    assert payload["compute_status"] == "computable"
    assert payload["disclosure_status"] == "public_demo"
    assert payload["input_units"] == {"close": "price"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", ""),
        ("input_units", {}),
        ("output_unit", ""),
        ("available_at", ""),
        ("window", 0),
        ("window", -5),
        ("direction", "sideways"),
    ],
)
def test_factor_spec_rejects_missing_or_invalid_contract_values(field: str, value: object) -> None:
    with pytest.raises(ContractViolation):
        make_factor(**{field: value})


def test_factor_spec_rejects_availability_before_observation() -> None:
    with pytest.raises(ContractViolation, match="available_at"):
        make_factor(
            available_at="2025-12-31T23:59:59Z",
            observation_time="2026-01-01T00:00:00Z",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "C:\\private\\factor.py"),
        ("data_dependencies", ("__import__('os')",)),
        ("input_units", {"close": "price", "expression": "secret"}),
    ],
)
def test_factor_spec_rejects_paths_code_and_private_fields(field: str, value: object) -> None:
    with pytest.raises(ContractViolation):
        make_factor(**{field: value})


def test_factor_spec_rejects_non_text_or_executable_dependencies() -> None:
    with pytest.raises(ContractViolation):
        make_factor(input_fields=("close", object()))
    with pytest.raises(ContractViolation):
        make_factor(data_dependencies=(lambda: None,))


def test_processing_spec_requires_explicit_training_fit_policy() -> None:
    spec = ProcessingSpec(
        processing_id="demo.clean.v1",
        version="1.0.0",
        missing_value_policy="drop_row",
        winsorize_lower=0.01,
        winsorize_upper=0.99,
        standardization="zscore",
        axis="cross_sectional",
        fit_scope="training_period",
        fit_train_only=True,
    )

    assert spec.to_dict()["fit_train_only"] is True

    with pytest.raises(ContractViolation):
        ProcessingSpec(
            processing_id="demo.clean.v1",
            version="1.0.0",
            missing_value_policy="drop_row",
            winsorize_lower=0.99,
            winsorize_upper=0.01,
            standardization="zscore",
            axis="cross_sectional",
            fit_scope="training_period",
            fit_train_only=True,
        )


def test_label_spec_uses_sessions_and_preserves_incomplete_tail() -> None:
    spec = LabelSpec(
        label_id="demo.forward_return",
        version="1.0.0",
        prediction_direction="forward_return",
        horizon_sessions=5,
        anchor="observation_close",
        return_convention="close_to_close",
        tail_policy="preserve_missing",
        overlapping=True,
        available_at_policy="future_session_close",
    )

    payload = spec.to_dict()
    assert payload["horizon_sessions"] == 5
    assert payload["tail_policy"] == "preserve_missing"
    assert payload["overlapping"] is True

    with pytest.raises(ContractViolation):
        LabelSpec(
            label_id="demo.bad",
            version="1.0.0",
            prediction_direction="forward_return",
            horizon_sessions=0,
            anchor="observation_close",
            return_convention="close_to_close",
            tail_policy="preserve_missing",
            overlapping=False,
            available_at_policy="future_session_close",
        )


@pytest.mark.parametrize("field,value", [("anchor", "calendar_day"), ("version", "")])
def test_label_spec_rejects_unsupported_anchor_and_missing_version(field: str, value: object) -> None:
    values: dict[str, object] = {
        "label_id": "demo.forward_return",
        "version": "1.0.0",
        "prediction_direction": "forward_return",
        "horizon_sessions": 5,
        "anchor": "observation_close",
        "return_convention": "close_to_close",
        "tail_policy": "preserve_missing",
        "overlapping": True,
        "available_at_policy": "future_session_close",
    }
    values[field] = value
    with pytest.raises(ContractViolation):
        LabelSpec(**values)
