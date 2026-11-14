from __future__ import annotations

import pytest

from portfolio_app.offline_ledger import FillEvent, LedgerState, apply_fill
from portfolio_app.offline_performance import (
    build_daily_nav,
    calculate_performance_metrics,
    reconcile_nav,
    run_stage28_truth_exit,
)


def test_nav_reconciles_cash_positions_and_mark_prices() -> None:
    state = LedgerState(initial_cash=10_000.0, cash=7_995.0, positions={"600000.SH": 100}, total_fees=5.0)
    nav = build_daily_nav(
        state,
        prices={"600000.SH": 21.0},
        price_status={"600000.SH": "fresh"},
        as_of="2024-01-08",
    )

    assert nav["cash"] == pytest.approx(7_995.0)
    assert nav["positions_value"] == pytest.approx(2_100.0)
    assert nav["nav"] == pytest.approx(10_095.0)
    assert nav["gross_exposure"] == pytest.approx(2_100.0)
    assert reconcile_nav(nav)["status"] == "reconciled"


def test_missing_price_is_not_zero_filled_and_stale_value_is_not_executable() -> None:
    state = LedgerState(initial_cash=10_000.0, positions={"600000.SH": 100})
    nav = build_daily_nav(
        state,
        prices={"600000.SH": 20.0},
        price_status={"600000.SH": "stale"},
        tradable={"600000.SH": False},
        as_of="2024-01-08",
    )
    assert nav["positions_value"] == pytest.approx(2_000.0)
    assert nav["executable_symbols"] == []
    assert nav["diagnostics"]["stale_valuation_symbols"] == ["600000.SH"]

    with pytest.raises(ValueError, match="missing price"):
        build_daily_nav(state, prices={}, price_status={}, as_of="2024-01-08")


def test_performance_metrics_define_return_risk_and_drawdown_without_fake_sharpe() -> None:
    nav_rows = [
        {"as_of": "2024-01-02", "nav": 100.0},
        {"as_of": "2024-01-03", "nav": 102.0},
        {"as_of": "2024-01-04", "nav": 101.0},
        {"as_of": "2024-01-05", "nav": 103.0},
    ]
    metrics = calculate_performance_metrics(nav_rows, annualization_sessions=252)

    assert metrics["total_return"] == pytest.approx(0.03)
    assert metrics["max_drawdown"] == pytest.approx(101.0 / 102.0 - 1.0)
    assert metrics["observations"] == 3
    assert metrics["sharpe"] is not None
    assert metrics["sortino"] is not None

    flat = calculate_performance_metrics(
        [{"as_of": "2024-01-02", "nav": 100.0}, {"as_of": "2024-01-03", "nav": 100.0}],
        annualization_sessions=252,
    )
    assert flat["sharpe"] is None
    assert flat["sortino"] is None


def test_stage28_truth_exit_covers_rejection_partial_fill_fee_dividend_and_jump() -> None:
    report = run_stage28_truth_exit()

    assert report["fixture_kind"] == "stage28_offline_truth_fixture"
    assert all(report["checks"].values())
    assert report["checks"]["jump_excludes_pre_entry_return"] is True
    assert report["checks"]["rejected_fill_preserves_state"] is True
    assert report["checks"]["partial_fill_has_remaining"] is True
    assert report["checks"]["dividend_reconciles_cash"] is True
