from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from portfolio_app.restricted_expressions import (
    ExpressionBudget,
    ExpressionCompileError,
    compile_expression,
    evaluate_expression,
)


def market_frame(rows: int = 8) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-02", periods=rows)
    close = np.arange(10.0, 10.0 + rows)
    return pd.DataFrame(
        {
            "trade_date": list(dates) * 2,
            "symbol": ["AAA"] * rows + ["BBB"] * rows,
            "open": np.concatenate([close - 0.2, close + 4.8]),
            "high": np.concatenate([close + 0.5, close + 5.5]),
            "low": np.concatenate([close - 0.5, close + 4.5]),
            "close": np.concatenate([close, close + 5.0]),
            "vol": np.concatenate([np.arange(100.0, 100.0 + rows), np.arange(200.0, 200.0 + rows)]),
        }
    )


def test_safe_tree_evaluates_arithmetic_and_boolean_conditions() -> None:
    expression = compile_expression(
        {
            "kind": "boolean",
            "op": "and",
            "operands": [
                {
                    "kind": "compare",
                    "op": "gt",
                    "left": {"kind": "field", "name": "close"},
                    "right": {"kind": "literal", "value": 10},
                },
                {
                    "kind": "compare",
                    "op": "lt",
                    "left": {"kind": "field", "name": "close"},
                    "right": {"kind": "literal", "value": 14},
                },
            ],
        },
        allowed_fields={"close"},
    )

    result = evaluate_expression(expression, market_frame().iloc[:8])

    assert result.dtype == bool
    assert result.tolist() == [False, True, True, True, False, False, False, False]
    serialized = expression.to_dict()
    assert serialized["tree"]["kind"] == "boolean"
    assert serialized["tree"]["operands"][0]["left"] == {"kind": "field", "name": "close"}
    assert "callable" not in repr(serialized)


def test_text_conditions_are_parsed_to_the_same_safe_tree() -> None:
    expression = compile_expression("(close - open) / open > 0.05", allowed_fields={"close", "open"})

    result = evaluate_expression(expression, market_frame().iloc[:8])

    assert result.tolist() == [False] * 8
    assert expression.fields == ("close", "open")


def test_rolling_operator_is_symbol_aware_and_does_not_use_future_rows() -> None:
    frame = market_frame()
    expression = compile_expression(
        {"kind": "rolling", "op": "mean", "window": 3, "operand": {"kind": "field", "name": "close"}},
        allowed_fields={"close"},
    )

    result = evaluate_expression(expression, frame)

    assert result.iloc[0:2].isna().all()
    assert result.iloc[2] == pytest.approx(11.0)
    assert result.iloc[8:10].isna().all()
    assert result.iloc[10] == pytest.approx(16.0)
    changed = frame.copy()
    changed.loc[7, "close"] = 10000.0
    changed_result = evaluate_expression(expression, changed)
    assert changed_result.iloc[0:7].equals(result.iloc[0:7])


def test_registered_indicator_node_uses_shared_indicator_math() -> None:
    frame = market_frame()
    expression = compile_expression(
        {
            "kind": "indicator",
            "name": "MA",
            "params": {"period": 3},
        },
        allowed_fields={"close", "high", "low", "vol"},
    )

    result = evaluate_expression(expression, frame.iloc[:8])

    assert result.iloc[2] == pytest.approx(11.0)
    assert result.iloc[3] == pytest.approx(12.0)
    assert expression.indicators == ("MA",)


def test_registered_indicator_is_evaluated_per_symbol_without_crossing_boundaries() -> None:
    frame = market_frame()
    expression = compile_expression(
        {"kind": "indicator", "name": "MA", "params": {"period": 3}},
        allowed_fields={"close", "high", "low", "vol"},
    )

    result = evaluate_expression(expression, frame)

    assert result.iloc[7] == pytest.approx(16.0)
    assert result.iloc[8] == pytest.approx(15.0)
    assert result.iloc[9] == pytest.approx(15.5)
    assert result.iloc[10] == pytest.approx(16.0)


def test_indicator_result_preserves_nonconsecutive_input_index() -> None:
    frame = market_frame().iloc[[4, 0, 9, 1, 5, 2, 10, 3, 6, 7, 8, 11]].copy()
    frame.index = [101, 7, 205, 12, 309, 14, 408, 18, 501, 22, 607, 25]
    expression = compile_expression(
        {"kind": "indicator", "name": "MA", "params": {"period": 3}},
        allowed_fields={"close", "high", "low", "vol"},
    )

    result = evaluate_expression(expression, frame)

    assert result.index.tolist() == frame.index.tolist()
    assert result.loc[25] == pytest.approx(17.0)


def test_expression_budget_reports_and_limits_resources() -> None:
    expression = compile_expression(
        {
            "kind": "rolling",
            "op": "mean",
            "window": 20,
            "operand": {"kind": "field", "name": "close"},
        },
        allowed_fields={"close"},
        budget=ExpressionBudget(max_window=30, max_nodes=4),
    )

    assert expression.node_count == 2
    assert expression.max_depth == 2
    assert expression.windows == (20,)
    with pytest.raises(ExpressionCompileError, match="window"):
        compile_expression(
            {"kind": "rolling", "op": "mean", "window": 31, "operand": {"kind": "field", "name": "close"}},
            allowed_fields={"close"},
            budget=ExpressionBudget(max_window=30),
        )


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo unsafe')",
        "close.__class__",
        "close[0]",
        "eval('close')",
        "open('private.csv')",
    ],
)
def test_text_parser_rejects_calls_attributes_subscripts_and_code_injection(expression: str) -> None:
    with pytest.raises(ExpressionCompileError):
        compile_expression(expression, allowed_fields={"close"})


def test_tree_rejects_unknown_fields_private_names_and_arbitrary_objects() -> None:
    with pytest.raises(ExpressionCompileError, match="field"):
        compile_expression({"kind": "field", "name": "private_formula"}, allowed_fields={"close"})
    with pytest.raises(ExpressionCompileError, match="operator"):
        compile_expression({"kind": "binary", "op": "power", "left": {"kind": "field", "name": "close"}, "right": {"kind": "literal", "value": 2}}, allowed_fields={"close"})
    with pytest.raises(ExpressionCompileError, match="literal"):
        compile_expression({"kind": "literal", "value": object()}, allowed_fields=set())
    with pytest.raises(ExpressionCompileError, match="unknown"):
        compile_expression({"kind": "field", "name": "close", "private_expression": "secret"}, allowed_fields={"close"})


def test_indicator_and_rolling_operator_whitelists_fail_closed() -> None:
    with pytest.raises(ExpressionCompileError, match="indicator"):
        compile_expression({"kind": "indicator", "name": "PRIVATE_FORMULA", "params": {}}, allowed_fields={"close"})
    with pytest.raises(ExpressionCompileError, match="operator"):
        compile_expression({"kind": "rolling", "op": "apply", "window": 3, "operand": {"kind": "field", "name": "close"}}, allowed_fields={"close"})
    with pytest.raises(ExpressionCompileError, match="parameter"):
        compile_expression({"kind": "indicator", "name": "MA", "params": {"period": 3, "private": 1}}, allowed_fields={"close"})


def test_expression_does_not_read_paths_or_execute_environment_values(tmp_path) -> None:
    marker = tmp_path / "marker.txt"
    os.environ["RESTRICTED_EXPRESSION_MARKER"] = str(marker)
    with pytest.raises(ExpressionCompileError):
        compile_expression({"kind": "literal", "value": str(marker)}, allowed_fields=set())
    assert not marker.exists()
