from __future__ import annotations

import pytest

from portfolio_app.offline_ledger import LedgerState
from portfolio_app.offline_market_rules import (
    AssetRule,
    CompanyAction,
    apply_company_action,
    validate_sellable_quantity,
)


def test_stock_split_updates_position_and_records_company_action() -> None:
    state = LedgerState(initial_cash=10_000.0, positions={"600000.SH": 100})
    updated, result = apply_company_action(
        state,
        CompanyAction(
            action_id="split-1",
            action_type="split",
            symbol="600000.SH",
            effective_date="2024-01-08",
            split_ratio=2.0,
        ),
    )

    assert result["status"] == "applied"
    assert updated.positions["600000.SH"] == 200
    assert updated.cash == pytest.approx(state.cash)
    assert updated.ledger[-1]["event_type"] == "company_action"
    assert updated.ledger[-1]["split_ratio"] == 2.0


def test_cash_dividend_credits_existing_position_and_is_auditable() -> None:
    state = LedgerState(initial_cash=10_000.0, positions={"600000.SH": 100})
    updated, result = apply_company_action(
        state,
        CompanyAction(
            action_id="div-1",
            action_type="cash_dividend",
            symbol="600000.SH",
            effective_date="2024-01-08",
            cash_per_share=0.35,
        ),
    )

    assert result["status"] == "applied"
    assert result["cash_credit"] == pytest.approx(35.0)
    assert updated.cash == pytest.approx(10_035.0)
    assert updated.positions["600000.SH"] == 100
    assert updated.ledger[-1]["cash_credit"] == pytest.approx(35.0)


def test_duplicate_or_unsupported_company_action_does_not_change_state() -> None:
    state = LedgerState(initial_cash=10_000.0, positions={"600000.SH": 100})
    action = CompanyAction("split-2", "split", "600000.SH", "2024-01-08", split_ratio=2.0)
    applied, _ = apply_company_action(state, action)
    duplicate, duplicate_result = apply_company_action(applied, action)
    assert duplicate == applied
    assert duplicate_result["reason"] == "duplicate_action"

    with pytest.raises(ValueError, match="action_type"):
        CompanyAction("x", "buyback", "600000.SH", "2024-01-08")


def test_t_plus_one_blocks_same_session_stock_sale_but_allows_next_session() -> None:
    stock = AssetRule(asset_type="cn_stock", lot_size=100, t_plus_one=True)
    assert validate_sellable_quantity(
        total_quantity=100,
        acquired_today_quantity=100,
        requested_quantity=100,
        rule=stock,
    ).allowed is False
    next_day = validate_sellable_quantity(
        total_quantity=300,
        acquired_today_quantity=0,
        requested_quantity=100,
        rule=stock,
    )
    assert next_day.allowed is True
    assert next_day.sellable_quantity == 300


def test_etf_rule_does_not_inherit_stock_t_plus_one_and_lot_is_explicit() -> None:
    etf = AssetRule(asset_type="etf", lot_size=1, t_plus_one=False)
    result = validate_sellable_quantity(
        total_quantity=100,
        acquired_today_quantity=100,
        requested_quantity=100,
        rule=etf,
    )
    assert result.allowed is True
    assert result.sellable_quantity == 100

    with pytest.raises(ValueError, match="lot"):
        AssetRule(asset_type="cn_stock", lot_size=0, t_plus_one=True)


def test_sellable_quantity_rejects_unknown_asset_rule_and_over_sale() -> None:
    rule = AssetRule(asset_type="us_stock", lot_size=1, t_plus_one=False)
    over = validate_sellable_quantity(
        total_quantity=50,
        acquired_today_quantity=0,
        requested_quantity=60,
        rule=rule,
    )
    assert over.allowed is False
    assert over.reason == "insufficient_position"
