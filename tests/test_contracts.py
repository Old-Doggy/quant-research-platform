from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.contracts import (
    BacktestResultEnvelope,
    ContractViolation,
    DatasetManifest,
    DisclosureMode,
    ExecutionPolicy,
    Fill,
    OrderIntent,
    PortfolioState,
    ResearchEvidenceEnvelope,
    StrategySpec,
    TradeEvent,
    get_disclosure_policy,
    validate_market_frame_contract,
    validate_signal_frame_contract,
)


def test_market_data_contract_requires_canonical_daily_bar_fields():
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-01-02"]),
            "symbol": ["AAA"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
        }
    )

    validated = validate_market_frame_contract(frame)

    assert validated["rows"] == 1
    assert validated["symbols"] == 1
    assert validated["schema_version"] == "1.1"


def test_market_data_contract_rejects_missing_or_invalid_price_fields():
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-01-02"]),
            "symbol": ["AAA"],
            "open": [10.0],
            "high": [9.0],
            "low": [9.5],
            "close": [10.5],
        }
    )

    with pytest.raises(ContractViolation, match="high/low"):
        validate_market_frame_contract(frame)


def test_strategy_signal_contract_requires_decision_and_effective_dates():
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-01-02"]),
            "symbol": ["AAA"],
            "strategy_id": ["demo.trend"],
            "signal": [1],
            "signal_label": ["long"],
            "reason_code": ["trend_confirmed"],
            "reason_text_public": ["Trend confirmed; position opened"],
            "reason_evidence": [{"close_above_fast_ma": True}],
            "decision_date": pd.to_datetime(["2026-01-02"]),
            "effective_date": pd.to_datetime(["2026-01-05"]),
        }
    )

    result = validate_signal_frame_contract(frame)

    assert result["execution_lag_days"] == 1
    assert result["strategy_ids"] == ["demo.trend"]


def test_strategy_signal_contract_rejects_missing_public_reason_fields():
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-01-02"]),
            "symbol": ["AAA"],
            "strategy_id": ["demo.trend"],
            "signal": [1],
            "signal_label": ["long"],
            "decision_date": pd.to_datetime(["2026-01-02"]),
            "effective_date": pd.to_datetime(["2026-01-05"]),
        }
    )

    with pytest.raises(ContractViolation, match="reason_code"):
        validate_signal_frame_contract(frame)


def test_order_fill_portfolio_and_backtest_contracts_are_serializable():
    order = OrderIntent(
        order_id="order-1",
        strategy_id="demo.trend",
        symbol="AAA",
        side="BUY",
        quantity=100,
        decision_date="2026-01-02",
        execution_date="2026-01-05",
        target_weight=0.25,
    )
    fill = Fill(
        fill_id="fill-1",
        order_id="order-1",
        symbol="AAA",
        quantity=100,
        fill_price=10.2,
        fill_date="2026-01-05",
        commission=0.5,
        slippage=0.1,
    )
    portfolio = PortfolioState(
        as_of_date="2026-01-05",
        cash=9_000.0,
        equity=10_020.0,
        gross_exposure=0.25,
        net_exposure=0.25,
        positions_count=1,
    )
    result = BacktestResultEnvelope(
        strategy_id="demo.trend",
        evidence_layer="interactive_demo",
        source_kind="interactive_demo",
        start_date="2026-01-02",
        end_date="2026-01-05",
        metrics={"annual_return": 0.12, "sharpe": 0.8, "max_drawdown": -0.05},
        trade_count=1,
    )

    for item in (order, fill, portfolio, result):
        assert item.to_dict()


def test_disclosure_modes_make_public_boundaries_explicit():
    private = get_disclosure_policy(DisclosureMode.PRIVATE_LOCAL)
    public = get_disclosure_policy(DisclosureMode.PUBLIC_REDACTED)
    demo = get_disclosure_policy(DisclosureMode.PUBLIC_DEMO)

    assert private.allow_raw_data is True
    assert private.allow_target_positions is True
    assert public.allow_raw_data is False
    assert public.allow_target_positions is False
    assert public.allow_aggregate_metrics is True
    assert demo.allow_synthetic_data is True


def test_strategy_spec_requires_version_and_declares_next_day_execution():
    spec = StrategySpec(
        strategy_id="demo.trend",
        display_name="Demo trend",
        version="1.0",
        required_features=("close", "ma20", "ma60"),
        execution_lag_days=1,
    )

    assert spec.to_dict()["execution_lag_days"] == 1


