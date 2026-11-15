from __future__ import annotations

import pytest

from portfolio_app.data_workflow import (
    DataWorkflowStep,
    build_data_workflow,
    next_data_workflow,
)


def _local_data_app():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    return AppTest.from_file(str(root / "portfolio_app" / "local_app.py"), default_timeout=60)


def test_data_workflow_starts_at_import_and_explains_next_action():
    state = build_data_workflow()

    assert state.step is DataWorkflowStep.IMPORT
    assert state.can_research is False
    assert state.next_action == "选择合成示例、导入文件或连接本地历史行情"


def test_confirmed_preview_moves_to_quality_and_exposes_dataset_summary():
    state = next_data_workflow(
        build_data_workflow(),
        source_kind="file_import",
        dataset_id="my_dataset",
        rows=120,
        symbols=3,
        preview_ready=True,
    )

    assert state.step is DataWorkflowStep.QUALITY
    assert state.dataset_id == "my_dataset"
    assert state.rows == 120
    assert state.symbols == 3
    assert state.can_research is False


def test_passed_quality_moves_to_version_before_research():
    state = next_data_workflow(
        next_data_workflow(
            build_data_workflow(),
            source_kind="file_import",
            dataset_id="my_dataset",
            preview_ready=True,
        ),
        quality_status="通过",
    )

    assert state.step is DataWorkflowStep.VERSION
    assert state.next_action == "登记或选择数据版本后进入研究"
    assert state.can_research is False


def test_registered_version_unlocks_research():
    state = next_data_workflow(
        next_data_workflow(
            next_data_workflow(
                build_data_workflow(),
                source_kind="file_import",
                dataset_id="my_dataset",
                preview_ready=True,
            ),
            quality_status="通过",
        ),
        version="v001",
    )

    assert state.step is DataWorkflowStep.RESEARCH
    assert state.can_research is True
    assert state.version == "v001"


@pytest.mark.parametrize("quality_status", ["需复核", "失败", "未知"])
def test_non_passed_quality_blocks_research_and_preserves_quality_step(quality_status):
    state = next_data_workflow(
        next_data_workflow(
            build_data_workflow(),
            source_kind="file_import",
            dataset_id="my_dataset",
            preview_ready=True,
        ),
        quality_status=quality_status,
    )

    assert state.step is DataWorkflowStep.QUALITY
    assert state.can_research is False
    assert "质量" in state.next_action


def test_workflow_rejects_version_before_quality_passes():
    with pytest.raises(ValueError, match="quality"):
        next_data_workflow(build_data_workflow(), version="v001")


def test_workflow_rejects_unsafe_dataset_id():
    with pytest.raises(ValueError, match="dataset_id"):
        next_data_workflow(
            build_data_workflow(),
            source_kind="file_import",
            dataset_id="../private",
            preview_ready=True,
        )


def test_data_workspace_does_not_reuse_previous_source_after_switch(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_MODE", "local")
    view = _local_data_app().run()
    assert not view.exception
    view.radio(key="workspace_route_selector").set_value("data").run()
    view.session_state['data_service_tab']='文件导入'
    view.run()
    view.button(key="confirm_builtin_data").click().run()
    view.button(key="confirm_data_quality").click().run()
    view.button(key="confirm_builtin_version").click().run()
    assert view.session_state["data_workflow_state"].can_research is True

    view.selectbox(key="analysis_source").select("文件导入").run()

    assert not view.exception
    assert view.session_state["data_workflow_state"].step is DataWorkflowStep.IMPORT
    assert not any(button.key == "confirm_builtin_data" for button in view.button)
