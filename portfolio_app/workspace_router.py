"""Safe seven-workspace routing and context-preserving navigation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from portfolio_app.research_context import (
    ALLOWED_BAR_PERIODS,
    ALLOWED_WORKSPACES,
    ContractViolation,
    ResearchContext,
)


@dataclass(frozen=True)
class WorkspaceRoute:
    id: str
    label_zh: str
    label_en: str
    summary: str
    is_default: bool = False


WORKSPACE_ROUTES = (
    WorkspaceRoute("watch", "看盘", "Watch", "个股行情与图表" , True),
    WorkspaceRoute("factors", "因子", "Factors", "因子诊断与分层"),
    WorkspaceRoute("strategy", "策略", "Strategy", "策略规则与离线回测"),
    WorkspaceRoute("portfolio", "组合", "Portfolio", "组合资金与风险"),
    WorkspaceRoute("data", "数据", "Data", "数据目录与质量"),
    WorkspaceRoute("experiments", "实验", "Experiments", "实验配置与复现"),
    WorkspaceRoute("showcase", "作品", "Showcase", "公开脱敏研究成果"),
)
DEFAULT_WORKSPACE = "watch"
_ROUTE_BY_ID = {route.id: route for route in WORKSPACE_ROUTES}
_ALLOWED_QUERY_KEYS = frozenset({"workspace", "context_workspace", "dataset_id", "symbol", "symbols", "as_of", "bar_period", "context_id", "strategy_id", "factor_id"})


@dataclass(frozen=True)
class WorkspaceState:
    active_workspace: str
    context: ResearchContext


def _validate_workspace(workspace: str, *, field_name: str = "workspace") -> str:
    if not isinstance(workspace, str) or workspace not in _ROUTE_BY_ID or workspace not in ALLOWED_WORKSPACES:
        raise ContractViolation(f"{field_name} is unknown: {workspace}")
    return workspace


def build_workspace_state(context: ResearchContext, active_workspace: str | None = None) -> WorkspaceState:
    workspace = _validate_workspace(active_workspace or context.workspace)
    return WorkspaceState(active_workspace=workspace, context=context)


def switch_workspace(state: WorkspaceState, workspace: str) -> WorkspaceState:
    """Switch only the route; the validated research context remains identical."""
    _validate_workspace(workspace)
    return WorkspaceState(active_workspace=workspace, context=state.context)


def encode_route_query(state: WorkspaceState) -> dict[str, str]:
    """Encode a safe deep link using IDs and context identity only."""
    context = state.context
    query: dict[str, str] = {
        "workspace": _validate_workspace(state.active_workspace),
        "context_workspace": _validate_workspace(context.workspace),
        "dataset_id": context.dataset_id,
        "as_of": str(context.as_of),
        "bar_period": context.bar_period,
        "context_id": context.context_id,
    }
    if context.strategy_id is not None:
        query["strategy_id"] = context.strategy_id
    if context.factor_id is not None:
        query["factor_id"] = context.factor_id
    if context.symbol is not None:
        query["symbol"] = context.symbol
    elif context.symbols:
        query["symbols"] = ",".join(context.symbols)
    return query


def _query_symbols(query: Mapping[str, Any]) -> tuple[str, ...]:
    raw = query.get("symbols", "")
    if isinstance(raw, str):
        return tuple(item for item in raw.split(",") if item)
    if raw:
        raise ContractViolation("symbols query must be a comma-separated string")
    return ()


def parse_route_query(query: Mapping[str, Any]) -> WorkspaceState:
    """Parse a deep link without accepting arbitrary paths or extra state."""
    if not isinstance(query, Mapping):
        raise ContractViolation("route query must be a mapping")
    unknown = set(query) - _ALLOWED_QUERY_KEYS
    if unknown:
        raise ContractViolation(f"route query contains unknown field: {sorted(unknown)[0]}")
    workspace = _validate_workspace(query.get("workspace", DEFAULT_WORKSPACE))
    required = ("dataset_id", "as_of")
    missing = [key for key in required if key not in query]
    if missing:
        raise ContractViolation(f"route query is missing {missing[0]}")
    symbol = query.get("symbol")
    symbols = _query_symbols(query)
    if symbol is not None and symbols:
        raise ContractViolation("route query cannot provide symbol and symbols together")
    if "context_workspace" in query:
        context_workspace = _validate_workspace(query["context_workspace"], field_name="context_workspace")
    else:
        # Older links did not distinguish the page from the data context.
        # Keep those links readable while new links always carry the field.
        context_workspace = "watch"
        if workspace == "factors" and query.get("factor_id"):
            context_workspace = "factors"
        elif workspace == "strategy" and query.get("strategy_id"):
            context_workspace = "strategy"
        elif workspace == "portfolio":
            context_workspace = "portfolio"
    context = ResearchContext(
        dataset_id=query["dataset_id"],
        workspace=context_workspace,
        symbol=symbol,
        symbols=symbols,
        as_of=query["as_of"],
        bar_period=query.get("bar_period", "1d"),
        strategy_id=query.get("strategy_id") if context_workspace == "strategy" else None,
        factor_id=query.get("factor_id") if context_workspace == "factors" else None,
    )
    if query.get("context_id") and query["context_id"] != context.context_id:
        raise ContractViolation("route context_id does not match the context fields")
    return WorkspaceState(active_workspace=workspace, context=context)
