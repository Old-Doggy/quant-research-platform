from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_neutralization import (
    FactorNeutralizationError,
    NeutralizationUnavailable,
    NeutralizationSpec,
    neutralize_factors,
)


def neutralization_frame() -> pd.DataFrame:
    dates = pd.to_datetime(["2026-01-02"] * 6 + ["2026-01-05"] * 6)
    industry = ["tech", "tech", "bank", "bank", "retail", "retail"] * 2
    size = [1.0, 2.0, 1.5, 2.5, 1.2, 2.2] * 2
    factor = [
        10.0, 12.0, 20.0, 22.0, 30.0, 32.0,
        11.0, 13.0, 21.0, 23.0, 31.0, 33.0,
    ]
    return pd.DataFrame(
        {
            "trade_date": dates,
            "symbol": [f"S{i:02d}" for i in range(6)] * 2,
            "factor": factor,
            "second_factor": np.asarray(factor) * 2,
            "industry": industry,
            "size": size,
            "industry_available_at": dates - pd.Timedelta(days=1),
            "size_available_at": dates,
        }
    )


def spec(**overrides: object) -> NeutralizationSpec:
    values: dict[str, object] = {
        "neutralization_id": "demo.industry_size_neutral.v1",
        "version": "1.0.0",
        "industry_column": "industry",
        "industry_available_at_column": "industry_available_at",
        "size_column": "size",
        "size_available_at_column": "size_available_at",
        "size_transform": "none",
        "min_observations": 5,
    }
    values.update(overrides)
    return NeutralizationSpec(**values)


def test_cross_sectional_residuals_remove_industry_and_size_exposure() -> None:
    result = neutralize_factors(neutralization_frame(), ["factor"], spec())

    residual = result.data["factor_neutralized"]
    assert result.data.index.tolist() == list(range(12))
    assert result.diagnostics["dates_processed"] == 2
    assert result.diagnostics["rows_processed"] == 12
    assert result.diagnostics["controls"] == ["industry", "size"]
    assert residual.notna().all()
    assert result.data.groupby("trade_date")["factor_neutralized"].sum().abs().max() < 1e-9


def test_residual_matches_independent_ols_and_preserves_input() -> None:
    frame = neutralization_frame()
    original = frame.copy(deep=True)
    result = neutralize_factors(frame, ["factor"], spec())

    one_day = frame[frame["trade_date"] == pd.Timestamp("2026-01-02")]
    industry_matrix = pd.get_dummies(one_day["industry"], drop_first=True, dtype=float)
    design = np.column_stack([np.ones(len(one_day)), industry_matrix.to_numpy(), one_day[["size"]].to_numpy()])
    expected = one_day["factor"].to_numpy() - design @ np.linalg.lstsq(design, one_day["factor"].to_numpy(), rcond=None)[0]

    np.testing.assert_allclose(result.data.loc[one_day.index, "factor_neutralized"], expected, atol=1e-10)
    pd.testing.assert_frame_equal(frame, original)


def test_multiple_factors_get_independent_residual_columns() -> None:
    result = neutralize_factors(neutralization_frame(), ["factor", "second_factor"], spec())

    assert {"factor_neutralized", "second_factor_neutralized"}.issubset(result.data.columns)
    np.testing.assert_allclose(
        result.data["second_factor_neutralized"], result.data["factor_neutralized"] * 2, atol=1e-10
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"size_column": None, "size_available_at_column": None},
        {"industry_column": None, "industry_available_at_column": None},
    ],
)
def test_each_control_is_optional_when_its_pair_is_disabled(overrides: dict[str, object]) -> None:
    result = neutralize_factors(neutralization_frame(), ["factor"], spec(**overrides))

    assert result.data["factor_neutralized"].notna().all()
    assert result.diagnostics["controls"] == [
        control for control in (overrides.get("industry_column", "industry"), overrides.get("size_column", "size")) if control
    ]


def test_size_log1p_transform_is_applied_before_regression() -> None:
    frame = neutralization_frame()
    result = neutralize_factors(frame, ["factor"], spec(size_transform="log1p"))

    first_day = frame[frame["trade_date"] == pd.Timestamp("2026-01-02")]
    first_result = result.data.loc[first_day.index, "factor_neutralized"].to_numpy()
    assert np.isfinite(first_result).all()
    assert np.max(np.abs(first_result)) < 1.0


def test_pit_available_at_must_not_be_after_observation_date() -> None:
    frame = neutralization_frame()
    frame.loc[0, "size_available_at"] = pd.Timestamp("2026-01-03")

    with pytest.raises(FactorNeutralizationError, match="available_at"):
        neutralize_factors(frame, ["factor"], spec())


def test_missing_control_or_availability_field_is_explicitly_unavailable() -> None:
    with pytest.raises(NeutralizationUnavailable, match="industry"):
        neutralize_factors(neutralization_frame().drop(columns="industry"), ["factor"], spec())
    with pytest.raises(NeutralizationUnavailable, match="available"):
        neutralize_factors(neutralization_frame().drop(columns="size_available_at"), ["factor"], spec())


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda frame: frame.assign(size=1.0), "constant"),
        (lambda frame: frame.assign(size=frame["industry"].map({"tech": 1.0, "bank": 2.0, "retail": 3.0})), "collinear"),
    ],
)
def test_constant_or_collinear_controls_fail_with_explanation(mutator, message: str) -> None:
    frame = mutator(neutralization_frame())

    with pytest.raises(FactorNeutralizationError, match=message):
        neutralize_factors(frame, ["factor"], spec())


def test_insufficient_cross_section_is_explained() -> None:
    frame = neutralization_frame().iloc[[0, 1, 2, 4]].copy()

    with pytest.raises(FactorNeutralizationError, match="observations"):
        neutralize_factors(frame, ["factor"], spec(min_observations=5))


def test_cross_section_with_no_residual_degrees_of_freedom_is_rejected() -> None:
    frame = neutralization_frame().iloc[[0, 1, 2, 4]].copy()

    with pytest.raises(FactorNeutralizationError, match="observations"):
        neutralize_factors(frame, ["factor"], spec(min_observations=2))


def test_invalid_factor_identity_and_spec_are_rejected() -> None:
    with pytest.raises(ValueError, match="control"):
        NeutralizationSpec(
            neutralization_id="demo.bad",
            version="1.0.0",
            industry_column=None,
            industry_available_at_column=None,
            size_column=None,
            size_available_at_column=None,
            size_transform="none",
            min_observations=5,
        )
    with pytest.raises(FactorNeutralizationError, match="unknown"):
        neutralize_factors(neutralization_frame(), ["unknown_factor"], spec())


def test_result_is_serializable_and_reports_quality() -> None:
    result = neutralize_factors(neutralization_frame(), ["factor"], spec())

    payload = result.to_dict()

    assert payload["neutralization_id"] == "demo.industry_size_neutral.v1"
    assert payload["factor_columns"] == ["factor"]
    assert payload["diagnostics"]["rows_processed"] == 12
    assert "callable" not in repr(payload)
