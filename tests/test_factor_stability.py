from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_stability import (
    FactorStabilityError,
    compute_factor_correlation,
    compute_ic_decay,
)


def stability_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2025-12-29", periods=8, freq="B")
    for day_index, date in enumerate(dates):
        for asset_index in range(6):
            factor = float(asset_index + day_index * 0.01)
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"A{asset_index:02d}",
                    "factor_a": factor,
                    "factor_b": factor * 2.0 + 1.0,
                    "factor_c": float(5 - asset_index),
                    "forward_1d": factor / 100.0,
                    "forward_3d": factor / 200.0,
                    "industry": "tech" if asset_index < 3 else "bank",
                }
            )
    return pd.DataFrame(rows)


def test_ic_decay_uses_shared_sessions_and_marks_incomplete_years() -> None:
    result = compute_ic_decay(
        stability_frame(),
        label_columns={"1d": "forward_1d", "3d": "forward_3d"},
        factor_column="factor_a",
        min_observations=5,
        rolling_window=3,
    )

    assert set(result.ic_series["horizon"]) == {"1d", "3d"}
    assert result.ic_series.groupby("horizon")["trade_date"].nunique().to_dict() == {"1d": 8, "3d": 8}
    assert set(result.decay_summary["horizon"]) == {"1d", "3d"}
    assert result.annual_summary["complete_year"].eq(False).all()
    assert set(result.rolling_summary["window_observations"]) <= {1, 2, 3}
    assert result.diagnostics["shared_session_anchor"] is True


def test_ic_decay_rejects_negative_windows_and_unknown_labels() -> None:
    with pytest.raises(FactorStabilityError, match="rolling_window"):
        compute_ic_decay(stability_frame(), factor_column="factor_a", label_columns={"1d": "forward_1d"}, rolling_window=-1)
    with pytest.raises(FactorStabilityError, match="label"):
        compute_ic_decay(stability_frame(), factor_column="factor_a", label_columns={"1d": "missing_label"})


def test_factor_correlation_reports_common_n_and_optional_group_rows() -> None:
    frame = stability_frame()
    frame.loc[0, "factor_b"] = np.nan
    result = compute_factor_correlation(
        frame,
        factor_columns=["factor_a", "factor_b", "factor_c"],
        group_column="industry",
        min_observations=3,
    )

    overall = result.matrix[(result.matrix["group"] == "__all__") & (result.matrix["left"] == "factor_a") & (result.matrix["right"] == "factor_b")].iloc[0]
    assert overall["common_n"] == len(frame) - 1
    assert np.isclose(overall["correlation"], 1.0)
    assert set(result.matrix["group"]) == {"__all__", "bank", "tech"}
    assert result.diagnostics["method"] == "spearman"


def test_factor_correlation_keeps_insufficient_and_constant_states() -> None:
    frame = stability_frame()
    frame["factor_c"] = 1.0
    result = compute_factor_correlation(frame, factor_columns=["factor_a", "factor_c"], min_observations=3)
    row = result.matrix.iloc[0]
    assert row["status"] == "constant_factor"
    assert pd.isna(row["correlation"])

    with pytest.raises(FactorStabilityError, match="factor_columns"):
        compute_factor_correlation(frame, factor_columns=["factor_a"])
