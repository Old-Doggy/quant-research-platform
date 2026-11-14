"""Fail-closed capability policy for the public and local application routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os


class InvalidCapabilityMode(ValueError):
    """Raised when the application route is missing or not explicitly supported."""


class CapabilityMode(StrEnum):
    PUBLIC = "public"
    LOCAL = "local"


@dataclass(frozen=True)
class CapabilitySet:
    """Capabilities granted to one route, with conservative public defaults."""

    mode: CapabilityMode
    public_only: bool
    can_read_local_market: bool
    can_load_private_workspace: bool
    can_display_private_evidence: bool


_CAPABILITIES = {
    CapabilityMode.PUBLIC: CapabilitySet(
        mode=CapabilityMode.PUBLIC,
        public_only=True,
        can_read_local_market=False,
        can_load_private_workspace=False,
        can_display_private_evidence=False,
    ),
    CapabilityMode.LOCAL: CapabilitySet(
        mode=CapabilityMode.LOCAL,
        public_only=False,
        can_read_local_market=True,
        can_load_private_workspace=True,
        can_display_private_evidence=True,
    ),
}


def resolve_capability_mode(value: str | None = None) -> CapabilityMode:
    """Resolve the route from an explicit value and reject unknown values."""

    raw = os.environ.get("PORTFOLIO_MODE", "public") if value is None else value
    normalized = str(raw).strip().lower()
    try:
        return CapabilityMode(normalized)
    except ValueError as exc:
        raise InvalidCapabilityMode(
            f"Unsupported PORTFOLIO_MODE={raw!r}; choose 'public' or 'local'."
        ) from exc


def capabilities_for(mode: CapabilityMode | str) -> CapabilitySet:
    """Return the immutable capability set for a validated route."""

    try:
        return _CAPABILITIES[CapabilityMode(mode)]
    except (KeyError, ValueError) as exc:
        raise InvalidCapabilityMode(f"Unsupported capability mode: {mode!r}") from exc
