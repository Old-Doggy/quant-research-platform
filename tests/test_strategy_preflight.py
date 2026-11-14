from __future__ import annotations

import pytest

from portfolio_app.strategy_preflight import (
    PreflightStatus,
    StrategyRunSpec,
    preflight_strategy_run,
)


def ready_manifest() -> dict[str, object]:
    return {
        "dataset_id": "demo.raw.v1",
        "price_mode": "raw",
        "corporate_actions": "complete",
        "point_in_time": "known",
        "quality_status": "passed",
        "capabilities": ["raw_price_share_ledger", "cash_backtest", "local_backtest_input"],
        "required_columns": ["trade_date", "symbol", "open", "high", "low", "close"],
    }


def ready_spec(**changes):
    payload = {
        "strategy_id": "demo",
        "dataset_id": "demo.raw.v1",
        "history_start": "2024-01-01",
        "history_end": "2024-06-30",
        "history_sessions": 120,
        "buy_rule": {"type": "threshold", "field": "close", "operator": ">", "value": 1},
        "sell_rule": {"type": "threshold", "field": "close", "operator": "<", "value": 1},
        "execution_policy": {"price_field": "open", "fill_model": "next_open"},
        "commission_bps": 5.0,
        "slippage_bps": 2.0,
    }
    payload.update(changes)
    return StrategyRunSpec.from_mapping(payload)


def test_preflight_allows_trusted_offline_run_only_when_data_rules_history_and_costs_are_complete():
    report = preflight_strategy_run(ready_spec(), ready_manifest())

    assert report.status is PreflightStatus.READY
    assert report.can_run is True
    assert report.execution_label == "offline_cash_ledger_simulation"
    assert report.reasons == ()


def test_adjusted_or_incomplete_execution_data_is_proxy_only_and_never_claims_cash_backtest():
    manifest = {**ready_manifest(), "price_mode": "qfq", "capabilities": ["demo_backtest"]}
    report = preflight_strategy_run(ready_spec(), manifest)

    assert report.status is PreflightStatus.PROXY_ONLY
    assert report.can_run is True
    assert report.execution_label == "research_proxy_only"
    assert any("raw" in reason for reason in report.reasons)
    assert report.trusted_cash_simulation is False


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"buy_rule": None}, "buy_rule"),
        ({"history_sessions": 0}, "history"),
        ({"commission_bps": -1}, "commission"),
        ({"execution_policy": {"price_field": "adj_close", "fill_model": "next_open"}}, "raw"),
    ],
)
def test_preflight_blocks_missing_rules_history_costs_or_unsupported_execution(changes, match):
    spec = ready_spec(**changes)
    report = preflight_strategy_run(spec, ready_manifest())

    assert report.status is PreflightStatus.BLOCKED
    assert report.can_run is False
    assert any(match in reason for reason in report.reasons)


def test_preflight_requires_matching_dataset_identity_and_required_columns():
    report = preflight_strategy_run(ready_spec(), {**ready_manifest(), "dataset_id": "other", "required_columns": ["close"]})

    assert report.status is PreflightStatus.BLOCKED
    assert report.can_run is False
    assert any("dataset" in reason for reason in report.reasons)
    assert any("columns" in reason for reason in report.reasons)


def test_preflight_blocks_failed_quality_or_missing_execution_columns():
    failed_quality = {**ready_manifest(), "quality_status": "failed"}
    report = preflight_strategy_run(ready_spec(), failed_quality)
    assert report.status is PreflightStatus.BLOCKED
    assert report.can_run is False
    assert any("quality" in reason for reason in report.reasons)

    missing_open = {**ready_manifest(), "required_columns": ["trade_date", "symbol", "high", "low", "close"]}
    report = preflight_strategy_run(ready_spec(), missing_open)
    assert report.status is PreflightStatus.BLOCKED
    assert report.can_run is False
    assert any("columns" in reason for reason in report.reasons)
