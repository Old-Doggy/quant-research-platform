from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PortfolioResearchResult:
    frame: pd.DataFrame
    attribution: pd.DataFrame
    trade_events: list[dict[str, object]]
    weights: dict[str, float]
    cash_weight: float
    diagnostics: dict[str, object]
