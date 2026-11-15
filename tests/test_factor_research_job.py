from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_compute import BASIC_FACTOR_SPECS
from portfolio_app.factor_workspace import FactorResearchConfig
from portfolio_app.factor_research_job import (
    FactorResearchJobError,
    FactorResearchJobService,
)
from portfolio_app.research_jobs import JobStatus


def bars(rows: int = 80, symbols: tuple[str, ...] = ("AAA", "BBB", "CCC")) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-02", periods=rows)
    output = []
    for symbol_index, symbol in enumerate(symbols):
        close = np.linspace(10.0 + symbol_index, 18.0 + symbol_index, rows)
        output.extend(
            {
                "trade_date": date,
                "symbol": symbol,
                "open": value - 0.1,
                "high": value + 0.4,
                "low": value - 0.4,
                "close": value,
                "vol": 1000.0 + index,
                "amount": value * (1000.0 + index),
            }
            for index, (date, value) in enumerate(zip(dates, close))
        )
    return pd.DataFrame(output)


def config() -> FactorResearchConfig:
    return FactorResearchConfig(
        factor_id="basic.return_20d",
        dataset_id="demo_dataset",
        date_start="2026-01-02",
        date_end="2026-04-24",
        label_horizon_sessions=5,
        quantiles=3,
        min_assets_per_date=3,
        max_missing_ratio=0.5,
        disclosure_mode="public_demo",
    )


def test_submit_runs_only_after_preflight_and_exposes_drilldown_blocks() -> None:
    service = FactorResearchJobService(specs=BASIC_FACTOR_SPECS)
    job = service.submit(bars(), config())

    assert job.status is JobStatus.SUCCEEDED
    assert job.result is not None
    result = job.result
    assert result["preflight"]["submittable"] is True
    assert set(result["overview"]) >= {"factor_id", "rows", "valid_ic_sessions", "portfolio_type"}
    assert {"ic_series", "group_returns", "turnover"}.issubset(result["analysis"])
    assert result['analysis']['correlation'] == {
        'status': 'unavailable', 'reason': 'single_factor', 'rows': []}
    assert 'factor_copy' not in str(result)
    assert result["analysis"]["group_returns"]["portfolio_type"] == "research_equal_weight"
    assert service.drilldown(result, trade_date="2026-02-02")["trade_date"] == "2026-02-02"
    assert service.drilldown(result, symbol="AAA")["symbol"] == "AAA"


def test_blocked_preflight_never_creates_a_successful_result() -> None:
    service = FactorResearchJobService(specs=BASIC_FACTOR_SPECS)
    bad = config()
    bad_frame = bars().drop(columns="close")

    job = service.submit(bad_frame, bad)

    assert job.status is JobStatus.FAILED
    assert job.result is None
    assert job.failure['code'] == 'INPUT_INVALID'


def test_cancelled_and_failed_jobs_do_not_commit_and_previous_success_is_retained() -> None:
    service = FactorResearchJobService(specs=BASIC_FACTOR_SPECS)
    first = service.submit(bars(), config())
    assert first.status is JobStatus.SUCCEEDED

    cancelled = service.submit(bars(), config(), cancel_before_run=True)
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.result is None
    assert service.last_success is not None

    failed = service.submit(bars(), config(), compute_override=lambda token: (_ for _ in ()).throw(RuntimeError("fixture failure")))
    assert failed.status is JobStatus.FAILED
    assert failed.result is None
    assert service.last_success == first.result


def test_drilldown_rejects_unknown_filters_and_mixed_run_results() -> None:
    service = FactorResearchJobService(specs=BASIC_FACTOR_SPECS)
    job = service.submit(bars(), config())

    with pytest.raises(FactorResearchJobError, match="date or symbol"):
        service.drilldown(job.result, trade_date="2026-02-02", symbol="AAA")
    with pytest.raises(FactorResearchJobError, match="not found"):
        service.drilldown(job.result, symbol="ZZZ")
