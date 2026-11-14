"""Fixed local-review artifact register; registration is not publication consent."""
from hashlib import sha256
from pathlib import Path


_DIGESTS = {
    "model1_summary": "786acc6dce4f02791de0892280ee70f67cba9a0809325416809f1d69fac652a3",
    "model2_summary": "71c274040b37137ce9f6f266c946d59b3252752d26231fb39a6de9b4cf55e8bd",
    "model3_summary": "334bf2cf6203eebf1d5ba82ec4bdfeebba79cb93ffe1901486fc981fd44c02c0",
    "model3_annual_oos": "5ae04e44d9297d0b409168ddd7cf72702f7359c10dd7f72a75e6d95378ac6352",
    "model4_summary": "8ee45904d3498c724e6816dbf842cf86c4cbaf53446788249650b82a73ef8038",
    "model5_summary": "2f9d9d3248c58020c3c0d3fbd0cbfcc7d42d6b04e2bcdefcf235ddfee5bd78d1",
    "model6_summary": "99729fdec51fbef27f46c38de03f6196b72a56dfbcb717bd72809a950ff97ec1",
    "model7_summary": "fb40919490de759c08c37d657cc93c01a15180969df0d62ec5ca54cb38bc3670",
}


def _verified_content(root, artifact_id):
    if artifact_id not in _DIGESTS:
        raise ValueError("Unknown artifact identifier")
    public_root = Path(root).resolve() / "public_evidence"
    path = (public_root / f"{artifact_id}.csv").resolve()
    if not path.is_relative_to(public_root):
        return "outside_root", None
    try:
        if not path.is_file():
            return "missing", None
        with path.open("rb") as handle:
            content = handle.read(65537)
    except OSError:
        return "unreadable", None
    if len(content) > 65536 or sha256(content).hexdigest() != _DIGESTS[artifact_id]:
        return "changed", None
    return "verified", content


def read_project_artifact(root, artifact_id):
    """Recheck bytes at download preparation; never accept a caller-supplied path."""
    status, content = _verified_content(root, artifact_id)
    if status != "verified":
        raise ValueError("Artifact unavailable; local review required")
    return content


def list_project_artifacts(root, model_id, *, language="zh"):
    if language not in {"zh", "en"}:
        raise ValueError("language must be 'zh' or 'en'")
    if model_id not in {f"model{i}" for i in range(1, 8)}:
        raise ValueError("Unknown project identifier")
    zh = language == "zh"
    result = []
    for identifier, digest in _DIGESTS.items():
        if not identifier.startswith(model_id + "_"):
            continue
        status, _ = _verified_content(root, identifier)
        annual = identifier.endswith("annual_oos")
        limitations = ("年度样本外摘要，保留负年度和不完整年度；不含逐日曲线。" if annual else
            "聚合历史摘要，不含完整训练、逐笔交易或独立复现所需材料。") if zh else (
            "Annual OOS summary retains negative and incomplete years; no daily curve." if annual else
            "Historical aggregates exclude full training, trade records and materials needed for independent reproduction.")
        if model_id == "model7":
            limitations += " 选型、本地回测和历史运行状态分层，运行状态无收益。" if zh else " Selection, local backtest and historical runtime are separate; runtime has no returns."
        result.append({"artifact_id": identifier, "model_id": model_id,
            "label": ("年度样本外" if zh else "Annual out-of-sample results") if annual else ("公开摘要" if zh else "Public summary"),
            "path": f"public_evidence/{identifier}.csv", "suffix": "csv",
            "available": status == "verified", "status": status,
            "sha256": digest, "source_version": "sha256:" + digest,
            "review_date": "2026-11-01", "upstream_version_status": "not_disclosed",
            "source": "既有筛选研究摘要；内容指纹对应本次本地登记，原始研究版本未披露。" if zh else "Existing curated research summary; content fingerprint identifies this local registration. Original research version is not disclosed.",
            "license_status": "MIT", "publication_status": "public",
            "license_note": "经项目所有者授权公开的历史汇总，按 MIT 许可证发布。" if zh else "Historical aggregates published with owner authorization under the MIT license.",
            "limitations": limitations})
    return result
