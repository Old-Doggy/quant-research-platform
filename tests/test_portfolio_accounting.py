from __future__ import annotations

import math
import pytest

from portfolio_app.portfolio_accounting import (
    PortfolioAccountingError,
    build_portfolio_accounting,
)


def _prices():
    return {
        "AAA": {"2024-01-02": 10.0, "2024-01-03": 11.0, "2024-01-04": 10.0},
        "BBB": {"2024-01-02": 10.0, "2024-01-03": 9.0, "2024-01-04": 9.0},
    }


def test_portfolio_ledger_reconciles_nav_cash_positions_turnover_and_cost():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03", "2024-01-04"),
        prices={"AAA": {date: value for date, value in _prices()["AAA"].items()}},
        fills=(
            {"fill_id": "f1", "fill_date": "2024-01-03", "symbol": "AAA", "side": "BUY", "quantity": 5, "price": 10.0, "fee": 1.0, "leg": "trend"},
        ),
        initial_cash=100.0,
        benchmark_returns={"2024-01-03": 0.02, "2024-01-04": -0.01},
        cash_returns={"2024-01-03": 0.001, "2024-01-04": 0.001},
    )

    ledger = result.ledger.set_index("trade_date")
    assert ledger.loc["2024-01-03", "cash"] == pytest.approx(49.1)
    assert ledger.loc["2024-01-03", "positions_value"] == pytest.approx(55.0)
    assert ledger.loc["2024-01-03", "nav"] == pytest.approx(104.1)
    assert ledger.loc["2024-01-03", "cash_weight"] == pytest.approx(49.1 / 104.1)
    assert ledger.loc["2024-01-03", "gross_exposure"] == pytest.approx(55 / 104.1)
    assert ledger["reconciliation_delta"].abs().max() <= 1e-12
    assert ledger.loc["2024-01-03", "turnover_notional"] == pytest.approx(50.0)
    assert ledger.loc["2024-01-03", "cost"] == pytest.approx(1.0)
    assert ledger.loc["2024-01-03", "benchmark_return"] == pytest.approx(0.02)
    assert ledger.loc["2024-01-03", "cash_return"] == pytest.approx(0.001)
    assert result.diagnostics["nav_status"] == "reconciled"


def test_symbol_and_leg_contributions_reconcile_to_daily_return_without_fake_symbols():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03"),
        prices=_prices(),
        fills=(
            {"fill_id": "a", "fill_date": "2024-01-02", "symbol": "AAA", "side": "BUY", "quantity": 5, "price": 10.0, "fee": 0.0, "leg": "trend"},
            {"fill_id": "b", "fill_date": "2024-01-02", "symbol": "BBB", "side": "BUY", "quantity": 5, "price": 10.0, "fee": 0.0, "leg": "value"},
        ),
        initial_cash=100.0,
        factor_pnl={"2024-01-03": {"momentum": 5.0, "value": -5.0}},
        factor_source="synthetic-hand-calculation.v1",
    )

    ledger = result.ledger.set_index("trade_date")
    assert ledger.loc["2024-01-03", "daily_return"] == pytest.approx(0.0)
    symbols = result.symbol_contribution
    day = symbols.loc[symbols["trade_date"] == "2024-01-03"]
    assert set(day["symbol"]) == {"AAA", "BBB"}
    assert day["contribution"].sum() == pytest.approx(0.0)
    assert result.leg_contribution.groupby("trade_date")["contribution"].sum().loc["2024-01-03"] == pytest.approx(0.0)
    assert set(result.factor_contribution["factor"]) == {"momentum", "value"}
    assert "CCC" not in set(symbols["symbol"])
    assert result.diagnostics["contribution_status"] == "reconciled"


def _fill(identity, date, side, quantity, price, fee=0.0, leg="trend", symbol="AAA"):
    return dict(fill_id=identity, fill_date=date, side=side, quantity=quantity,
                price=price, fee=fee, leg=leg, symbol=symbol)


def test_entry_and_full_exit_use_fill_price_and_actual_fee_not_end_position_pnl():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03", "2024-01-04"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 100, "2024-01-03": 12, "2024-01-04": 13}},
        fills=(_fill("buy", "2024-01-03", "BUY", 5, 11, 1),
               _fill("sell", "2024-01-04", "SELL", 5, 13, 2)),
    )
    assert result.ledger.nav.tolist() == pytest.approx([100, 104, 107])
    assert result.ledger.daily_return.tolist() == pytest.approx([0, .04, 3 / 104])
    stock = result.symbol_contribution
    assert stock.pnl.tolist() == pytest.approx([5, 10])
    assert result.leg_contribution.pnl.tolist() == pytest.approx([5, 10])
    assert result.diagnostics["contribution_status"] == "reconciled"
    assert result.risk["status"] == "available"  # liquidation does not erase history


