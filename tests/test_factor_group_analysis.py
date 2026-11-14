from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_group_analysis import (
    GroupAnalysisError,
    build_quantile_groups,
    compute_group_returns,
    compute_group_turnover,
)


def grouped_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2026-01-02", periods=3, freq="B")
    for day_index, date in enumerate(dates):
        for asset_index in range(10):
            factor = float(asset_index + 1 + day_index * 0.01)
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"A{asset_index:02d}",
                    "factor": factor,
                    "forward_1d": factor / 100.0,
                    "forward_2d": factor / 200.0,
                    "asset_status": "active",
                }
            )
    return pd.DataFrame(rows)


def test_quantile_groups_keep_ties_and_report_group_quality() -> None:
    frame = grouped_frame()
    frame.loc[frame["trade_date"] == frame["trade_date"].min(), "factor"] = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]

    result = build_quantile_groups(frame, quantiles=5, min_assets_per_group=2)

    first = result.data[result.data["trade_date"] == frame["trade_date"].min()]
    assert set(first["factor_quantile"]) == {1, 2, 3, 4, 5}
    assert first.groupby("factor_quantile", observed=True).size().tolist() == [2, 2, 2, 2, 2]
    assert result.diagnostics["requested_quantiles"] == 5
    assert result.diagnostics["quality_status"] == "READY"

    constant = frame.copy()
    constant["factor"] = 1.0
    constant_result = build_quantile_groups(constant, quantiles=5, min_assets_per_group=1)
    assert constant_result.data["factor_quantile"].nunique() == 1
    assert constant_result.diagnostics["quality_status"] == "INSUFFICIENT_QUANTILES"


def test_group_returns_support_multiple_horizons_and_non_tradable_label() -> None:
    grouped = build_quantile_groups(grouped_frame(), quantiles=5, min_assets_per_group=2)
    result = compute_group_returns(
        grouped.data,
        return_columns={"1d": "forward_1d", "2d": "forward_2d"},
    )

    assert set(result.daily["horizon"]) == {"1d", "2d"}
    top_1d = result.daily[(result.daily["horizon"] == "1d") & (result.daily["factor_quantile"] == 5)]
    assert np.isclose(top_1d.iloc[0]["mean_return"], 0.095)
    one_day_cumulative = result.cumulative[result.cumulative["horizon"] == "1d"]
    assert one_day_cumulative[one_day_cumulative["factor_quantile"] > 0]["portfolio_type"].eq("research_equal_weight").all()
    assert one_day_cumulative[one_day_cumulative["factor_quantile"] == 0]["portfolio_type"].eq("long_short_daily_spread").all()
    spread = one_day_cumulative[one_day_cumulative["factor_quantile"] == 0].sort_values("trade_date")
    assert np.isclose(spread.iloc[-1]["cumulative_return"], (1.08 ** 3) - 1.0)
    assert result.diagnostics["tradable"] is False
    assert result.diagnostics["overlapping_labels_retained"] is True


def test_group_returns_do_not_fill_missing_values_or_fake_groups() -> None:
    grouped = build_quantile_groups(grouped_frame(), quantiles=5, min_assets_per_group=2)
    frame = grouped.data.copy()
    frame.loc[0, "forward_1d"] = np.nan
    result = compute_group_returns(frame, return_columns={"1d": "forward_1d"})

    first_top = result.daily[
        (result.daily["trade_date"] == frame["trade_date"].min())
        & (result.daily["factor_quantile"] == 1)
    ].iloc[0]
    assert first_top["valid_n"] == 1
    assert pd.isna(result.daily[result.daily["valid_n"] == 0]["mean_return"]).all()
    assert result.diagnostics["missing_return_rows"] == 1


def test_turnover_rank_autocorrelation_and_coverage_keep_denominators() -> None:
    frame = grouped_frame()
    frame.loc[(frame["trade_date"] == frame["trade_date"].iloc[10]) & (frame["symbol"] == "A00"), "asset_status"] = "exited"
    frame.loc[(frame["trade_date"] == frame["trade_date"].iloc[0]) & (frame["symbol"] == "A01"), "factor"] = np.nan
    grouped = build_quantile_groups(frame, quantiles=5, min_assets_per_group=1)
    result = compute_group_turnover(grouped.data, top_quantile=5)

    assert result.turnover.iloc[0]["status"] == "no_previous_session"
    assert result.turnover.iloc[1]["denominator"] == 2
    assert 0.0 <= result.turnover.iloc[1]["turnover"] <= 1.0
    assert result.coverage["exited_rows"] == 1
    assert result.coverage["missing_factor_rows"] == 1
    assert result.coverage["assigned_rows"] < result.coverage["input_rows"]
    assert result.rank_autocorrelation["valid_pairs"] >= 1


def test_group_analysis_rejects_invalid_identity_and_quantile_settings() -> None:
    with pytest.raises(GroupAnalysisError, match="duplicate"):
        build_quantile_groups(pd.concat([grouped_frame(), grouped_frame().iloc[[0]]]), quantiles=5)
    with pytest.raises(GroupAnalysisError, match="quantiles"):
        build_quantile_groups(grouped_frame(), quantiles=1)
