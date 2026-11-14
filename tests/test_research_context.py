from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from portfolio_app.research_context import (
    CONTEXT_SCHEMA_VERSION,
    RUN_SPEC_SCHEMA_VERSION,
    ContractViolation,
    ResearchContext,
    RunSpec,
    context_from_legacy_params,
    run_spec_from_legacy_params,
)


def _context(**overrides) -> ResearchContext:
    values = {
        "dataset_id": "seeded_demo",
        "workspace": "watch",
        "symbol": "600000.SH",
        "bar_period": "1d",
        "as_of": "2026-02-27",
    }
    values.update(overrides)
    return ResearchContext(**values)


def test_research_context_has_versioned_identity_and_stable_id():
    context = _context()
    same = _context()

    assert context.schema_version == CONTEXT_SCHEMA_VERSION
    assert context.context_id == same.context_id
    assert context.context_id.startswith("ctx-")
    assert context.to_dict()["context_id"] == context.context_id


def test_context_allows_factor_and_portfolio_shapes_without_private_payloads():
    factor = _context(
        workspace="factors",
        factor_id="momentum-20d",
        symbol=None,
        symbols=("600000.SH", "000001.SZ"),
        date_start="2025-01-01",
        date_end="2026-02-27",
        indicator_ids=(),
    )
    portfolio = _context(
        workspace="portfolio",
        symbol=None,
        symbols=("600000.SH", "000001.SZ"),
        strategy_id="template-trend",
    )

    assert factor.symbols == ("600000.SH", "000001.SZ")
    assert portfolio.strategy_id == "template-trend"
    assert "private" not in str(factor.to_dict()).lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workspace", "unknown"),
        ("dataset_id", "../private-data"),
        ("bar_period", "5m"),
        ("as_of", "2026-02-30"),
        ("symbol", "D:/private/positions.csv"),
    ],
)
def test_context_rejects_unknown_ids_paths_and_invalid_values(field: str, value: str):
    with pytest.raises(ContractViolation):
        _context(**{field: value})


def test_context_rejects_reversed_window_and_mixed_symbol_inputs():
    with pytest.raises(ContractViolation, match="date_end"):
        _context(date_start="2026-02-27", date_end="2026-01-01")
    with pytest.raises(ContractViolation, match="symbol"):
        _context(symbol="600000.SH", symbols=("000001.SZ",))
    with pytest.raises(ContractViolation, match="symbol"):
        _context(symbol=None, symbols=())


def test_run_spec_is_explicit_and_references_context_only():
    context = _context(workspace="strategy", strategy_id="template-trend")
    run = RunSpec(
        context_id=context.context_id,
        run_type="backtest",
        engine_id="offline_research",
        parameters={"commission_bps": 10, "slippage_bps": 2},
    )

    assert run.schema_version == RUN_SPEC_SCHEMA_VERSION
    assert run.run_id.startswith("run-")
    assert run.to_dict()["context_id"] == context.context_id
    assert run.to_dict()["execution_mode"] == "offline_research_simulation"


@pytest.mark.parametrize(
    "bad_parameters",
    [
        {"source_path": "D:/private/data.csv"},
        {"callback": lambda: None},
        {"nested": {"callable": print}},
        {"values": {1, 2, 3}},
        {"values": Path("D:/private/data.csv")},
    ],
)
def test_run_spec_rejects_paths_callables_and_non_json_values(bad_parameters):
    with pytest.raises(ContractViolation):
        RunSpec(
            context_id="ctx-valid123",
            run_type="backtest",
            engine_id="offline_research",
            parameters=bad_parameters,
        )


def test_run_spec_rejects_live_or_unknown_execution_engines():
    with pytest.raises(ContractViolation):
        RunSpec(
            context_id="ctx-valid123",
            run_type="backtest",
            engine_id="qmt",
            parameters={},
        )
    with pytest.raises(ContractViolation):
        RunSpec(
            context_id="ctx-valid123",
            run_type="unknown_run",
            engine_id="offline_research",
            parameters={},
        )


def test_legacy_parameters_adapt_to_context_and_run_without_extra_fields():
    params = {
        "page": "strategy",
        "dataset_id": "seeded_demo",
        "symbol": "600000.SH",
        "period": "daily",
        "as_of": date(2026, 2, 27),
        "indicators": [{"key": "MA"}, "RSI"],
        "strategy_id": "template-trend",
        "commission_bps": 10,
    }

    context = context_from_legacy_params(params)
    run = run_spec_from_legacy_params(params, context=context)

    assert context.workspace == "strategy"
    assert context.bar_period == "1d"
    assert context.indicator_ids == ("MA", "RSI")
    assert run.context_id == context.context_id
    assert run.parameters == {"commission_bps": 10}


def test_legacy_adapter_rejects_private_path_and_missing_required_as_of():
    with pytest.raises(ContractViolation):
        context_from_legacy_params({"data_path": "D:/private/data", "as_of": "2026-02-27"})
    with pytest.raises(ContractViolation):
        context_from_legacy_params({"dataset_id": "seeded_demo", "symbol": "600000.SH"})
