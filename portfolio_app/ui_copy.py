"""Shared bilingual labels and stable value formatting for the workbench."""
from __future__ import annotations

from datetime import date, datetime
import math
import re
from typing import Any


UNKNOWN = "—"

_WORKSPACES = {
    "watch": "看盘 / Watch",
    "factors": "因子 / Factors",
    "strategy": "策略 / Strategy",
    "portfolio": "组合 / Portfolio",
    "data": "数据 / Data",
    "experiments": "实验 / Experiments",
    "showcase": "作品 / Showcase",
}
_DATA_SOURCES = {
    "synthetic": "合成示例 / Synthetic demo",
    "file_import": "文件导入 / File import",
    "local_market": "本地行情 / Local market",
    "curated_research_summary": "公开研究摘要 / Curated research summary",
}
_BASES = {
    "unspecified": "来源未声明复权 / Unspecified",
    "synthetic": "合成价格 / Synthetic",
    "raw": "原始价 / Raw",
    "qfq": "前复权 / QFQ",
    "hfq": "后复权 / HFQ",
}
_PERIODS = {"1d": "日线 / Daily", "1w": "周线 / Weekly", "1mo": "月线 / Monthly"}
_STATES = {
    "draft": "草案 / Draft",
    "running": "运行中 / Running",
    "result": "已完成 / Result",
    "stale": "草案已变更 / Stale draft",
    "failed": "失败 / Failed",
    "pending": "待接入 / Pending",
    "cancelled": "已取消 / Cancelled",
}
_RESEARCH_PHASES = {
    "queued": "排队中 / Queued",
    "lookup": "检查缓存 / Checking cache",
    "preflight": "检查研究输入 / Checking inputs",
    "features": "构造指标和标签 / Building features and labels",
    "labels": "检查标签 / Checking labels",
    "analysis": "计算信号 / Computing signals",
    "simulation": "执行研究 / Running simulation",
    "scenarios": "汇总风险和归因 / Summarizing risk and attribution",
    "archive": "生成归档 / Generating archive",
    "validation": "样本外验证 / Validating out of sample",
}


def _lookup(mapping: dict[str, str], value: str, field_name: str) -> str:
    if not isinstance(value, str) or value not in mapping:
        raise ValueError(f"unknown {field_name}: {value}")
    return mapping[value]


def format_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ValueError("date must be an ISO date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must be an ISO date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("date must be an ISO date") from exc


def format_count(value: Any) -> str:
    if value is None:
        return UNKNOWN
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("count must be a finite number")
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{float(value):,.2f}"


def format_percent(value: Any) -> str:
    if value is None:
        return UNKNOWN
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("percent must be a finite number")
    return f"{float(value):.2%}"


def format_price_basis(value: str) -> str:
    return _lookup(_BASES, value, "price_basis")


def format_period(value: str) -> str:
    return _lookup(_PERIODS, value, "bar_period")


def format_status(value: str) -> str:
    return _lookup(_STATES, value, "status")


def format_research_status(
    value: str,
    *,
    phase: str | None = None,
    cache_hit: bool = False,
    recoverable: bool = False,
) -> str:
    """Format one truthful bilingual research lifecycle label."""
    if value == "draft":
        return "草案 / Draft · 尚未运行"
    if value == "queued":
        return "排队中 / Queued"
    if value == "running":
        if phase is None:
            return "计算中 / Computing"
        return "计算中 / Computing · " + _lookup(_RESEARCH_PHASES, phase, "research phase")
    if value == "succeeded":
        return "已完成 / Complete · " + ("命中缓存" if cache_hit else "完成计算")
    if value == "stale":
        return "结果已过期 / Stale result · 配置已改变"
    if value == "failed":
        return "失败 / Failed · " + ("可恢复" if recoverable else "请检查输入")
    if value == "cancelled":
        return "已取消 / Cancelled · 未提交结果"
    raise ValueError(f"unknown research status: {value}")


def context_research_state(value: str | None) -> str:
    """Normalize a runner or run-state value for the compact context bar."""
    normalized = "draft" if value in {None, "idle"} else str(value)
    if normalized == "succeeded":
        return "result"
    if normalized == "queued":
        return "running"
    if normalized not in _STATES:
        raise ValueError(f"unknown context research state: {value}")
    return normalized


def resolve_data_source(
    *,
    dataset_id: str,
    selected_source: str | None = None,
    public_only: bool = False,
    workspace: str | None = None,
) -> str:
    """Resolve the displayed source from explicit evidence, not page name.

    The public workbench can only expose its synthetic dataset.  Local mode
    accepts the current selector value when available, then falls back to
    stable dataset-id prefixes used by cached research drafts.  Unknown values
    fail closed to ``synthetic`` so a local source is never claimed without
    evidence.
    """
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("dataset_id is required")
    if public_only:
        return "synthetic"

    source_aliases = {
        "合成示例": "synthetic",
        "synthetic": "synthetic",
        "文件导入": "file_import",
        "file_import": "file_import",
        "本地行情": "local_market",
        "local_market": "local_market",
        "公开研究摘要": "curated_research_summary",
        "curated_research_summary": "curated_research_summary",
    }
    if selected_source in source_aliases:
        return source_aliases[selected_source]

    normalized = dataset_id.strip().lower()
    if normalized == "seeded_demo" or normalized.startswith("seeded_demo:"):
        return "synthetic"
    if normalized.startswith(("file_import:", "uploaded:", "upload:")) or "file_import" in normalized:
        return "file_import"
    if normalized.startswith(("local_market:", "local:", "本地行情:")) or "local_market" in normalized:
        return "local_market"
    if normalized.startswith(("curated_research_summary:", "curated_summary:")):
        return "curated_research_summary"
    if workspace == "showcase":
        return "curated_research_summary"
    return "synthetic"


def build_research_basis_notice(data_source: str) -> str:
    """Return the consistent boundary statement shown with research results."""
    source = _lookup(_DATA_SOURCES, data_source, "data_source")
    return (
        "历史离线研究模拟 / Historical offline research simulation · "
        f"数据来源 / Data source: {source} · "
        "结果不代表实时行情、真实账户收益或实盘成交 / "
        "Results are not live quotes, live account returns, or live fills."
    )


def display_dataset_id(dataset_id: str, data_source: str) -> str:
    """Return a safe, truthful display id for the resolved source."""
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("dataset_id is required")
    if data_source == "synthetic":
        return dataset_id
    if dataset_id == "seeded_demo":
        return {
            "file_import": "file_import",
            "local_market": "local_market",
            "curated_research_summary": "curated_summary",
        }.get(data_source, dataset_id)
    return dataset_id


def build_context_status(
    *,
    workspace: str,
    dataset_id: str,
    as_of: str | date | datetime,
    data_source: str,
    price_basis: str,
    bar_period: str,
    state: str,
) -> dict[str, str]:
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("dataset_id is required")
    return {
        "workspace": _lookup(_WORKSPACES, workspace, "workspace"),
        "data": f"{_lookup(_DATA_SOURCES, data_source, 'data_source')} · dataset {dataset_id}",
        "as_of": f"截至 {format_date(as_of)} / As of {format_date(as_of)}",
        "basis": f"{format_price_basis(price_basis)} · {format_period(bar_period)}",
        "state": format_status(state),
        "mode": "历史离线研究模拟 / Historical offline research simulation",
    }
