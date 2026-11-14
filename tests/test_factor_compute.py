from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_compute import (
    BASIC_FACTOR_SPECS,
    FactorComputeError,
    compute_basic_factors,
)


def make_bars(rows: int = 80) -> pd.DataFrame:
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


def test_basic_factor_registry_contains_twelve_public_demo_specs() -> None:
    assert len(BASIC_FACTOR_SPECS) == 12
    assert len({spec.factor_id for spec in BASIC_FACTOR_SPECS}) == 12
    assert {spec.compute_status.value for spec in BASIC_FACTOR_SPECS} == {"computable"}
    assert all(spec.disclosure_status.value == "public_demo" for spec in BASIC_FACTOR_SPECS)


def test_returns_reversal_and_realized_volatility_match_hand_calculation() -> None:
    bars = make_bars()
    result = compute_basic_factors(bars)

    expected_5d = bars["close"].pct_change(5)
    expected_20d = bars["close"].pct_change(20)
    expected_vol20 = bars["close"].pct_change().rolling(20, min_periods=20).std(ddof=0)

    assert result.loc[5, "return_1d"] == pytest.approx(bars.loc[5, "close"] / bars.loc[4, "close"] - 1)
    assert result.loc[5, "return_5d"] == pytest.approx(expected_5d.loc[5])
    assert result.loc[20, "return_20d"] == pytest.approx(expected_20d.loc[20])
    assert result.loc[60, "return_60d"] == pytest.approx(bars.loc[60, "close"] / bars.loc[0, "close"] - 1)
    assert result.loc[5, "reversal_5d"] == pytest.approx(-expected_5d.loc[5])
    assert result.loc[20, "realized_volatility_20d"] == pytest.approx(expected_vol20.loc[20])


def test_price_volume_factors_have_explicit_units_and_warmup_missing_values() -> None:
    bars = make_bars()
    result = compute_basic_factors(bars)

    assert result.loc[0, "return_5d"] is np.nan or pd.isna(result.loc[0, "return_5d"])
    assert pd.isna(result.loc[18, "volume_ratio_20d"])
    assert pd.isna(result.loc[18, "price_volume_corr_20d"])
    assert pd.isna(result.loc[18, "range_position_20d"])
    assert result.loc[20, "volume_ratio_20d"] == pytest.approx(bars.loc[20, "vol"] / bars.loc[1:20, "vol"].mean())
    assert result.loc[20, "ma_deviation_20d"] == pytest.approx(
        bars.loc[20, "close"] / bars.loc[1:20, "close"].mean() - 1
    )
    assert result.loc[20, "range_position_20d"] == pytest.approx(
        (bars.loc[20, "close"] - bars.loc[1:20, "low"].min())
        / (bars.loc[1:20, "high"].max() - bars.loc[1:20, "low"].min())
    )
    assert result.loc[1, "illiquidity"] == pytest.approx(abs(bars.loc[1, "close"] / bars.loc[0, "close"] - 1) / bars.loc[1, "amount"])
    previous_close = bars["close"].shift(1)
    true_range = pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - previous_close).abs(), (bars["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    assert result.loc[20, "atr_ratio_14d"] == pytest.approx(true_range.loc[7:20].mean() / bars.loc[20, "close"])
    zero_amount = bars.copy()
    zero_amount.loc[10, "amount"] = 0.0
    zero_result = compute_basic_factors(zero_amount)
    assert pd.isna(zero_result.loc[10, "illiquidity"])


def test_factor_calculation_is_grouped_by_symbol_and_has_no_future_leakage() -> None:
    second = make_bars().assign(symbol="BBB")
    second[["open", "high", "low", "close"]] = second[["open", "high", "low", "close"]] * 2
    second["amount"] = second["close"] * second["vol"]
    bars = pd.concat([make_bars(), second], ignore_index=True)
    result = compute_basic_factors(bars)
    aaa = result[result["symbol"] == "AAA"].reset_index(drop=True)
    bbb = result[result["symbol"] == "BBB"].reset_index(drop=True)
    assert pd.isna(aaa.loc[0, "return_1d"])
    assert pd.isna(bbb.loc[0, "return_1d"])

    changed = bars.copy()
    changed.loc[70, "close"] = 9999.0
    changed.loc[70, "high"] = 9999.0
    changed.loc[70, "amount"] = changed.loc[70, "close"] * changed.loc[70, "vol"]
    changed_result = compute_basic_factors(changed)
    pd.testing.assert_series_equal(
        result.loc[:69, "return_20d"].reset_index(drop=True),
        changed_result.loc[:69, "return_20d"].reset_index(drop=True),
        check_names=False,
    )


@pytest.mark.parametrize("missing", ["vol", "amount"])
def test_volume_dependent_factors_reject_missing_inputs(missing: str) -> None:
    bars = make_bars().drop(columns=[missing])
    with pytest.raises(FactorComputeError, match=missing):
        compute_basic_factors(bars)


def test_missing_volume_only_disables_requested_volume_factors() -> None:
    bars = make_bars().drop(columns=["vol", "amount"])
    result = compute_basic_factors(bars, factor_ids={"basic.return_20d", "basic.realized_volatility_20d"})
    assert "return_20d" in result
    assert "realized_volatility_20d" in result
    assert "volume_ratio_20d" not in result


def test_duplicate_symbol_session_is_rejected() -> None:
    bars = pd.concat([make_bars(), make_bars().iloc[[0]]], ignore_index=True)
    with pytest.raises(FactorComputeError, match="duplicate"):
        compute_basic_factors(bars)


def test_invalid_or_empty_market_frame_is_rejected() -> None:
    with pytest.raises(FactorComputeError):
        compute_basic_factors(pd.DataFrame())
    with pytest.raises(FactorComputeError, match="close"):
        compute_basic_factors(make_bars().drop(columns=["close"]))


def test_selected_factor_ids_control_output_columns() -> None:
    result = compute_basic_factors(make_bars(), factor_ids={"basic.return_1d", "basic.volume_ratio_20d"})

    assert "return_1d" in result.columns
    assert "volume_ratio_20d" in result.columns
    assert "return_20d" not in result.columns
    assert "realized_volatility_20d" not in result.columns


def test_selected_factor_uses_only_its_declared_input_fields() -> None:
    price_only = make_bars()[["trade_date", "symbol", "close"]]
    volume_only = make_bars()[["trade_date", "symbol", "vol"]]

    price_result = compute_basic_factors(price_only, factor_ids={"basic.return_20d"})
    volume_result = compute_basic_factors(volume_only, factor_ids={"basic.volume_ratio_20d"})

    assert price_result.loc[20, "return_20d"] == pytest.approx(price_only.loc[20, "close"] / price_only.loc[0, "close"] - 1)
    assert volume_result.loc[20, "volume_ratio_20d"] == pytest.approx(volume_only.loc[20, "vol"] / volume_only.loc[1:20, "vol"].mean())
