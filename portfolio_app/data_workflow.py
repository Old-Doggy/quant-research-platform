"""Safe, explicit stages for moving a dataset into offline research."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import re


class DataWorkflowStep(StrEnum):
    IMPORT = "import"
    QUALITY = "quality"
    VERSION = "version"
    RESEARCH = "research"


_SOURCE_KINDS = frozenset({"synthetic", "file_import", "local_market"})
_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class DataWorkflowState:
    """Serializable UI state; it contains metadata only, never source paths."""

    step: DataWorkflowStep = DataWorkflowStep.IMPORT
    source_kind: str | None = None
    dataset_id: str | None = None
    rows: int | None = None
    symbols: int | None = None
    quality_status: str | None = None
    version: str | None = None

    @property
    def can_research(self) -> bool:
        return self.step is DataWorkflowStep.RESEARCH and bool(self.dataset_id and self.version)

    @property
    def next_action(self) -> str:
        if self.step is DataWorkflowStep.QUALITY and self.quality_status not in {None, "通过"}:
            return "处理质量问题后重新检查"
        return {
            DataWorkflowStep.IMPORT: "选择合成示例、导入文件或连接本地历史行情",
            DataWorkflowStep.QUALITY: "检查字段、重复记录、价格逻辑和日期覆盖",
            DataWorkflowStep.VERSION: "登记或选择数据版本后进入研究",
            DataWorkflowStep.RESEARCH: "数据已就绪，可进入看盘、因子、策略或组合研究",
        }[self.step]


def build_data_workflow() -> DataWorkflowState:
    return DataWorkflowState()


def _validate_source(source_kind: str) -> None:
    if source_kind not in _SOURCE_KINDS:
        raise ValueError("source_kind is invalid")


def _validate_dataset_id(dataset_id: str) -> None:
    if not isinstance(dataset_id, str) or not _DATASET_ID_RE.fullmatch(dataset_id):
        raise ValueError("dataset_id is invalid")


def next_data_workflow(
    state: DataWorkflowState,
    *,
    source_kind: str | None = None,
    dataset_id: str | None = None,
    rows: int | None = None,
    symbols: int | None = None,
    preview_ready: bool = False,
    quality_status: str | None = None,
    version: str | None = None,
) -> DataWorkflowState:
    """Advance exactly one workflow boundary after its gate has passed."""
    if not isinstance(state, DataWorkflowState):
        raise TypeError("state must be DataWorkflowState")
    if state.step is DataWorkflowStep.IMPORT:
        if not preview_ready:
            raise ValueError("preview is required before quality")
        selected_source = source_kind or state.source_kind
        selected_dataset = dataset_id or state.dataset_id
        if selected_source is None:
            raise ValueError("source_kind is required")
        if selected_dataset is None:
            raise ValueError("dataset_id is required")
        _validate_source(selected_source)
        _validate_dataset_id(selected_dataset)
        if rows is not None and (not isinstance(rows, int) or rows < 0):
            raise ValueError("rows is invalid")
        if symbols is not None and (not isinstance(symbols, int) or symbols < 0):
            raise ValueError("symbols is invalid")
        return replace(
            state,
            step=DataWorkflowStep.QUALITY,
            source_kind=selected_source,
            dataset_id=selected_dataset,
            rows=rows,
            symbols=symbols,
        )

    if state.step is DataWorkflowStep.QUALITY:
        if state.dataset_id is None or state.source_kind is None:
            raise ValueError("quality requires an imported dataset")
        if quality_status != "通过":
            return replace(state, quality_status=quality_status)
        return replace(state, step=DataWorkflowStep.VERSION, quality_status=quality_status)

    if state.step is DataWorkflowStep.VERSION:
        if state.quality_status != "通过":
            raise ValueError("quality must pass before version")
        if not isinstance(version, str) or not re.fullmatch(r"v[0-9]{3,}", version):
            raise ValueError("version is invalid")
        return replace(state, step=DataWorkflowStep.RESEARCH, version=version)

    raise ValueError("workflow is already ready for research")