def test_same_symbol_two_legs_keep_ownership_and_attribute_fees_to_originating_leg():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03"), initial_cash=200,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 12}},
        fills=(_fill("a", "2024-01-02", "BUY", 5, 10, leg="alpha"),
               _fill("b", "2024-01-02", "BUY", 5, 10, leg="beta"),
               _fill("c", "2024-01-03", "SELL", 5, 11, 1, leg="alpha")),
    )
    day = result.leg_contribution.query("trade_date == '2024-01-03'").set_index("leg")
    assert day.loc["alpha", "pnl"] == pytest.approx(5)
    assert day.loc["beta", "pnl"] == pytest.approx(10)
    assert result.ledger.iloc[-1].nav == pytest.approx(214)
    assert result.ledger.iloc[-1].turnover == pytest.approx(55 / 200)


def test_first_day_fee_is_in_return_and_symbol_contribution_even_with_unchanged_price():
    result = build_portfolio_accounting(dates=("2024-01-02",), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10}},
        fills=(_fill("buy", "2024-01-02", "BUY", 5, 10, 1),))
    assert result.ledger.iloc[0].daily_return == pytest.approx(-.01)
    assert result.symbol_contribution.empty
    assert result.ledger.iloc[0].cost_contribution == pytest.approx(-.01)
    assert result.diagnostics["contribution_status"] == "reconciled"


def test_cash_and_benchmark_are_separate_and_missing_benchmark_is_unavailable():
    result = build_portfolio_accounting(dates=("2024-01-02", "2024-01-03"),
        prices={}, fills=(), initial_cash=100,
        cash_returns={"2024-01-03": .01}, benchmark_returns={"2024-01-03": .20})
    assert result.ledger.iloc[-1].nav == pytest.approx(101)
    assert result.ledger.iloc[-1].cash_contribution == pytest.approx(.01)
    assert result.symbol_contribution.empty
    missing = build_portfolio_accounting(dates=("2024-01-02",), prices={}, fills=(), initial_cash=100)
    assert missing.ledger.benchmark_return.isna().all()
    assert missing.diagnostics["benchmark_status"] == "unavailable"


def test_factor_source_and_residual_are_explicit_and_exposures_are_not_pnl():
    options = dict(dates=("2024-01-02", "2024-01-03"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 11}},
        fills=(_fill("buy", "2024-01-02", "BUY", 10, 10),))
    result = build_portfolio_accounting(**options,
        factor_pnl={"2024-01-03": {"momentum": 6}}, factor_source="fixture.v1")
    assert result.factor_contribution.iloc[0].contribution == pytest.approx(.06)
    assert result.ledger.iloc[-1].factor_residual_contribution == pytest.approx(.04)
    assert result.diagnostics["factor_status"] == "partial"
    with pytest.raises(PortfolioAccountingError, match="factor_source"):
        build_portfolio_accounting(**options, factor_pnl={"2024-01-03": {"momentum": 6}})


def test_factor_output_is_unavailable_without_explicit_factor_pnl_source():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 11}},
        fills=(_fill("buy", "2024-01-02", "BUY", 10, 10),),
    )
    assert result.factor_contribution.empty
    assert result.diagnostics["factor_status"] == "unavailable"


def test_two_legs_same_symbol_are_not_double_counted_on_holding_day():
    result = build_portfolio_accounting(dates=("2024-01-02", "2024-01-03"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 11}},
        fills=(_fill("a", "2024-01-02", "BUY", 5, 10, leg="a"),
               _fill("b", "2024-01-02", "BUY", 5, 10, leg="b")))
    assert result.symbol_contribution.iloc[-1].contribution == pytest.approx(.1)
    assert result.diagnostics["contribution_status"] == "reconciled"


def test_same_leg_multiple_symbols_sale_preserves_symbol_ownership():
    result = build_portfolio_accounting(dates=("2024-01-02", "2024-01-03"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 10},
                "BBB": {"2024-01-02": 20, "2024-01-03": 22}},
        fills=(_fill("a", "2024-01-02", "BUY", 4, 10),
               _fill("b", "2024-01-02", "BUY", 2, 20, symbol="BBB"),
               _fill("c", "2024-01-03", "SELL", 2, 22, symbol="BBB")))
    assert result.ledger.iloc[-1].nav == pytest.approx(104)
    assert result.diagnostics["contribution_status"] == "reconciled"
    assert result.symbol_contribution.iloc[-1].symbol == "BBB"
    assert result.symbol_contribution.iloc[-1].pnl == pytest.approx(4)
    assert result.leg_contribution.iloc[-1].pnl == pytest.approx(4)


