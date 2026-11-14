from __future__ import annotations

import pytest

from portfolio_app.factor_strategy_draft import (
    FactorStrategyDraftError,
    build_factor_strategy_draft,
)
from portfolio_app.factor_compute import BASIC_FACTOR_SPECS
from portfolio_app.factor_research_job import FactorResearchJobService
from portfolio_app.factor_research_job import FactorResearchJobError
from portfolio_app.factor_workspace import FactorResearchConfig
from portfolio_app.demo_datasets import generate_cross_section_demo


def factor_run() -> dict[str, object]:
    return {
        "run_id": "factor-run-001",
        "status": "succeeded",
        "config": {
            "factor_id": "basic.return_20d",
            "dataset_id": "demo_dataset",
            "data_version": "data-v1",
            "label_id": "forward-5d",
        },
        "overview": {"factor_id": "basic.return_20d", "source": "offline_research_simulation"},
        "result_contract": {
            "result_id": "factor-result-001",
            "engine_id": "factor_research",
            "engine_version": "1.0.0",
        },
    }


def test_factor_result_becomes_explicit_draft_with_traceable_source() -> None:
    draft = build_factor_strategy_draft(
        factor_run(), top_k=10, direction="long", rebalance_frequency="monthly"
    )

    assert draft["status"] == "draft"
    assert draft["strategy_type"] == "factor_rank"
    assert draft["selection"] == {
        "top_k": 10,
        "direction": "long",
        "rebalance_frequency": "monthly",
    }
    assert draft["source"] == {
        "factor_run_id": "factor-run-001",
        "factor_result_id": "factor-result-001",
        "factor_id": "basic.return_20d",
        "dataset_id": "demo_dataset",
        "data_version": "data-v1",
        "label_id": "forward-5d",
    }


def test_draft_requires_execution_confirmation_and_is_not_a_backtest_result() -> None:
    draft = build_factor_strategy_draft(factor_run(), top_k=5, direction="short", rebalance_frequency="weekly")

    assert draft["execution_policy"]["status"] == "requires_confirmation"
    assert draft["execution_policy"]["policy_id"] is None
    assert draft["backtest"]["status"] == "not_run"
    assert draft["backtest"]["result"] is None
    assert "fills" not in draft
    assert "ending_nav" not in draft


def test_draft_rejects_invalid_selection_and_non_successful_factor_run() -> None:
    with pytest.raises(FactorStrategyDraftError, match="top_k"):
        build_factor_strategy_draft(factor_run(), top_k=0)
    with pytest.raises(FactorStrategyDraftError, match="direction"):
        build_factor_strategy_draft(factor_run(), direction="flat")
    with pytest.raises(FactorStrategyDraftError, match="rebalance"):
        build_factor_strategy_draft(factor_run(), rebalance_frequency="intraday")

    failed = factor_run()
    failed["status"] = "failed"
    with pytest.raises(FactorStrategyDraftError, match="successful"):
        build_factor_strategy_draft(failed)


def test_draft_rejects_missing_source_identity() -> None:
    missing = factor_run()
    del missing["config"]
    with pytest.raises(FactorStrategyDraftError, match="source"):
        build_factor_strategy_draft(missing)


def test_factor_job_result_has_reproducible_identity_and_service_conversion() -> None:
    demo = generate_cross_section_demo(assets=30, sessions=80, seed=17)
    config = FactorResearchConfig(
        factor_id="basic.return_20d",
        dataset_id="demo_dataset",
        date_start=str(demo.frame["trade_date"].min().date()),
        date_end=str(demo.frame["trade_date"].max().date()),
        min_assets_per_date=30,
        max_missing_ratio=0.5,
        disclosure_mode="public_demo",
    )
    service = FactorResearchJobService(specs=BASIC_FACTOR_SPECS)
    job = service.submit(demo.frame, config)

    assert job.status.value == "succeeded"
    assert job.result is not None
    assert job.result["status"] == "succeeded"
    assert job.result["run_id"].startswith("factor-run-")
    assert job.result["config"]["data_version"].startswith("data-")
    draft = service.to_strategy_draft(job.result, top_k=12, direction="long_short")
    assert draft["source"]["factor_run_id"] == job.result["run_id"]
    assert draft["source"]["data_version"] == job.result["config"]["data_version"]


def test_m2_scale_demo_runs_and_small_or_constant_results_do_not_become_successful_drafts() -> None:
    demo = generate_cross_section_demo(assets=120, sessions=756, seed=29)
    config = FactorResearchConfig(
        factor_id="basic.return_20d",
        dataset_id="synthetic_cross_section_v1",
        date_start=str(demo.frame["trade_date"].min().date()),
        date_end=str(demo.frame["trade_date"].max().date()),
        min_assets_per_date=30,
        max_missing_ratio=0.5,
        disclosure_mode="public_demo",
    )
    service = FactorResearchJobService(specs=BASIC_FACTOR_SPECS)
    job = service.submit(demo.frame, config)
    assert job.status.value == "succeeded"
    assert service.to_strategy_draft(job.result)["status"] == "draft"

    small = config.__class__(**{**config.to_dict(), "min_assets_per_date": 200})
    blocked = service.submit(demo.frame, small)
    assert blocked.status.value == "failed"
    assert blocked.result is None

    constant = demo.frame.copy()
    constant["close"] = 100.0
    constant_job = service.submit(constant, config)
    assert constant_job.status.value in {"failed", "succeeded"}
    if constant_job.status.value == "succeeded":
        with pytest.raises(FactorResearchJobError, match="quality|constant|not suitable"):
            service.to_strategy_draft(constant_job.result)
