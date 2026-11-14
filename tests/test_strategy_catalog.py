from __future__ import annotations

import pytest

from portfolio_app.factor_strategy_draft import build_factor_strategy_draft
from portfolio_app.strategy_catalog import build_strategy_catalog


def factor_draft() -> dict[str, object]:
    return build_factor_strategy_draft(
        {
            "run_id": "factor-run-001",
            "status": "succeeded",
            "config": {
                "factor_id": "basic.return_20d",
                "dataset_id": "demo_dataset",
                "data_version": "data-v1",
                "label_id": "forward-5d",
            },
            "result_contract": {"result_id": "factor-result-001"},
        }
    )


def test_catalog_distinguishes_runnable_templates_drafts_private_evidence_and_review_states():
    catalog = build_strategy_catalog(
        factor_drafts=[factor_draft()],
        private_evidence=[
            {
                "model_id": "model1",
                "display_name": "私有策略证据 1",
                "status": "validated",
                "disclosure_mode": "private_local",
            },
            {
                "model_id": "model2",
                "display_name": "私有策略证据 2",
                "status": "review_required",
                "disclosure_mode": "private_local",
            },
        ],
        unavailable=[{"strategy_id": "private-model-3", "display_name": "未开放策略"}],
    )

    by_id = {item["strategy_id"]: item for item in catalog}

    assert {by_id[key]["status"] for key in ("trend", "mean_reversion", "quality_momentum")} == {"runnable"}
    draft = by_id["factor_draft:factor-run-001"]
    assert draft["status"] == "draft_requires_confirmation"
    assert draft["capabilities"] == ["review", "configure"]
    assert by_id["model1"]["status"] == "read_only"
    assert by_id["model1"]["capabilities"] == ["view_evidence"]
    assert by_id["model2"]["status"] == "review_required"
    assert by_id["model2"]["capabilities"] == ["view_evidence", "review"]
    assert by_id["private-model-3"]["status"] == "display_only"
    assert by_id["private-model-3"]["capabilities"] == ["view_summary"]


def test_catalog_does_not_turn_private_evidence_into_a_runnable_strategy_or_expose_payloads():
    catalog = build_strategy_catalog(
        private_evidence=[
            {
                "model_id": "model2",
                "display_name": "Model 2",
                "status": "review_required",
                "disclosure_mode": "private_local",
                "private_path": "D:/secret/model2",
                "parameters": {"hidden": 1},
            }
        ]
    )

    record = next(item for item in catalog if item["strategy_id"] == "model2")
    assert record["status"] == "review_required"
    assert "private_path" not in record
    assert "parameters" not in record
    assert "backtest" not in record["capabilities"]


def test_catalog_rejects_invalid_status_and_duplicate_strategy_ids():
    with pytest.raises(ValueError, match="status"):
        build_strategy_catalog(private_evidence=[{"model_id": "bad", "status": "runnable"}])

    with pytest.raises(ValueError, match="duplicate"):
        build_strategy_catalog(
            unavailable=[{"strategy_id": "trend", "display_name": "duplicate"}]
        )