def test_multi_symbol_leg_keeps_unsold_lots_and_can_sell_them_later():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03", "2024-01-04"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 11, "2024-01-04": 12},
                "BBB": {"2024-01-02": 20, "2024-01-03": 22}},
        fills=(_fill("a", "2024-01-02", "BUY", 4, 10),
               _fill("b", "2024-01-02", "BUY", 2, 20, symbol="BBB"),
               _fill("c", "2024-01-03", "SELL", 2, 22, symbol="BBB"),
               _fill("d", "2024-01-04", "SELL", 4, 12)),
    )
    assert result.ledger.nav.tolist() == pytest.approx([100, 108, 112])
    assert result.leg_contribution.iloc[-1].pnl == pytest.approx(12)
    assert result.diagnostics["contribution_status"] == "reconciled"


def test_incomplete_or_unrelated_benchmark_dates_do_not_claim_availability():
    options = dict(dates=("2024-01-02", "2024-01-03", "2024-01-04"),
                   prices={}, fills=(), initial_cash=100)
    partial = build_portfolio_accounting(**options, benchmark_returns={"2024-01-03": .01})
    unrelated = build_portfolio_accounting(**options, benchmark_returns={"2023-01-03": .01})
    complete = build_portfolio_accounting(**options,
        benchmark_returns={"2024-01-03": .01, "2024-01-04": -.01})
    assert partial.diagnostics["benchmark_status"] == "partial"
    assert unrelated.diagnostics["benchmark_status"] == "unavailable"
    assert complete.diagnostics["benchmark_status"] == "available"


def test_initial_cost_drawdown_includes_starting_cash_and_first_day_return():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03", "2024-01-04"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 10, "2024-01-04": 10}},
        fills=(_fill("buy", "2024-01-02", "BUY", 5, 10, fee=1),),
    )
    assert result.risk["observations"] == 3
    assert result.risk["max_drawdown"] == pytest.approx(-.01)


def test_factor_source_retained_and_missing_days_cannot_claim_complete_attribution():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03", "2024-01-04"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 11, "2024-01-04": 12}},
        fills=(_fill("a", "2024-01-02", "BUY", 10, 10),),
        factor_pnl={"2024-01-03": {"momentum": 10}}, factor_source="fixture.v1")
    assert result.diagnostics["factor_source"] == "fixture.v1"
    assert result.diagnostics["factor_status"] == "partial"


@pytest.mark.parametrize("kind", ["cash", "benchmark"])
def test_nonfinite_external_returns_rejected(kind):
    with pytest.raises(PortfolioAccountingError, match="return"):
        build_portfolio_accounting(dates=("2024-01-02", "2024-01-03"), initial_cash=100,
            prices={}, fills=(), **{kind + "_returns": {"2024-01-03": float("inf")}})


def test_window_metrics_match_independent_formulas_and_industry_requires_complete_pit():
    options = dict(dates=("2024-01-02", "2024-01-03", "2024-01-04"), initial_cash=100,
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 11, "2024-01-04": 9}},
        fills=(_fill("buy", "2024-01-02", "BUY", 10, 10),),
        annualization_sessions=12, risk_window=2)
    result = build_portfolio_accounting(**options)
    returns = [.1, -2 / 11]
    mean = sum(returns) / 2
    sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / 2)
    assert result.risk["sharpe"] == pytest.approx(mean / sd * math.sqrt(12))
    assert result.risk["sortino"] == pytest.approx(mean / math.sqrt((2 / 11) ** 2 / 2) * math.sqrt(12))
    assert result.risk["max_drawdown"] == pytest.approx(9 / 11 - 1)
    complete = build_portfolio_accounting(**options, industry_by_symbol={"AAA": "Tech"}, industry_pit_available=True)
    assert complete.risk["industry_concentration"] == 1
    incomplete = build_portfolio_accounting(**options, industry_by_symbol={"BBB": "Tech"}, industry_pit_available=True)
    assert incomplete.risk["industry_concentration_status"] == "incomplete"
    assert "industry_concentration" not in incomplete.risk


@pytest.mark.parametrize("fee", [-1, float("nan"), float("inf")])
def test_invalid_fee_is_blocked(fee):
    with pytest.raises(PortfolioAccountingError, match="fee"):
        build_portfolio_accounting(dates=("2024-01-02",), initial_cash=100,
            prices={"AAA": {"2024-01-02": 10}}, fills=(_fill("a", "2024-01-02", "BUY", 1, 10, fee),))


