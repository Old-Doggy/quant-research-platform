import json
import re

import pytest

from portfolio_app.project_event_summaries import build_project_event_summary


@pytest.mark.parametrize("language", ["zh", "en"])
def test_abstract_entry_exit_factor_and_timing_cover_all_projects(language):
    for i in range(1, 8):
        summary = build_project_event_summary(f"model{i}", language=language)
        assert [row["id"] for row in summary["items"]] == ["factor", "entry", "exit", "timing"]
        assert all(row["label"] and row["text"] for row in summary["items"])
        assert summary["scope_note"] and summary["source"]
        text = json.dumps(summary, ensure_ascii=False)
        assert not re.search(r"[A-Za-z]:[\\/]|data/output|target_positions|account_id|source_files|\b\d{6}\.(SH|SZ)\b", text)
        if language == "en":
            assert not re.search(r"[\u4e00-\u9fff]", text)


def test_missing_and_unknown_language_are_explicit():
    with pytest.raises(ValueError):
        build_project_event_summary("model8")
    with pytest.raises(ValueError):
        build_project_event_summary("model1", language="de")
