from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.data import normalise_market_frame
from portfolio_app.research import run_portfolio_research


def _frame(symbol: str, drift: float, rows: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=rows, freq="B")
    close = pd.Series(100 + pd.Series(range(rows)) * drift, dtype=float)
    return normalise_market_frame(
        pd.DataFrame(
            {
                "date": dates.strftime("%Y%m%d"),
                "symbol": symbol,
                "open": close - 0.4,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000,
            }
        )
    )


def test_weighted_portfolio_research_preserves_target_weights_cash_and_attribution():
    result = run_portfolio_research(
        {"AAA": _frame("AAA", 0.3), "BBB": _frame("BBB", 0.1)},
        strategy_key="trend",
        target_weights={"AAA": 0.6, "BBB": 0.3},
        cash_weight=0.1,
        transaction_cost=0.001,
    )
    assert result.weights == {"AAA": 0.6, "BBB": 0.3}
    assert result.cash_weight == 0.1
    assert {"AAA", "BBB"}.issubset(result.attribution.columns)
    pd.testing.assert_series_equal(
        result.attribution[["AAA", "BBB"]].sum(axis=1),
        result.frame["daily_return"],
        check_names=False,
    )
    assert result.frame["gross_exposure"].max() <= 0.9 + 1e-12
    assert result.frame["cash_weight"].min() >= 0.1 - 1e-12


def test_weighted_portfolio_research_rejects_invalid_constraints():
    frames = {"AAA": _frame("AAA", 0.2), "BBB": _frame("BBB", 0.1)}
    with pytest.raises(ValueError, match="weights must be non-negative"):
        run_portfolio_research(frames, strategy_key="trend", target_weights={"AAA": -0.1, "BBB": 1.0})
    with pytest.raises(ValueError, match="sum"):
        run_portfolio_research(frames, strategy_key="trend", target_weights={"AAA": 0.8, "BBB": 0.5}, cash_weight=0.0)
    with pytest.raises(ValueError, match="cash_weight"):
        run_portfolio_research(frames, strategy_key="trend", target_weights={"AAA": 0.8, "BBB": 0.1}, cash_weight=-0.1)


def test_missing_leg_policy_is_explicit_and_deterministic():
    frames = {"AAA": _frame("AAA", 0.2)}
    weights = {"AAA": 0.6, "BBB": 0.3}
    with pytest.raises(ValueError, match="missing portfolio legs"):
        run_portfolio_research(frames, strategy_key="trend", target_weights=weights, cash_weight=0.1, missing_leg_policy="fail")

    preserve_cash = run_portfolio_research(
        frames,
        strategy_key="trend",
        target_weights=weights,
        cash_weight=0.1,
        missing_leg_policy="preserve_cash",
    )
    assert preserve_cash.weights == {"AAA": 0.6}
    assert preserve_cash.cash_weight == 0.4

    renormalized = run_portfolio_research(
        frames,
        strategy_key="trend",
        target_weights=weights,
        cash_weight=0.1,
        missing_leg_policy="renormalize",
    )
    assert renormalized.weights == {"AAA": 0.9}
    assert renormalized.cash_weight == 0.1
