"""Factor research workspace route adapter."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from portfolio_app import factor_research_view

T = TypeVar("T")


def render_factor_workspace(
    route_state: Any,
    *,
    frame: Any,
    public_mode: bool,
    render_body: Callable[[Any, Any, bool], T] | None = None,
) -> T:
    """Render factor research only when the router selected factors."""
    if getattr(route_state, "active_workspace", None) != "factors":
        raise ValueError("factor workspace requires the factors route")
    if render_body is None:
        return factor_research_view.render_factor_research(frame, public_mode=public_mode)
    return render_body(route_state, frame, public_mode)
