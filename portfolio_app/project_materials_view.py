"""Research process notes and provenance-aware local downloads."""
import streamlit as st

from portfolio_app.project_artifact_registry import read_project_artifact
from portfolio_app.project_event_summaries import build_project_event_summary


def render_project_process(model_id, *, language):
    summary = build_project_event_summary(model_id, language=language)
    st.markdown("**信号、买卖与时点说明**" if language == "zh" else "**Signals, entry, exit and timing**")
    st.caption(summary["scope_note"])
    for item in summary["items"]:
        st.markdown(f"**{item['label']}**")
        st.write(item["text"])
    st.caption(summary["source"])


def render_project_artifacts(root, artifacts, *, language):
    zh = language == "zh"
    st.caption("以下为作者授权公开的历史研究汇总，按 MIT 许可证发布。" if zh else
        "Owner-authorized historical aggregates, published under the MIT license.")
    reasons = {
        "missing": "文件缺失" if zh else "File missing",
        "changed": "文件与已登记版本不一致，需重新复核" if zh else "File differs from the registered review; review required",
        "unreadable": "文件暂时无法读取" if zh else "File cannot be read",
        "outside_root": "文件不在允许目录中" if zh else "File is outside the allowed directory",
    }
    for artifact in artifacts:
        with st.container(border=True):
            st.markdown(f"**{artifact['label']} · CSV**")
            st.caption(artifact["source"])
            st.caption(("登记日期：" if zh else "Registration date: ") + artifact["review_date"])
            st.caption(("内容版本：" if zh else "Content version: ") + artifact["source_version"])
            st.caption(artifact["license_note"])
            st.write(artifact["limitations"])
            if not artifact["available"]:
                st.warning(reasons[artifact["status"]])
                continue
            try:
                content = read_project_artifact(root, artifact["artifact_id"])
            except ValueError:
                st.warning("文件已变化或不可用，需重新复核。" if zh else "File changed or unavailable; review required.")
                continue
            st.download_button(("下载 " if zh else "Download ") + artifact["label"], content,
                file_name=artifact["artifact_id"] + ".csv", mime="text/csv",
                key=f"dossier_download_{artifact['artifact_id']}")
