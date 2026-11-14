from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_contracts import ProcessingSpec
from portfolio_app.factor_processing import (
    FactorProcessingError,
    apply_factor_processing,
    fit_factor_processing,
)


def factor_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-02", periods=4)
    return pd.DataFrame(
        {
            "trade_date": list(dates) * 3,
            "symbol": ["AAA"] * 4 + ["BBB"] * 4 + ["CCC"] * 4,
            "factor": [1.0, 2.0, np.nan, 100.0, 2.0, 4.0, 6.0, 8.0, 3.0, 5.0, 7.0, 9.0],
            "other": np.arange(12, dtype=float),
        }
    )


def spec(**overrides: object) -> ProcessingSpec:
    values: dict[str, object] = {
        "processing_id": "demo.factor.clean.v1",
        "version": "1.0.0",
        "missing_value_policy": "drop_row",
        "winsorize_lower": 0.25,
        "winsorize_upper": 0.75,
        "standardization": "zscore",
        "axis": "cross_sectional",
        "fit_scope": "training_period",
        "fit_train_only": True,
    }
    values.update(overrides)
    return ProcessingSpec(**values)


def test_cross_sectional_processing_fits_per_session_and_reports_coverage() -> None:
    frame = factor_frame()
    fitted = fit_factor_processing(frame, ["factor"], spec(), training_end="2026-01-05")

    result = apply_factor_processing(fitted, frame)

    assert result.data.loc[result.data["trade_date"] == pd.Timestamp("2026-01-05"), "factor"].notna().all()
    assert result.data["factor"].mean() == pytest.approx(0.0, abs=1e-12)
    assert result.quality["input_rows"] == 12
    assert result.quality["output_rows"] == 11
    assert result.quality["missing_rows"] == 1
    assert result.quality["coverage_ratio"] == pytest.approx(11 / 12)
    assert result.quality["fit_rows"] == 6


def test_time_series_processing_fits_only_training_period_and_does_not_leak_future_outlier() -> None:
    frame = factor_frame()
    processing = spec(axis="time_series", standardization="zscore", winsorize_lower=None, winsorize_upper=None, missing_value_policy="preserve_nan")
    fitted = fit_factor_processing(frame, ["factor"], processing, training_end="2026-01-05")
    baseline = apply_factor_processing(fitted, frame).data

    changed = frame.copy()
    changed.loc[changed["trade_date"] > pd.Timestamp("2026-01-05"), "factor"] = 1_000_000.0
    changed_result = apply_factor_processing(fitted, changed).data

    train_rows = frame["trade_date"] <= pd.Timestamp("2026-01-05")
    pd.testing.assert_series_equal(
        baseline.loc[train_rows, "factor"].reset_index(drop=True),
        changed_result.loc[train_rows, "factor"].reset_index(drop=True),
    )
    assert changed_result.loc[changed_result["trade_date"] > pd.Timestamp("2026-01-05"), "factor"].max() > 1_000.0


def test_time_series_rank_is_rejected_instead_of_using_future_observations() -> None:
    processing = spec(axis="time_series", standardization="rank", winsorize_lower=None, winsorize_upper=None)

    with pytest.raises(FactorProcessingError, match="rank"):
        fit_factor_processing(factor_frame(), ["factor"], processing, training_end="2026-01-05")


def test_cross_sectional_standardization_uses_current_session_only() -> None:
    frame = factor_frame().drop(columns="other")
    processing = spec(winsorize_lower=None, winsorize_upper=None, standardization="rank")
    fitted = fit_factor_processing(frame, ["factor"], processing, training_end="2026-01-05")
    result = apply_factor_processing(fitted, frame).data

    first_session = result[result["trade_date"] == pd.Timestamp("2026-01-02")]["factor"]
    assert first_session.tolist() == pytest.approx([0.0, 0.5, 1.0])


def test_processing_preserves_input_and_supports_nan_retention_with_explicit_quality() -> None:
    frame = factor_frame().iloc[[7, 0, 8, 1, 9, 2, 10, 3, 11, 4, 5, 6]].copy()
    frame.index = [101, 7, 205, 12, 309, 14, 408, 18, 501, 22, 607, 25]
    original = frame.copy(deep=True)
    processing = spec(missing_value_policy="preserve_nan", standardization="none")
    fitted = fit_factor_processing(frame, ["factor"], processing, training_end="2026-01-05")

    result = apply_factor_processing(fitted, frame)

    pd.testing.assert_frame_equal(frame, original)
    assert result.data.index.tolist() == frame.index.tolist()
    assert result.data["factor"].isna().sum() == 1
    assert result.quality["output_rows"] == 12
    assert result.quality["dropped_rows"] == 0
    assert result.quality["deletion_rate"] == 0.0


@pytest.mark.parametrize(
    "processing, message",
    [
        (spec(missing_value_policy="fill_zero"), "missing"),
        (spec(standardization="minmax"), "standardization"),
        (spec(fit_scope="none", fit_train_only=False), "fit"),
    ],
)
def test_processing_rejects_unsupported_policy_or_fit_configuration(processing: ProcessingSpec, message: str) -> None:
    with pytest.raises(FactorProcessingError, match=message):
        fit_factor_processing(factor_frame(), ["factor"], processing, training_end="2026-01-05")


def test_processing_rejects_missing_identity_duplicate_keys_and_unknown_factor_columns() -> None:
    frame = factor_frame()
    with pytest.raises(FactorProcessingError, match="symbol"):
        fit_factor_processing(frame.drop(columns="symbol"), ["factor"], spec(), training_end="2026-01-05")
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(FactorProcessingError, match="duplicate"):
        fit_factor_processing(duplicate, ["factor"], spec(), training_end="2026-01-05")
    with pytest.raises(FactorProcessingError, match="unknown"):
        fit_factor_processing(frame, ["not_a_factor"], spec(), training_end="2026-01-05")


def test_fitted_processing_is_immutable_and_serializable() -> None:
    fitted = fit_factor_processing(factor_frame(), ["factor"], spec(), training_end="2026-01-05")

    payload = fitted.to_dict()

    assert payload["processing_id"] == "demo.factor.clean.v1"
    assert payload["factor_columns"] == ["factor"]
    assert payload["fit_scope"] == "training_period"
    assert "callable" not in repr(payload)
