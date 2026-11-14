from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

import pandas as pd
import pytest

from portfolio_app.evidence import build_model_comparison_rows, build_research_artifact_manifest, load_all_model_evidence, load_model7_evidence


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_EVIDENCE = ROOT / "public_evidence"


def test_public_evidence_covers_models_one_to_seven():
    expected = {
        "model1_summary.csv",
        "model2_summary.csv",
        "model3_summary.csv",
        "model3_annual_oos.csv",
        "model4_summary.csv",
        "model5_summary.csv",
        "model6_summary.csv",
        "model7_summary.csv",
    }
    assert expected.issubset({path.name for path in PUBLIC_EVIDENCE.glob("*.csv")})

    for name in expected:
        frame = pd.read_csv(PUBLIC_EVIDENCE / name)
        assert not frame.empty
        required = {"model", "status", "cost_assumption", "source", "limitations"}
        if name == "model3_annual_oos.csv":
            required.update({"period_start", "period_end"})
        else:
            required.add("period")
        assert required.issubset(frame.columns)
        assert frame[list(required)].notna().all().all(), name
        assert frame["model"].eq(name.split("_")[0]).all()


def test_public_evidence_has_no_absolute_paths_or_sensitive_runtime_fields():
    absolute_path = re.compile(r"[A-Za-z]:[\\/]|\\\\[A-Za-z0-9_.-]+\\|/(?:home|Users|mnt|tmp)/")
    sensitive_assignment = re.compile(
        r"(?:password|secret|api[_-]?key|access[_-]?token|broker[_-]?account|account[_-]?id)"
        r"[\"']?\s*[:=]\s*[\"']?\S+", re.IGNORECASE
    )
    for path in PUBLIC_EVIDENCE.iterdir():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert not absolute_path.search(text), path.name
        assert not sensitive_assignment.search(text), path.name
        assert path.suffix in {".csv", ".md"}, path.name
        assert path.stat().st_size < 1_000_000, path.name


def test_public_sources_are_safe_labels_not_private_artifact_paths():
    for path in PUBLIC_EVIDENCE.glob("*.csv"):
        frame = pd.read_csv(path)
        if "source" in frame:
            assert frame["source"].eq("curated research summary").all(), path.name


def test_model7_runtime_state_is_not_presented_as_performance():
    frame = pd.read_csv(PUBLIC_EVIDENCE / "model7_summary.csv")
    runtime = frame.loc[frame["evidence_case"].eq("runtime_state")].iloc[0]
    assert runtime["status"] == "runtime_only"
    assert pd.isna(runtime["annual_return"])
    assert pd.isna(runtime["sharpe"])
    assert pd.isna(runtime["max_drawdown"])
    assert set(frame["evidence_case"]) == {"selection_validation", "latest_local_backtest", "runtime_state"}


@pytest.mark.parametrize("model", ["model2", "model6"])
def test_failed_research_gates_remain_visible(model):
    frame = pd.read_csv(PUBLIC_EVIDENCE / f"{model}_summary.csv")
    assert frame["status"].eq("review_required").all()


def test_model3_annual_oos_keeps_negative_and_partial_years():
    frame = pd.read_csv(PUBLIC_EVIDENCE / "model3_annual_oos.csv", dtype={"year": str})
    assert frame.loc[frame["year"].eq("2022"), "annual_return"].iloc[0] < 0
    partial = frame.loc[frame["year"].eq("2026")].iloc[0]
    assert partial["period_end"] == "2026-04-30"
    assert partial["days"] == 77
    summary = pd.read_csv(PUBLIC_EVIDENCE / "model3_summary.csv").iloc[0]
    aggregate = frame.loc[frame["year"].eq("ALL_OOS")].iloc[0]
    for field in ("annual_return", "sharpe", "max_drawdown"):
        assert summary[field] == pytest.approx(aggregate[field], abs=1e-10)


def test_public_loaders_work_without_private_outputs():
    with TemporaryDirectory(prefix=".tmp_public_evidence_", dir=ROOT) as temporary:
        verification_root = Path(temporary)
        shutil.copytree(PUBLIC_EVIDENCE, verification_root / "public_evidence")
        evidence = load_all_model_evidence(verification_root, public_only=True)
        assert evidence["model2"]["status"] == "review_required"
        assert evidence["model6"]["status"] == "review_required"
        assert evidence["model3"]["annual_oos"]
        assert evidence["model4"]["headline"]["annual_return"] > 0
        model7 = load_model7_evidence(verification_root, public_only=True)
        assert model7["available"]
        assert model7["selection_validation"]["annual"] == pytest.approx(0.3033286626)
        assert model7["periods"]["full"]["annual"] == pytest.approx(0.2889319904)
        assert len(model7["layers"]) == 3
        assert pd.isna(model7["layers"][2]["annual_return"])
        rows = build_model_comparison_rows(verification_root, public_only=True)
        assert len(rows) == 7
        assert all(row["source"] for row in rows)
        assert all(row["status"] != "unavailable" for row in rows)


def test_public_downloads_never_include_private_artifacts():
    manifest = build_research_artifact_manifest(ROOT, public_only=True)
    assert len(manifest) == 7
    for entry in manifest:
        assert entry["artifacts"]
        for artifact in entry["artifacts"]:
            assert artifact["path"].startswith("public_evidence/")
            assert artifact["suffix"] in {"csv", "md"}
            assert artifact["available"]
            assert "manifest.json" not in artifact["path"]
            assert "targets.csv" not in artifact["path"]


def test_public_loader_does_not_fall_back_to_private_data():
    with TemporaryDirectory(prefix=".tmp_public_evidence_", dir=ROOT) as temporary:
        verification_root = Path(temporary)
        (verification_root / "data" / "output").mkdir(parents=True)
        evidence = load_all_model_evidence(verification_root, public_only=True)
        assert all(row["status"] == "unavailable" for row in evidence.values())
        assert not load_model7_evidence(verification_root, public_only=True)["available"]
