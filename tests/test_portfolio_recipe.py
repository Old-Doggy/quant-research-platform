from __future__ import annotations

import math
import json

import pytest


def _recipe(**overrides):
    value = {
        "recipe_id": "demo-recipe-v1",
        "target_weights": {"AAA": 0.55, "BBB": 0.25},
        "cash_weight": 0.20,
        "lower_bounds": {"AAA": 0.20, "BBB": 0.0},
        "upper_bounds": {"AAA": 0.70, "BBB": 0.60},
        "lot_size": 100,
        "min_rebalance_weight": 0.05,
        "missing_leg_policy": "preserve_cash",
        "schema_version": "portfolio-recipe.v1",
    }
    value.update(overrides)
    return value


def test_portfolio_recipe_is_explicit_round_trippable_and_constraint_aware():
    from portfolio_app.portfolio_recipe import PortfolioRecipe, resolve_portfolio_recipe

    recipe = PortfolioRecipe.from_dict(_recipe())
    assert recipe.to_dict() == _recipe()
    assert recipe.schema_version == "portfolio-recipe.v1"
    assert recipe.total_declared_weight == pytest.approx(1.0)
    assert recipe.lower_bounds["AAA"] == pytest.approx(0.20)
    assert recipe.upper_bounds["BBB"] == pytest.approx(0.60)
    restored = PortfolioRecipe.from_json(recipe.to_json())
    assert restored.to_dict() == recipe.to_dict()
    assert json.loads(recipe.to_json())["schema_version"] == "portfolio-recipe.v1"

    resolved = resolve_portfolio_recipe(recipe, available_symbols={"AAA", "BBB"})
    assert resolved.weights == {"AAA": 0.55, "BBB": 0.25}
    assert resolved.cash_weight == pytest.approx(0.20)
    assert resolved.missing_symbols == ()
    assert resolved.status == "ready"
    assert resolved.cash_delta == pytest.approx(0.0)
    assert resolved.constraint_status == "within_bounds"
    assert resolved.constraint_violations == ()


def test_portfolio_recipe_rejects_invalid_sum_bounds_lot_threshold_and_policy():
    from portfolio_app.portfolio_recipe import PortfolioRecipe

    with pytest.raises(ValueError, match="sum to 1"):
        PortfolioRecipe.from_dict(_recipe(cash_weight=0.10))
    with pytest.raises(ValueError, match="lower bound"):
        PortfolioRecipe.from_dict(_recipe(lower_bounds={"AAA": 0.60, "BBB": 0.0}))
    with pytest.raises(ValueError, match="upper bound"):
        PortfolioRecipe.from_dict(_recipe(upper_bounds={"AAA": 0.50, "BBB": 0.60}))
    with pytest.raises(ValueError, match="lot_size"):
        PortfolioRecipe.from_dict(_recipe(lot_size=0))
    with pytest.raises(ValueError, match="min_rebalance_weight"):
        PortfolioRecipe.from_dict(_recipe(min_rebalance_weight=-0.1))
    with pytest.raises(ValueError, match="missing_leg_policy"):
        PortfolioRecipe.from_dict(_recipe(missing_leg_policy="silently_drop"))
    with pytest.raises(ValueError, match="finite"):
        PortfolioRecipe.from_dict(_recipe(target_weights={"AAA": math.inf, "BBB": 0.25}, cash_weight=0.0))


def test_portfolio_recipe_missing_leg_policy_keeps_outcome_explicit():
    from portfolio_app.portfolio_recipe import PortfolioRecipe, resolve_portfolio_recipe

    recipe = PortfolioRecipe.from_dict(_recipe())
    with pytest.raises(ValueError, match="missing portfolio legs"):
        resolve_portfolio_recipe(recipe, available_symbols={"AAA"}, policy="fail")

    preserved = resolve_portfolio_recipe(recipe, available_symbols={"AAA"}, policy="preserve_cash")
    assert preserved.weights == {"AAA": 0.55}
    assert preserved.cash_weight == pytest.approx(0.45)
    assert preserved.missing_symbols == ("BBB",)
    assert preserved.status == "preserved_cash"
    assert preserved.cash_delta == pytest.approx(0.25)
    assert preserved.constraint_status == "within_bounds"

    renormalized = resolve_portfolio_recipe(recipe, available_symbols={"AAA"}, policy="renormalize")
    assert renormalized.weights == {"AAA": 0.80}
    assert renormalized.cash_weight == pytest.approx(0.20)
    assert renormalized.status == "renormalized"
    assert renormalized.constraint_status == "violated"
    assert renormalized.constraint_violations == ("AAA exceeds upper bound 0.7",)


def test_portfolio_recipe_minimum_rebalance_is_visible_and_does_not_silently_change_targets():
    from portfolio_app.portfolio_recipe import PortfolioRecipe, resolve_rebalance_targets

    recipe = PortfolioRecipe.from_dict(_recipe(min_rebalance_weight=0.05))
    resolved = resolve_rebalance_targets(recipe, {"AAA": 0.49, "BBB": 0.28, "现金": 0.20})
    assert resolved["AAA"] == pytest.approx(0.55)
    assert resolved["BBB"] == pytest.approx(0.28)
    assert resolved["现金"] == pytest.approx(0.17)
    assert resolved["diagnostics"]["minimum_rebalance_weight"] == pytest.approx(0.05)
    assert resolved["diagnostics"]["suppressed_symbols"] == ("BBB",)
    assert resolved["diagnostics"]["applied_symbols"] == ("AAA",)
    assert resolved["diagnostics"]["cash_delta"] == pytest.approx(-0.03)
    assert resolved["diagnostics"]["constraint_status"] == "within_bounds"
