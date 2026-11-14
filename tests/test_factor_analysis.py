from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_analysis import (
    FactorAnalysisError,
    align_factor_labels,
    compute_ic_series,
    summarize_ic,
)


def research_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2026-01-02", periods=4, freq="B")
    for day_index, date in enumerate(dates):
        for symbol_index, symbol in enumerate(("A", "B", "C")):
            factor = float(symbol_index + day_index * 0.1)
            rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "factor": factor,
                    "forward_label": factor * 0.2 + 0.01 * day_index,
                }
            )
    return pd.DataFrame(rows)


def test_alignment_drops_missing_rows_with_reasons_and_reports_quality_gate() -> None:
    frame = research_frame()
    frame.loc[1, "factor"] = np.nan
    frame.loc[4, "forward_label"] = np.nan

    result = align_factor_labels(
        frame,
        factor_column="factor",
        label_column="forward_label",
        min_assets_per_date=3,
        min_sessions=4,
    )

    assert len(result.data) == len(frame) - 2
    assert result.diagnostics["dropped_by_reason"] == {
        "missing_factor": 1,
        "missing_label": 1,
    }
    assert result.diagnostics["quality_status"] == "INSUFFICIENT_CROSS_SECTION"
    assert result.diagnostics["valid_sessions"] == 4
    assert result.diagnostics["min_assets_per_date"] == 3


def test_alignment_rejects_duplicate_identity_and_invalid_dates() -> None:
    duplicate = pd.concat([research_frame(), research_frame().iloc[[0]]], ignore_index=True)
    with pytest.raises(FactorAnalysisError, match="duplicate"):
        align_factor_labels(duplicate)

    invalid = research_frame()
    invalid["trade_date"] = invalid["trade_date"].astype(object)
    invalid.loc[0, "trade_date"] = "not-a-date"
    with pytest.raises(FactorAnalysisError, match="trade_date"):
        align_factor_labels(invalid)


def test_ic_series_reports_pearson_and_rank_ic_without_fake_zero() -> None:
    result = align_factor_labels(research_frame(), min_assets_per_date=3, min_sessions=1)
    pearson = compute_ic_series(result.data, method="pearson", min_observations=3)
    rank = compute_ic_series(result.data, method="spearman", min_observations=3)

    assert np.allclose(pearson.data["ic"], 1.0)
    assert np.allclose(rank.data["ic"], 1.0)
    assert set(pearson.data["valid_n"]) == {3}
    assert pearson.diagnostics["method"] == "pearson"
    assert rank.diagnostics["method"] == "spearman"

    constant = result.data.copy()
    constant.loc[constant["trade_date"] == constant["trade_date"].min(), "factor"] = 1.0
    constant_result = compute_ic_series(constant, method="pearson", min_observations=3)
    first = constant_result.data.iloc[0]
    assert pd.isna(first["ic"])
    assert first["status"] == "constant_factor"


def test_ic_rejects_unknown_method_and_malformed_input() -> None:
    aligned = align_factor_labels(research_frame(), min_assets_per_date=3, min_sessions=1)
    with pytest.raises(FactorAnalysisError, match="method"):
        compute_ic_series(aligned.data, method="kendall")

    broken = aligned.data.drop(columns="symbol")
    with pytest.raises(FactorAnalysisError, match="symbol"):
        compute_ic_series(broken)


def test_ic_summary_exposes_raw_and_explicitly_annualized_metrics() -> None:
    aligned = align_factor_labels(research_frame(), min_assets_per_date=3, min_sessions=1)
    series = compute_ic_series(aligned.data, method="pearson", min_observations=3)
    summary = summarize_ic(series, frequency="daily", annualize=True)

    assert summary.metrics["valid_sessions"] == 4
    assert np.isclose(summary.metrics["ic_mean"], 1.0)
    assert np.isclose(summary.metrics["ic_std"], 0.0)
    assert summary.metrics["icir"] is None
    assert summary.metrics["annualization_factor"] == 252
    assert summary.metrics["annualized_icir"] is None
    assert summary.metrics["frequency"] == "daily"


def test_ic_summary_does_not_claim_statistical_guarantee_for_small_samples() -> None:
    aligned = align_factor_labels(research_frame(), min_assets_per_date=3, min_sessions=1)
    series = compute_ic_series(aligned.data, method="pearson", min_observations=3)
    summary = summarize_ic(series, frequency="weekly", annualize=False, rolling_window=3)

    assert summary.metrics["frequency"] == "weekly"
    assert summary.metrics["annualized_icir"] is None
    assert summary.diagnostics["statistical_guarantee"] is False
    assert len(summary.rolling) == 4
    assert summary.rolling[-1]["window_observations"] == 3