def test_risk_metrics_declare_window_annualization_missing_status_and_weighted_concentration():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"),
        prices={"AAA": {"2024-01-02": 10.0, "2024-01-03": 12.0, "2024-01-04": 11.0, "2024-01-05": 13.0},
                "BBB": {"2024-01-02": 10.0, "2024-01-03": 10.0, "2024-01-04": 10.0, "2024-01-05": 10.0}},
        fills=(
            {"fill_id": "a", "fill_date": "2024-01-02", "symbol": "AAA", "side": "BUY", "quantity": 8, "price": 10.0, "fee": 0.0, "leg": "trend"},
            {"fill_id": "b", "fill_date": "2024-01-02", "symbol": "BBB", "side": "BUY", "quantity": 2, "price": 10.0, "fee": 0.0, "leg": "value"},
        ),
        initial_cash=100.0,
        annualization_sessions=252,
        risk_window=2,
        industry_by_symbol={"AAA": "Tech", "BBB": "Finance"},
        industry_pit_available=False,
    )

    risk = result.risk
    assert risk["annualization_sessions"] == 252
    assert risk["window"] == 2
    assert risk["observations"] == 2
    assert risk["concentration_hhi"] == pytest.approx((104 / 124) ** 2 + (20 / 124) ** 2)
    assert risk["industry_concentration_status"] == "unavailable_pit"
    assert "industry_concentration" not in risk


def test_max_drawdown_uses_the_selected_risk_window_not_full_history():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"),
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 20, "2024-01-04": 18, "2024-01-05": 19, "2024-01-08": 19.5}},
        fills=(_fill("buy", "2024-01-02", "BUY", 10, 10),),
        initial_cash=100,
        annualization_sessions=252,
        risk_window=2,
    )
    assert result.risk["max_drawdown"] == pytest.approx(0.0)


def test_full_exit_does_not_require_marks_after_the_position_is_closed():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03", "2024-01-04"),
        prices={"AAA": {"2024-01-02": 10, "2024-01-03": 12}},
        fills=(
            _fill("buy", "2024-01-02", "BUY", 10, 10),
            _fill("sell", "2024-01-03", "SELL", 10, 12),
        ),
        initial_cash=100,
    )
    assert result.ledger.nav.tolist() == pytest.approx([100, 120, 120])
    assert result.ledger.iloc[-1].positions_value == pytest.approx(0)


def test_factor_contribution_is_unavailable_without_exposure_and_does_not_insert_zero_rows():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03"),
        prices={"AAA": {"2024-01-02": 10.0, "2024-01-03": 11.0}},
        fills=({"fill_id": "a", "fill_date": "2024-01-02", "symbol": "AAA", "side": "BUY", "quantity": 10, "price": 10.0, "fee": 0.0, "leg": "trend"},),
        initial_cash=100.0,
    )
    assert result.factor_contribution.empty
    assert result.diagnostics["factor_status"] == "unavailable"
    assert "BBB" not in set(result.symbol_contribution["symbol"])


def test_empty_all_cash_portfolio_has_valid_nav_but_unavailable_risk_and_no_fake_contributions():
    result = build_portfolio_accounting(
        dates=("2024-01-02", "2024-01-03"),
        prices={},
        fills=(),
        initial_cash=100.0,
    )
    assert result.ledger["nav"].tolist() == [100.0, 100.0]
    assert result.ledger["cash_weight"].tolist() == [1.0, 1.0]
    assert result.ledger["gross_exposure"].tolist() == [0.0, 0.0]
    assert result.symbol_contribution.empty
    assert result.risk["status"] == "unavailable"
    assert result.risk["observations"] == 0


def test_accounting_rejects_missing_marks_and_invalid_inputs_instead_of_zero_filling():
    with pytest.raises(PortfolioAccountingError, match="missing price"):
        build_portfolio_accounting(
            dates=("2024-01-02", "2024-01-03"),
            prices={"AAA": {"2024-01-02": 10.0}},
            fills=({"fill_id": "a", "fill_date": "2024-01-02", "symbol": "AAA", "side": "BUY", "quantity": 1, "price": 10.0, "fee": 0.0, "leg": "trend"},),
            initial_cash=10.0,
        )
    with pytest.raises(PortfolioAccountingError, match="initial_cash"):
        build_portfolio_accounting(dates=("2024-01-02",), prices={}, fills=(), initial_cash=-1.0)
