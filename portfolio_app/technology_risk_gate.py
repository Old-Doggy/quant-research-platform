"""Technology and risk entry decisions for the v4 execution sequence.

This module is deliberately declarative. It does not inspect private data,
load optional research libraries, or switch any runtime implementation. The
decision objects make the evidence boundary explicit before a later stage can
consume it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class EvidenceStatus(StrEnum):
    READY = "READY"
    DATA_BLOCKED = "DATA_BLOCKED"
    PENDING = "PENDING"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


EVIDENCE_STATUSES = frozenset(EvidenceStatus)
_STAGE20_EVIDENCE = ("20.01", "20.02", "20.03", "20.04", "20.05", "20.06", "20.07")


@dataclass(frozen=True)
class CapabilityDecision:
    """One bounded capability decision derived from Stage 20 evidence."""

    capability_id: str
    status: EvidenceStatus
    evidence_basis: tuple[str, ...]
    allowed_claims: tuple[str, ...]
    required_gates: tuple[str, ...]
    blocked_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_id or not self.evidence_basis:
            raise ValueError("capability decisions require an id and evidence basis")
        if not self.allowed_claims and self.status is EvidenceStatus.READY:
            raise ValueError("READY capability decisions require an allowed claim")
        if self.status is EvidenceStatus.DATA_BLOCKED and not self.required_gates:
            raise ValueError("DATA_BLOCKED capability decisions require follow-up gates")
        if self.status is EvidenceStatus.OUT_OF_SCOPE and not self.blocked_reasons:
            raise ValueError("OUT_OF_SCOPE decisions require a boundary reason")


@dataclass(frozen=True)
class StageEntry:
    """The narrow scope that a completed technology gate permits."""

    stage_id: str
    status: EvidenceStatus
    required_evidence: tuple[str, ...]
    allowed_scope: tuple[str, ...]


@dataclass(frozen=True)
class TechnologyRiskGate:
    """Auditable Stage 20.08 decision and its capability-level boundaries."""

    status: EvidenceStatus
    evidence_ids: tuple[str, ...]
    capabilities: Mapping[str, CapabilityDecision]
    allowed_stage21_scope: tuple[str, ...]
    blocked_scope: tuple[str, ...]

    def capability(self, capability_id: str) -> CapabilityDecision:
        try:
            return self.capabilities[capability_id]
        except KeyError as exc:
            raise ValueError(f"unknown capability: {capability_id}") from exc


def build_stage20_08_gate() -> TechnologyRiskGate:
    """Return the fixed decision from accepted 20.01-20.07 evidence."""

    capabilities = {
        "qlib_execution": CapabilityDecision(
            "qlib_execution",
            EvidenceStatus.PENDING,
            ("20.02", "20.04"),
            ("research_only", "candidate_semantics"),
            ("execution_adapter", "order_rounding", "tradability", "T+1_ledger", "independent_oracle"),
            ("native Qlib behavior was characterized but direct runtime adoption was not approved",),
        ),
        "alphalens_statistics": CapabilityDecision(
            "alphalens_statistics",
            EvidenceStatus.PENDING,
            ("20.02", "20.03"),
            ("research_only", "validated_statistics_with_prevalidated_labels"),
            ("PIT_forward_returns", "missing_price_policy", "overlap_disclosure"),
            ("the package must not own data-quality or point-in-time decisions",),
        ),
        "chart_component_migration": CapabilityDecision(
            "chart_component_migration",
            EvidenceStatus.PENDING,
            ("20.05", "20.06"),
            ("isolated_prototype", "offline_4_2_api_asset"),
            ("production_ui_acceptance", "asset_export_review", "responsive_browser_checks"),
            ("the component probe is not a formal workbench migration",),
        ),
        "local_realistic_backtest": CapabilityDecision(
            "local_realistic_backtest",
            EvidenceStatus.DATA_BLOCKED,
            ("20.07", "directory_observed", "20.04"),
            ("directory_observed", "demo_data_only"),
            ("pit_verified", "corporate_actions_verified", "full_directory_quality", "execution_realism"),
            ("local directory observations do not prove a reproducible, executable dataset",),
        ),
        "seeded_demo_research": CapabilityDecision(
            "seeded_demo_research",
            EvidenceStatus.READY,
            ("20.01", "20.07"),
            ("public_demo", "deterministic_contract_testing", "design_prototype"),
            (),
        ),
        "private_strategy_publication": CapabilityDecision(
            "private_strategy_publication",
            EvidenceStatus.OUT_OF_SCOPE,
            ("20.01", "20.07"),
            (),
            ("public_redaction_review", "release_allowlist_review"),
            ("private strategy cores, QMT state and raw source data remain outside this gate",),
        ),
    }
    return TechnologyRiskGate(
        status=EvidenceStatus.READY,
        evidence_ids=_STAGE20_EVIDENCE,
        capabilities=MappingProxyType(capabilities),
        allowed_stage21_scope=(
            "design_system",
            "operable_prototype",
            "seeded_demo_states",
            "explicit_disabled_and_pending_states",
        ),
        blocked_scope=(
            "production_ui_migration",
            "formal_chart_component_migration",
            "qlib_runtime_adoption",
            "realistic_local_backtest_authorization",
            "private_strategy_publication",
        ),
    )


def require_stage_entry(gate: TechnologyRiskGate, stage_id: str) -> StageEntry:
    """Fail closed unless the requested stage is the fixed next stage."""

    if stage_id != "21":
        raise ValueError(f"stage {stage_id} is not the fixed successor of Stage 20.08")
    if gate.status is not EvidenceStatus.READY or gate.evidence_ids != _STAGE20_EVIDENCE:
        raise ValueError("Stage 21 requires a READY 20.08 decision with complete evidence")
    return StageEntry(
        stage_id="21",
        status=EvidenceStatus.READY,
        required_evidence=("20.08",),
        allowed_scope=gate.allowed_stage21_scope,
    )
