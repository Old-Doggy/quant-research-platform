from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.strategy_rules import (
    RuleValidationError,
    compile_strategy_rules,
    evaluate_strategy_rules,
)


FIELDS = {
    "close": "price",
    "open": "price",
    "volume": "volume",
    "ret20": "return",
    "score": "score",
}


def market_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["A", "A", "A", "A", "B", "B", "B", "B"],
            "trade_date": pd.date_range("2024-01-01", periods=4).tolist() * 2,
            "close": [10.0, 11.0, 12.0, 11.0, 10.0, 9.0, 10.0, 12.0],
            "open": [9.5, 10.5, 11.5, 11.5, 10.5, 9.5, 9.5, 11.5],
            "high": [10.5, 11.5, 12.5, 11.5, 10.5, 9.5, 10.5, 12.5],
            "low": [9.0, 10.0, 11.0, 10.5, 9.5, 8.5, 9.5, 11.5],
            "volume": [100, 120, 130, 140, 110, 115, 125, 150],
            "ret20": [0.1, 0.2, 0.3, 0.1, -0.1, -0.2, 0.1, 0.4],
            "score": [1.0, 2.0, 3.0, 2.0, 0.5, 1.5, 2.5, 4.0],
        }
    )


def test_buy_and_sell_rules_compile_separately_and_evaluate_to_reasonable_signals():
    rules = compile_strategy_rules(
        buy_rule={
            "type": "logic",
            "operator": "AND",
            "conditions": [
                {"type": "threshold", "field": "close", "operator": ">", "value": 10},
                {
                    "type": "cross",
                    "left": "close",
                    "right": {"kind": "indicator", "name": "MA", "params": {"period": 2}},
                    "direction": "up",
                },
            ],
        },
        sell_rule={"type": "threshold", "field": "close", "operator": "<", "value": 10},
        field_types=FIELDS,
    )

    result = evaluate_strategy_rules(rules, market_frame())

    assert result.columns.tolist() == ["buy", "sell"]
    assert result["buy"].dtype == bool
    assert result["sell"].dtype == bool
    assert result["sell"].tolist() == [False, False, False, False, False, True, False, False]
    assert rules.to_dict()["buy"]["type"] == "logic"
    assert rules.to_dict()["sell"]["type"] == "threshold"


def test_logic_supports_or_and_rank_conditions_with_explicit_direction():
    rules = compile_strategy_rules(
        buy_rule={
            "type": "logic",
            "operator": "OR",
            "conditions": [
                {"type": "rank", "field": "score", "direction": "top", "limit": 1},
                {"type": "threshold", "field": "ret20", "operator": ">=", "value": 0.3},
            ],
        },
        sell_rule={"type": "rank", "field": "score", "direction": "bottom", "limit": 1},
        field_types=FIELDS,
    )

    result = evaluate_strategy_rules(rules, market_frame())

    assert result["buy"].tolist() == [True, True, True, False, False, False, False, True]
    assert result["sell"].tolist() == [False, False, False, True, True, True, True, False]


@pytest.mark.parametrize(
    "rule,match",
    [
        ({"type": "threshold", "field": "secret", "operator": ">", "value": 1}, "field"),
        ({"type": "threshold", "field": "volume", "operator": ">", "value": "1"}, "numeric"),
        ({"type": "threshold", "field": "close", "operator": "contains", "value": 1}, "operator"),
        ({"type": "cross", "left": "close", "right": "open", "direction": "sideways"}, "direction"),
        ({"type": "rank", "field": "score", "direction": "top", "limit": 0}, "limit"),
        ({"type": "logic", "operator": "XOR", "conditions": []}, "operator"),
    ],
)
def test_rule_validation_rejects_unknown_fields_bad_types_and_invalid_direction(rule, match):
    with pytest.raises(RuleValidationError, match=match):
        compile_strategy_rules(rule, rule, field_types=FIELDS)


@pytest.mark.parametrize("expression", ["__import__('os').system('x')", "close.__class__", "eval('close')"])
def test_rule_expressions_reject_arbitrary_code(expression: str):
    with pytest.raises(RuleValidationError):
        compile_strategy_rules(
            {"type": "cross", "left": expression, "right": "close", "direction": "up"},
            {"type": "threshold", "field": "close", "operator": ">", "value": 1},
            field_types=FIELDS,
        )


def test_buy_and_sell_rules_are_required_and_cannot_be_implicitly_reused():
    with pytest.raises(RuleValidationError, match="buy_rule"):
        compile_strategy_rules(None, {"type": "threshold", "field": "close", "operator": ">", "value": 1}, field_types=FIELDS)
    with pytest.raises(RuleValidationError, match="sell_rule"):
        compile_strategy_rules({"type": "threshold", "field": "close", "operator": ">", "value": 1}, None, field_types=FIELDS)