def test_trade_event_links_signal_order_and_fill_with_public_reason():
    event = TradeEvent(
        event_id="event-1",
        event_type="FILL",
        strategy_id="demo.trend",
        symbol="AAA",
        side="BUY",
        decision_date="2026-01-02",
        effective_date="2026-01-05",
        fill_date="2026-01-05",
        reason_code="trend_confirmed",
        reason_text_public="Trend confirmed; position opened",
        evidence={"close_above_fast_ma": True, "fast_ma_above_slow_ma": True},
        order_id="order-1",
        fill_id="fill-1",
        quantity=100,
        price=10.2,
        status="FILLED",
    )

    payload = event.to_dict()

    assert payload["event_type"] == "FILL"
    assert payload["decision_date"] == "2026-01-02"
    assert payload["effective_date"] == "2026-01-05"
    assert payload["fill_date"] == "2026-01-05"
    assert payload["reason_code"] == "trend_confirmed"
    assert payload["evidence"]["fast_ma_above_slow_ma"] is True


def test_trade_event_rejects_invalid_timeline_and_side():
    with pytest.raises(ContractViolation, match="event_type"):
        TradeEvent(
            event_id="event-1",
            event_type="UNKNOWN",
            strategy_id="demo.trend",
            symbol="AAA",
            side="BUY",
            decision_date="2026-01-02",
            effective_date="2026-01-05",
            reason_code="trend_confirmed",
            reason_text_public="Public explanation",
        )

    with pytest.raises(ContractViolation, match="fill_date"):
        TradeEvent(
            event_id="event-1",
            event_type="FILL",
            strategy_id="demo.trend",
            symbol="AAA",
            side="SELL",
            decision_date="2026-01-05",
            effective_date="2026-01-05",
            fill_date="2026-01-02",
            reason_code="risk_exit",
            reason_text_public="Risk condition triggered exit",
        )


def test_dataset_manifest_freezes_source_coverage_and_price_mode():
    manifest = DatasetManifest(
        dataset_id="demo.daily.v1",
        display_name="Seeded daily bars",
        source_kind="seeded_demo",
        license_note="generated for demonstration",
        frequency="1d",
        price_mode="raw",
        start_date="2024-01-02",
        end_date="2026-01-02",
        symbol_count=3,
        row_count=1500,
        required_columns=("trade_date", "symbol", "open", "high", "low", "close"),
        quality_status="passed",
        generated_at="2026-10-16T00:00:00Z",
    )

    payload = manifest.to_dict()

    assert payload["dataset_id"] == "demo.daily.v1"
    assert payload["price_mode"] == "raw"
    assert payload["row_count"] == 1500
    assert payload["schema_version"] == "1.1"


def test_execution_policy_requires_explicit_fill_and_cost_assumptions():
    policy = ExecutionPolicy(
        policy_id="next_open_costed",
        execution_lag_days=1,
        price_field="open",
        fill_model="next_bar",
        commission_bps=3.0,
        slippage_bps=5.0,
        reject_untradable=True,
        as_of_policy="decision_date",
    )

    assert policy.to_dict()["fill_model"] == "next_bar"
    assert policy.to_dict()["slippage_bps"] == 5.0

    with pytest.raises(ContractViolation, match="commission"):
        ExecutionPolicy(
            policy_id="invalid",
            execution_lag_days=1,
            price_field="open",
            fill_model="next_bar",
            commission_bps=-1.0,
            slippage_bps=0.0,
            reject_untradable=True,
            as_of_policy="decision_date",
        )


def test_research_evidence_envelope_requires_status_cost_and_limitations():
    evidence = ResearchEvidenceEnvelope(
        model_id="model3",
        evidence_layer="selection_validation",
        status="validated",
        source_kind="curated_research_summary",
        disclosure_mode=DisclosureMode.PUBLIC_REDACTED,
        period_start="2016-01-04",
        period_end="2026-04-30",
        metrics={"annual_return": 0.1186, "sharpe": 0.88},
        cost_assumption="approved aggregate cost case",
        limitations=("Annual OOS includes an incomplete current year.",),
        artifact_ids=("model3_summary",),
    )

    payload = evidence.to_dict()

    assert payload["evidence_layer"] == "selection_validation"
    assert payload["disclosure_mode"] == "public_redacted"
    assert payload["limitations"]

    with pytest.raises(ContractViolation, match="private"):
        ResearchEvidenceEnvelope(
            model_id="model3",
            evidence_layer="selection_validation",
            status="validated",
            source_kind="curated_research_summary",
            disclosure_mode=DisclosureMode.PUBLIC_REDACTED,
            period_start="2016-01-04",
            period_end="2026-04-30",
            metrics={"annual_return": 0.1},
            cost_assumption="approved aggregate cost case",
            limitations=("private strategy path: D:/secret",),
        )
