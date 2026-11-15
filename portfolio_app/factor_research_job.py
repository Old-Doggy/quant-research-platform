"""Explicit factor-research submission, analysis blocks and drilldown service."""
from __future__ import annotations

from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from .factor_analysis import align_factor_labels, compute_ic_series
from .factor_compute import compute_basic_factors
from .factor_contracts import FactorSpec, LabelSpec
from .factor_group_analysis import build_quantile_groups, compute_group_returns, compute_group_turnover
from .factor_labels import build_forward_labels
from .factor_research_result import build_factor_research_result
from .factor_strategy_draft import build_factor_strategy_draft
from .factor_workspace import FactorResearchConfig, preflight_factor_research
from .research_jobs import CancellationToken, JobStatus, ResearchJob, ResearchJobCoordinator
from .research_result_cache import ResearchResultCache, build_data_fingerprint, build_research_cache_key
from .research_manifest import build_run_manifest
from .research_integrity import audit_research_input, audit_labels, assert_causal_prefix
from .research_display import check_research_size


def _archive_values(value):
    """Preserve unavailable observations as JSON null, never as zero."""
    if isinstance(value, dict):
        return {key: _archive_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_archive_values(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _archive_values(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is pd.NaT:
        return None
    return value


class FactorResearchJobError(ValueError):
    """Raised when a result drilldown or factor job request is invalid."""


class FactorResearchJobService:
    """Submit one explicit factor job and expose stable result drilldowns."""

    def __init__(self, *, specs: Iterable[FactorSpec]) -> None:
        self.specs = tuple(specs)
        self.cache = ResearchResultCache()
        self.coordinator = ResearchJobCoordinator(self.cache)
        self.last_success: dict[str, Any] | None = None

    def submit(
        self,
        frame: pd.DataFrame,
        config: FactorResearchConfig,
        *,
        cancel_before_run: bool = False,
        compute_override: Callable[[CancellationToken], dict[str, Any]] | None = None,
        token: CancellationToken | None = None,
    ) -> ResearchJob:
        check_research_size(frame)
        external_token = token
        if external_token:
            external_token.report(.05, 'preflight')
        preflight = preflight_factor_research(frame, config, specs=self.specs)
        key = build_research_cache_key(
            dataset_id=config.dataset_id,
            data_version=build_data_fingerprint(frame),
            processing={**config.to_dict(), 'timing': frame.attrs.get('research_timing', {}),
                        'specs': [str(s) for s in self.specs]},
            engine_id="factor_research.v1",
        )
        if not preflight.submittable:
            queued = self.coordinator.create_job(key)
            return self.coordinator.run(queued.job_id, lambda token: (_ for _ in ()).throw(FactorResearchJobError(f"preflight blocked: {'; '.join(preflight.errors)}")))
        if cancel_before_run:
            queued = self.coordinator.create_job(key)
            return self.coordinator.cancel(queued.job_id)

        selected = next(spec for spec in self.specs if spec.factor_id == config.factor_id)

        try:
            audit_research_input(frame, feature_fields=selected.input_fields)
        except ValueError:
            # A cached success must not bypass newly supplied provenance errors.
            queued = self.coordinator.create_job(key)
            return self.coordinator.run(queued.job_id, lambda token: audit_research_input(frame, feature_fields=selected.input_fields))

        def compute(inner_token: CancellationToken) -> dict[str, Any]:
            token = external_token or inner_token
            audit_research_input(frame, feature_fields=selected.input_fields)
            if compute_override is not None:
                return compute_override(token)
            return self._compute(
                frame,
                config,
                preflight,
                token,
                data_version=key.data_version,
                run_id=f"factor-run-{key.key_id.removeprefix('cache-')}",
            )

        if external_token is not None:
            # The outer runner owns commit; no nested success can survive a
            # cancellation after this calculation but before outer submission.
            result = compute(external_token)
            external_token.checkpoint()
            return ResearchJob(job_id='background-factor', key=key, status=JobStatus.SUCCEEDED, result=result)
        if compute_override is not None:
            queued = self.coordinator.create_job(key)
            job = self.coordinator.run(queued.job_id, compute)
        else:
            job = self.coordinator.submit(key, compute)
        if job.status is JobStatus.SUCCEEDED:
            self.last_success = dict(job.result or {})
        return job

    def _compute(
        self,
        frame: pd.DataFrame,
        config: FactorResearchConfig,
        preflight: Any,
        token: CancellationToken,
        *,
        data_version: str,
        run_id: str,
    ) -> dict[str, Any]:
        token.report(.12, 'features')
        selected = next(spec for spec in self.specs if spec.factor_id == config.factor_id)
        integrity = audit_research_input(frame, feature_fields=selected.input_fields)
        factor_frame = compute_basic_factors(frame.copy(deep=True), factor_ids={config.factor_id})
        output_column = config.factor_id.split('.', 1)[-1]
        prefix = assert_causal_prefix(frame, lambda f: compute_basic_factors(
            f, factor_ids={config.factor_id})[output_column])
        token.report(.3, 'labels')
        label_spec = LabelSpec(
            label_id=f"forward-{config.label_horizon_sessions}d",
            version="1.0.0",
            prediction_direction="forward_return",
            horizon_sessions=config.label_horizon_sessions,
            anchor="observation_close",
            return_convention="close_to_close",
            tail_policy="preserve_missing",
            overlapping=True,
            available_at_policy="future_session_close",
        )
        label_data = build_forward_labels(frame.copy(deep=True), label_spec).data
        label_audit = audit_labels(label_data, horizon=config.label_horizon_sessions)
        labels = label_data[["trade_date", "symbol", "forward_label", 'label_available_at']].copy()
        # Research end is an information cutoff, even if input contains later bars.
        labels.loc[labels.label_available_at.gt(pd.Timestamp(config.date_end)), 'forward_label'] = np.nan
        output_column = config.factor_id.split(".", 1)[-1]
        if output_column not in factor_frame.columns:
            raise FactorResearchJobError(f"computed factor output is missing: {config.factor_id}")
        combined = factor_frame[["trade_date", "symbol", output_column]].rename(columns={output_column: "factor"}).merge(labels, on=["trade_date", "symbol"], how="left")
        combined = combined.loc[combined.trade_date.between(pd.Timestamp(config.date_start), pd.Timestamp(config.date_end))]
        aligned = align_factor_labels(combined, min_assets_per_date=config.min_assets_per_date, min_sessions=1)
        token.report(.45, 'analysis')
        ic = compute_ic_series(aligned.data, factor_column="factor", label_column="forward_label", method="spearman", min_observations=max(2, config.min_assets_per_date))
        # Membership must not depend on whether a future label happens to exist.
        grouped = build_quantile_groups(combined, quantiles=config.quantiles, min_assets_per_group=1)
        token.report(.6, 'analysis')
        grouped_frame = grouped.data.copy()
        grouped_frame["forward_1d"] = grouped_frame["forward_label"]
        group_returns = compute_group_returns(grouped_frame, return_columns={"forward": "forward_1d"})
        turnover = compute_group_turnover(grouped.data.assign(factor=grouped.data["factor"]))
        token.report(.78, 'analysis')
        detail = aligned.data.copy()
        detail["trade_date"] = detail["trade_date"].dt.strftime("%Y-%m-%d")
        detail_rows = detail.to_dict(orient="records")
        result = {
            "run_id": run_id,
            "status": "succeeded",
            "config": {
                **config.to_dict(),
                "data_version": data_version,
                "label_id": label_spec.label_id,
                'processing_version': config.schema_version,
            },
            "preflight": preflight.to_dict(),
            "overview": {
                "factor_id": config.factor_id,
                "rows": int(len(aligned.data)),
                "valid_ic_sessions": int((ic.data["status"] == "ok").sum()),
                "portfolio_type": "research_equal_weight",
                "source": "offline_research_simulation",
            },
            "analysis": {
                "ic_series": ic.data.assign(trade_date=ic.data["trade_date"].dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
                "group_returns": {"portfolio_type": group_returns.diagnostics["portfolio_type"], "daily": group_returns.daily.assign(trade_date=group_returns.daily["trade_date"].dt.strftime("%Y-%m-%d")).to_dict(orient="records"), "cumulative": group_returns.cumulative.assign(trade_date=group_returns.cumulative["trade_date"].dt.strftime("%Y-%m-%d")).to_dict(orient="records")},
                "turnover": {"rows": turnover.turnover.to_dict(orient="records"), "coverage": turnover.coverage, "rank_autocorrelation": turnover.rank_autocorrelation},
                "correlation": {'status': 'unavailable', 'reason': 'single_factor', 'rows': []},
            },
            "detail": detail_rows,
            "metadata": {"factor_version": selected.version, "label_version": label_spec.version, "engine_id": "factor_research.v1"},
        }
        safe = build_factor_research_result(
            result_id="factor-job-result",
            data_fingerprint=build_data_fingerprint(frame),
            factor_fingerprint=f"{config.factor_id}:{selected.version}",
            label_fingerprint=label_spec.version,
            processing_fingerprint=config.schema_version,
            engine_id="factor_research",
            engine_version="1.0.0",
            diagnostics={"quality_status": aligned.diagnostics["quality_status"], "valid_rows": len(aligned.data)},
            payload={"overview": result["overview"], "metadata": result["metadata"]},
        )
        result["result_contract"] = safe.to_dict()
        result['integrity'] = dict(input=integrity, labels=label_audit, prefix=prefix,
            grouping='same_session_factor_only', inference='descriptive_only_no_iid_t_test')
        result['run_manifest'] = build_run_manifest(frame=frame, engine_id='factor_research.v1',
            features={'factor': selected.factor_id, 'version': selected.version},
            labels={'id': label_spec.label_id, 'version': label_spec.version,
                'horizon': config.label_horizon_sessions, 'anchor': label_spec.anchor,
                'return_convention': label_spec.return_convention},
            execution={'model': 'research_equal_weight_non_tradable'},
            parameters=config.to_dict(), cost={'model': 'not_applied_research_returns'},
            evaluation='descriptive_full_sample', processing={'quantiles': config.quantiles,
                'min_assets': config.min_assets_per_date, 'version': config.schema_version,
                'evaluation_period': {'start': config.date_start, 'end': config.date_end}})
        token.report(.95, 'archive')
        return _archive_values(result)

    def to_strategy_draft(
        self,
        result: dict[str, Any] | None,
        *,
        top_k: int = 10,
        direction: str = "long",
        rebalance_frequency: str = "weekly",
    ) -> dict[str, Any]:
        """Convert a completed, numerically usable result into a draft only."""
        if result is None or not isinstance(result, dict):
            raise FactorResearchJobError("research result is not available")
        overview = result.get("overview")
        if not isinstance(overview, dict) or int(overview.get("valid_ic_sessions", 0)) <= 0:
            raise FactorResearchJobError("factor result quality is not suitable for a strategy draft")
        try:
            return build_factor_strategy_draft(
                result,
                top_k=top_k,
                direction=direction,
                rebalance_frequency=rebalance_frequency,
            )
        except ValueError as exc:
            raise FactorResearchJobError(str(exc)) from exc

    def drilldown(self, result: dict[str, Any] | None, *, trade_date: str | None = None, symbol: str | None = None) -> dict[str, Any]:
        if result is None or not isinstance(result, dict) or "detail" not in result:
            raise FactorResearchJobError("research result is not available")
        if trade_date is not None and symbol is not None:
            raise FactorResearchJobError("choose a date or symbol filter")
        rows = result["detail"]
        if trade_date is not None:
            matches = [row for row in rows if str(row.get("trade_date")) == trade_date]
            if not matches:
                raise FactorResearchJobError("date not found")
            return {"trade_date": trade_date, "rows": matches}
        if symbol is not None:
            matches = [row for row in rows if str(row.get("symbol")) == symbol]
            if not matches:
                raise FactorResearchJobError("symbol not found")
            return {"symbol": symbol, "rows": matches}
        raise FactorResearchJobError("date or symbol filter is required")
