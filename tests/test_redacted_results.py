from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from portfolio_app.redacted_results import (
    REDACTED_RESULT_COLUMNS,
    load_redacted_model7_results,
    load_redacted_results,
    redact_result_frame,
    validate_redacted_input,
)


ROOT = Path(__file__).resolve().parents[1]


def test_redaction_keeps_only_aggregate_public_fields():
    raw = pd.DataFrame(
        [
            {
                "model": "model1",
                "evidence_case": "base",
                "asset_scope": "股票横截面",
                "status": "validated",
                "status_label": "正式成本压力测试",
                "period": "2016-01-01至2020-01-01",
                "annual_return": 0.12,
                "sharpe": 0.8,
                "max_drawdown": -0.2,
                "cost_assumption": "基线成本",
                "source": r"D:\private\model1\manifest.json",
                "limitations": "仅展示聚合结果",
                "exact_parameters": "secret",
                "target_positions": "AAA:0.1",
                "account_id": "account-1",
            }
        ]
    )

    redacted = redact_result_frame(raw)

    assert list(redacted.columns) == REDACTED_RESULT_COLUMNS
    assert len(redacted) == 1
    assert redacted.loc[0, "source_label"] == "curated research summary"
    assert "private" not in redacted.to_string().lower()
    assert "manifest" not in redacted.to_string().lower()
    assert "AAA" not in redacted.to_string()
    assert "account" not in redacted.to_string().lower()


def test_redacted_workspace_loader_keeps_review_states_and_model7_layers():
    results = load_redacted_results(ROOT)
    model7 = load_redacted_model7_results(ROOT)

    assert {row["model"] for row in results} == {f"model{number}" for number in range(1, 7)}
    assert all(row["source_label"] == "curated research summary" for row in results)
    assert {row["status"] for row in results if row["model"] in {"model2", "model6"}} == {"review_required"}
    assert {row["evidence_case"] for row in model7} == {
        "selection_validation",
        "latest_local_backtest",
        "runtime_state",
    }
    runtime = next(row for row in model7 if row["evidence_case"] == "runtime_state")
    assert pd.isna(runtime["annual_return"])
    assert pd.isna(runtime["sharpe"])
    assert pd.isna(runtime["max_drawdown"])


def test_redacted_loader_returns_empty_when_public_evidence_is_absent():
    with TemporaryDirectory(prefix="redacted_missing_", dir=ROOT) as temporary:
        missing_root = Path(temporary)
        assert load_redacted_results(missing_root) == []
        assert load_redacted_model7_results(missing_root) == []


def test_redacted_input_contract_rejects_private_fields_and_bad_sources():
    valid = pd.DataFrame(
        columns=[
            "model",
            "evidence_case",
            "asset_scope",
            "status",
            "status_label",
            "period",
            "annual_return",
            "sharpe",
            "max_drawdown",
            "cost_assumption",
            "limitations",
            "source",
        ]
    )
    validate_redacted_input(valid)

    private = valid.assign(target_positions="AAA:0.1")
    try:
        validate_redacted_input(private)
    except ValueError as exc:
        assert "target_positions" in str(exc)
    else:
        raise AssertionError("private result fields must be rejected")

    bad_source = valid.iloc[:1].copy()
    bad_source.loc[0, "source"] = "D:/private/result.csv"
    try:
        validate_redacted_input(bad_source)
    except ValueError as exc:
        assert "curated public label" in str(exc)
    else:
        raise AssertionError("private source labels must be rejected")
