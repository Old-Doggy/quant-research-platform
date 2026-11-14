"""Explicit portfolio recipe and constraint resolution for offline research."""
from __future__ import annotations

from dataclasses import dataclass
import math
import json
from typing import Mapping


POLICIES = {"fail", "preserve_cash", "renormalize"}


def _weights(value: Mapping[str, object], label: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{label} must be a non-empty mapping")
    result: dict[str, float] = {}
    for symbol, raw in value.items():
        number = float(raw)
        if not math.isfinite(number) or number < 0 or number > 1:
            raise ValueError(f"{label} must contain finite weights between 0 and 1")
        result[str(symbol)] = number
    return result


def _optional_weights(value: Mapping[str, object] | None, label: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    result: dict[str, float] = {}
    for symbol, raw in value.items():
        number = float(raw)
        if not math.isfinite(number) or number < 0 or number > 1:
            raise ValueError(f"{label} must contain finite values between 0 and 1")
        result[str(symbol)] = number
    return result


@dataclass(frozen=True)
class PortfolioRecipe:
    recipe_id: str
    target_weights: dict[str, float]
    cash_weight: float
    lower_bounds: dict[str, float]
    upper_bounds: dict[str, float]
    lot_size: int
    min_rebalance_weight: float
    missing_leg_policy: str
    schema_version: str = "portfolio-recipe.v1"

    @property
    def total_declared_weight(self) -> float:
        return sum(self.target_weights.values()) + self.cash_weight

    def __post_init__(self) -> None:
        if not self.recipe_id.strip():
            raise ValueError("recipe_id is required")
        if self.schema_version != "portfolio-recipe.v1":
            raise ValueError("schema_version is invalid")
        if not math.isfinite(self.cash_weight) or not 0 <= self.cash_weight <= 1:
            raise ValueError("cash_weight must be finite and between 0 and 1")
        if any(not math.isfinite(value) or value < 0 for value in self.target_weights.values()):
            raise ValueError("target_weights must contain finite non-negative values")
        if not math.isclose(self.total_declared_weight, 1.0, abs_tol=1e-9):
            raise ValueError("target weights and cash must sum to 1")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        if not math.isfinite(self.min_rebalance_weight) or self.min_rebalance_weight < 0 or self.min_rebalance_weight > 1:
            raise ValueError("min_rebalance_weight must be finite and between 0 and 1")
        if self.missing_leg_policy not in POLICIES:
            raise ValueError("missing_leg_policy is invalid")
        symbols = set(self.target_weights) | set(self.lower_bounds) | set(self.upper_bounds)
        for symbol in symbols:
            lower = self.lower_bounds.get(symbol, 0.0)
            upper = self.upper_bounds.get(symbol, 1.0)
            target = self.target_weights.get(symbol, 0.0)
            if lower > upper:
                raise ValueError(f"lower bound cannot exceed upper bound for {symbol}")
            if target < lower - 1e-12:
                raise ValueError(f"target weight is below lower bound for {symbol}")
            if target > upper + 1e-12:
                raise ValueError(f"target weight exceeds upper bound for {symbol}")

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PortfolioRecipe":
        if not isinstance(payload, Mapping):
            raise ValueError("portfolio recipe must be a mapping")
        return cls(
            recipe_id=str(payload.get("recipe_id", "")),
            target_weights=_weights(payload.get("target_weights", {}), "target_weights"),
            cash_weight=float(payload.get("cash_weight", 0.0)),
            lower_bounds=_optional_weights(payload.get("lower_bounds"), "lower_bounds"),
            upper_bounds=_optional_weights(payload.get("upper_bounds"), "upper_bounds"),
            lot_size=int(payload.get("lot_size", 1)),
            min_rebalance_weight=float(payload.get("min_rebalance_weight", 0.0)),
            missing_leg_policy=str(payload.get("missing_leg_policy", "fail")),
            schema_version=str(payload.get("schema_version", "portfolio-recipe.v1")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "target_weights": dict(self.target_weights),
            "cash_weight": self.cash_weight,
            "lower_bounds": dict(self.lower_bounds),
            "upper_bounds": dict(self.upper_bounds),
            "lot_size": self.lot_size,
            "min_rebalance_weight": self.min_rebalance_weight,
            "missing_leg_policy": self.missing_leg_policy,
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        """Serialize the recipe as stable, human-readable JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "PortfolioRecipe":
        if not isinstance(payload, str) or not payload.strip():
            raise ValueError("portfolio recipe JSON must be a non-empty string")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("portfolio recipe JSON is invalid") from exc
        return cls.from_dict(value)


@dataclass(frozen=True)
class ResolvedPortfolioRecipe:
    weights: dict[str, float]
    cash_weight: float
    missing_symbols: tuple[str, ...]
    status: str
    cash_delta: float
    constraint_status: str
    constraint_violations: tuple[str, ...]


def _constraint_diagnostics(
    recipe: PortfolioRecipe,
    weights: Mapping[str, float],
) -> tuple[str, tuple[str, ...]]:
    violations: list[str] = []
    for symbol, value in weights.items():
        lower = recipe.lower_bounds.get(symbol, 0.0)
        upper = recipe.upper_bounds.get(symbol, 1.0)
        if value < lower - 1e-12:
            violations.append(f"{symbol} below lower bound {lower:g}")
        elif value > upper + 1e-12:
            violations.append(f"{symbol} exceeds upper bound {upper:g}")
    return ("within_bounds" if not violations else "violated", tuple(violations))


def resolve_portfolio_recipe(
    recipe: PortfolioRecipe,
    available_symbols: set[str],
    *,
    policy: str | None = None,
) -> ResolvedPortfolioRecipe:
    selected_policy = policy or recipe.missing_leg_policy
    if selected_policy not in POLICIES:
        raise ValueError("missing_leg_policy is invalid")
    available = {str(symbol) for symbol in available_symbols}
    missing = tuple(sorted(set(recipe.target_weights) - available))
    if missing and selected_policy == "fail":
        raise ValueError(f"missing portfolio legs: {', '.join(missing)}")
    weights = {symbol: value for symbol, value in recipe.target_weights.items() if symbol in available}
    cash = recipe.cash_weight
    if selected_policy == "preserve_cash" and missing:
        cash += sum(recipe.target_weights[symbol] for symbol in missing)
        status = "preserved_cash"
    elif selected_policy == "renormalize" and missing:
        declared = sum(recipe.target_weights.values())
        available_total = sum(weights.values())
        if available_total <= 0:
            raise ValueError("cannot renormalize an empty portfolio")
        scale = declared / available_total
        weights = {symbol: round(value * scale, 12) for symbol, value in weights.items()}
        status = "renormalized"
    else:
        status = "ready"
    constraint_status, constraint_violations = _constraint_diagnostics(recipe, weights)
    resolved_cash = float(cash)
    return ResolvedPortfolioRecipe(
        weights=weights,
        cash_weight=resolved_cash,
        missing_symbols=missing,
        status=status,
        cash_delta=resolved_cash - recipe.cash_weight,
        constraint_status=constraint_status,
        constraint_violations=constraint_violations,
    )


def resolve_rebalance_targets(
    recipe: PortfolioRecipe,
    current_weights: Mapping[str, float],
) -> dict[str, object]:
    # A suppressed leg keeps its current exposure.  The resulting cash weight
    # is then the residual required to keep the resolved recipe normalized.
    # This makes the effect of the threshold explicit without inventing an
    # order for a change smaller than the configured minimum.
    resolved_weights: dict[str, float] = {}
    suppressed: list[str] = []
    applied: list[str] = []
    for symbol, target in recipe.target_weights.items():
        current = float(current_weights.get(symbol, 0.0))
        delta = target - current
        if abs(delta) < recipe.min_rebalance_weight:
            suppressed.append(symbol)
            resolved_weights[symbol] = current
        else:
            resolved_weights[symbol] = target
            applied.append(symbol)
    cash_weight = 1.0 - sum(resolved_weights.values())
    if cash_weight < -1e-9:
        raise ValueError("resolved portfolio weights exceed 1")
    return {
        **resolved_weights,
        "现金": max(0.0, cash_weight),
        "diagnostics": {
            "minimum_rebalance_weight": recipe.min_rebalance_weight,
            "suppressed_symbols": tuple(suppressed),
            "applied_symbols": tuple(applied),
            "cash_delta": cash_weight - recipe.cash_weight,
            "constraint_status": _constraint_diagnostics(recipe, resolved_weights)[0],
            "constraint_violations": _constraint_diagnostics(recipe, resolved_weights)[1],
        },
    }
