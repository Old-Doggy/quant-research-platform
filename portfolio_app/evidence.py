from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from portfolio_app.projects import RESEARCH_PROJECTS
from portfolio_app.redacted_results import (
    PUBLIC_SOURCE_LABEL,
    load_redacted_annual_oos,
    load_redacted_model7_results,
    load_redacted_results,
)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _metric_row(row: object, annual_key: str = "annual_return", sharpe_key: str = "sharpe", drawdown_key: str = "max_drawdown") -> dict[str, float]:
    return {
        "annual_return": float(row.get(annual_key, 0.0)),
        "sharpe": float(row.get(sharpe_key, 0.0)),
        "max_drawdown": float(row.get(drawdown_key, 0.0)),
    }


def _model1_evidence(root: Path) -> dict[str, object]:
    folder = root / "data" / "output" / "model1_formal_cost_stress_20260507"
    manifest = _read_json(folder / "manifest.json")
    stress = pd.read_csv(folder / "model1_cost_stress.csv")
    base = stress.loc[stress["case"].eq("base")].iloc[0].to_dict()
    cost_x2 = stress.loc[stress["case"].eq("cost_x2")].iloc[0].to_dict()
    return {
        "status": "validated",
        "status_label": "正式成本压力测试",
        "source": _display_path(folder, root),
        "headline": _metric_row(base),
        "secondary": {"cost_x2": _metric_row(cost_x2), "trade_days": int(base["trade_days"])},
        "period": f"{base['start_date']} 至 {base['end_date']}",
        "notes": [f"固定参数：Buy{manifest['param']['MAX_TOP_K_BUY']} / Hold{manifest['param']['MAX_TOP_K_HOLD']} / Z{manifest['param']['MIN_Z_SCORE']}", "2 倍综合成本后仍保留正收益。"],
    }


def _model2_evidence(root: Path) -> dict[str, object]:
    folder = root / "data" / "output" / "model2_pool_validation_smoke_decode"
    summary = pd.read_csv(folder / "model2_pool_validation_summary.csv").iloc[0].to_dict()
    return {
        "status": "review_required",
        "status_label": "股票池验证未通过门槛",
        "source": _display_path(folder, root),
        "headline": {"annual_return": float(summary["ann"]), "sharpe": float(summary["sharpe"]), "max_drawdown": float(summary["dd"])},
        "secondary": {"pool_id": str(summary["pool_id"]), "pass_gate": _as_bool(summary["pass_gate"]), "source_trade_date": str(summary["source_trade_date"])},
        "period": "验证摘要",
        "notes": ["结果保留为研究证据，当前不把该候选描述为已通过生产门槛。"],
    }


def _model3_evidence(root: Path) -> dict[str, object]:
    folder = root / "data" / "output" / "model3_vaa_formal_audit_full"
    manifest = _read_json(folder / "manifest.json")
    metrics = manifest["wfo_metrics"]
    annual = pd.read_csv(folder / "model3_vaa_annual_oos.csv")
    return {
        "status": "validated",
        "status_label": "ETF/VAA 正式 WFO 审计",
        "source": _display_path(folder, root),
        "headline": {"annual_return": float(metrics["annualized_return"]), "sharpe": float(metrics["sharpe_ratio"]), "max_drawdown": float(metrics["max_drawdown"])},
        "secondary": {"days": int(metrics["days"]), "parameter_count": int(manifest["official_grid_param_count"])},
        "period": f"{metrics['start']} 至 {metrics['end']}",
        "annual_oos": annual.to_dict("records"),
        "notes": ["正式审计同时包含年度 OOS、参数稳定性、负对照和 bootstrap 结果。", "运行时配置存在来源交易日差异，页面保留该限制。"],
    }


def _model4_evidence(root: Path) -> dict[str, object]:
    folder = root / "data" / "output" / "model4_cb_execution_audit"
    summary = _read_json(folder / "model4_cb_execution_audit_summary.json")
    scenario = next(item for item in summary["summaries"] if item["scenario"] == "t_minus_1_next_open" and item["cost_multiplier"] == 2)
    return {
        "status": "validated_with_limitations",
        "status_label": "T-1 下一开盘执行审计",
        "source": _display_path(folder, root),
        "headline": _metric_row(scenario),
        "secondary": {"trade_count": int(scenario["trade_count"]), "blocked_buys": int(scenario["blocked_buys"]), "events": int(scenario["events"])},
        "period": f"{scenario['start']} 至 {scenario['end']}",
        "notes": summary["limitations"],
    }


def _model5_evidence(root: Path) -> dict[str, object]:
    folder = root / "data" / "output" / "model5_pead_formal_audit" / "20260507_215750"
    summary = _read_json(folder / "model5_audit_summary.json")
    cost = pd.read_csv(folder / "model5_cost_stress.csv")
    cost_x2 = cost.loc[cost["case"].eq("stress_cost_x2")].iloc[0].to_dict()
    return {
        "status": "validated",
        "status_label": "PEAD 正式 WFO 审计",
        "source": _display_path(folder, root),
        "headline": _metric_row(summary["base_wfo_metrics"]),
        "secondary": {"cost_x2": _metric_row(cost_x2), "stocks": int(summary["manifest"]["stocks"]), "events": int(summary["manifest"]["event_rows"])},
        "period": f"{summary['manifest']['start']} 至 {summary['manifest']['end']}",
        "notes": ["审计包含成本压力、负对照和 block bootstrap。", "事件策略采用信息时点控制，展示结果时不将公告时间优势默认为可得。"],
    }


def _model6_evidence(root: Path) -> dict[str, object]:
    folder = root / "data" / "output" / "model6_locked_validation_raw"
    decision = (folder / "MODEL6_LOCKED_CANDIDATE_DECISION.md").read_text(encoding="utf-8")
    match = re.search(r"costx1: annual=([\d.]+)% 2025\+=([\d.]+)% 2026=([\d.]+)% Sharpe=([\d.]+) DD=([-\d.]+)%", decision)
    fold = pd.read_csv(folder / "model6_locked_candidate_fixed_fold_summary.csv").iloc[0].to_dict()
    values = match.groups() if match else ("0", "0", "0", "0", "0")
    return {
        "status": "review_required",
        "status_label": "锁定候选未通过最终门禁",
        "source": _display_path(folder, root),
        "headline": {"annual_return": float(values[0]) / 100, "sharpe": float(values[3]), "max_drawdown": float(values[4]) / 100},
        "secondary": {"annual_2025plus": float(values[1]) / 100, "annual_2026": float(values[2]) / 100, "positive_folds": f"{int(fold['positive_fold_count'])}/{int(fold['fold_count'])}"},
        "period": "锁定候选验证",
        "notes": ["研究文档明确写出：候选未通过最终 research gate，不应改变生产配置。", "这类负结果本身适合作为稳健性与风险控制能力的作品集证据。"],
    }


def load_all_model_evidence(project_root: str | Path, public_only: bool = False) -> dict[str, dict[str, object]]:
    if public_only:
        try:
            return _load_public_model_evidence(Path(project_root))
        except (FileNotFoundError, KeyError, IndexError, ValueError, TypeError):
            return {
                f"model{model_number}": {
                    "status": "unavailable",
                    "status_label": "公开证据不可用",
                    "source": "",
                    "error": "public evidence summary is unavailable",
                }
                for model_number in range(1, 7)
            }
    root = Path(project_root)
    loaders = {"model1": _model1_evidence, "model2": _model2_evidence, "model3": _model3_evidence, "model4": _model4_evidence, "model5": _model5_evidence, "model6": _model6_evidence}
    evidence: dict[str, dict[str, object]] = {}
    for key, loader in loaders.items():
        try:
            evidence[key] = loader(root)
        except (FileNotFoundError, KeyError, IndexError, ValueError) as exc:
            from .research_diagnostics import capture_error
            failure = capture_error(exc, operation='archive')
            evidence[key] = {"status": "unavailable", "status_label": "产物不可用", "source": "",
                             "error": failure['message'], 'error_id': failure['error_id']}
    return evidence


def load_model7_evidence(project_root: str | Path, public_only: bool = False) -> dict[str, object]:
    """Read published model7 artifacts without importing live runtime code."""
    if public_only:
        try:
            return _load_public_model7_evidence(Path(project_root))
        except (FileNotFoundError, KeyError, IndexError, ValueError, TypeError):
            return {"available": False, "reason": "public model7 evidence is unavailable"}
    latest = Path(project_root) / "模型7" / "output" / "latest"
    metrics_path = latest / "model7_backtest_metrics.csv"
    manifest_path = latest / "manifest.json"
    if not metrics_path.exists() or not manifest_path.exists():
        return {"available": False, "reason": "model7 published artifacts are unavailable"}

    metrics = pd.read_csv(metrics_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selection = manifest.get("params", {}).get("selection_validation", {})
    periods = {
        str(row["period"]): {
            "annual": float(row["annual"]),
            "sharpe": float(row["sharpe"]),
            "max_drawdown": float(row["max_drawdown"]),
            "days": int(row["days"]),
        }
        for _, row in metrics.iterrows()
    }
    return {
        "available": True,
        "candidate_id": manifest.get("candidate_id", ""),
        "published_at": manifest.get("published_at", ""),
        "source": _display_path(latest, Path(project_root)),
        "periods": periods,
        "selection_validation": {
            "annual": float(selection.get("full_sample_annual", 0.0)),
            "sharpe": float(selection.get("full_sample_sharpe", 0.0)),
            "max_drawdown": float(selection.get("full_sample_max_drawdown", 0.0)),
            "wfo_annual": float(selection.get("wfo_annual", 0.0)),
            "cost_2x_annual": float(selection.get("cost_2x_annual", 0.0)),
        },
    }


def build_model_comparison_rows(
    project_root: str | Path,
    evidence: dict[str, dict[str, object]] | None = None,
    public_only: bool = False,
) -> list[dict[str, object]]:
    """Build one comparable display row per research model.

    Model 7 is stored in a separate published-artifact layout, so it is
    normalised here with the same headline fields as models 1-6.  The rows
    are for portfolio presentation only; each keeps its asset class and
    validation caveat visible so unlike studies are not presented as a
    production leaderboard.
    """
    root = Path(project_root)
    model_evidence = evidence if evidence is not None else load_all_model_evidence(root, public_only=public_only)
    model7 = load_model7_evidence(root, public_only=public_only)
    rows: list[dict[str, object]] = []
    for model_number in range(1, 8):
        key = f"model{model_number}"
        project = next((item for item in RESEARCH_PROJECTS if item.key == key), None)
        if project is None:
            continue
        if key == "model7":
            if not model7.get("available"):
                rows.append(
                    {
                        "key": key,
                        "model": project.title,
                        "category": project.category,
                        "status": "unavailable",
                        "status_label": "证据不可用",
                        "annual_return": None,
                        "sharpe": None,
                        "max_drawdown": None,
                        "period": "未提供",
                        "source": str(model7.get("reason", "")),
                        "asset_scope": "多股票池",
                    }
                )
                continue
            selection = model7["selection_validation"]
            rows.append(
                {
                    "key": key,
                    "model": project.title,
                    "category": project.category,
                    "status": "validated",
                    "status_label": "组合验证产物",
                    "annual_return": float(selection["annual"]),
                    "sharpe": float(selection["sharpe"]),
                    "max_drawdown": float(selection["max_drawdown"]),
                    "period": str(model7["layers"][0]["period"] if public_only else model7.get("published_at", "已发布产物")),
                    "source": str(model7.get("source", "")),
                    "asset_scope": "多股票池组合",
                    "cost_2x_annual": float(selection["cost_2x_annual"]),
                }
            )
            continue

        item = model_evidence.get(key, {})
        headline = item.get("headline", {})
        rows.append(
            {
                "key": key,
                "model": project.title,
                "category": project.category,
                "status": str(item.get("status", "unavailable")),
                "status_label": str(item.get("status_label", "证据不可用")),
                "annual_return": float(headline["annual_return"]) if "annual_return" in headline else None,
                "sharpe": float(headline["sharpe"]) if "sharpe" in headline else None,
                "max_drawdown": float(headline["max_drawdown"]) if "max_drawdown" in headline else None,
                "period": str(item.get("period", "未提供")),
                "source": str(item.get("source", "")),
                "asset_scope": _asset_scope(key),
                "notes": "；".join(str(note) for note in item.get("notes", [])),
            }
        )
    return rows


def build_research_artifact_manifest(project_root: str | Path, public_only: bool = False) -> list[dict[str, object]]:
    """Return a small, stable set of real research artifacts for portfolio download."""
    root = Path(project_root)
    if public_only:
        files = {
            "model1": (("公开摘要", "public_evidence/model1_summary.csv"),),
            "model2": (("公开摘要", "public_evidence/model2_summary.csv"),),
            "model3": (("公开摘要", "public_evidence/model3_summary.csv"), ("年度样本外", "public_evidence/model3_annual_oos.csv")),
            "model4": (("公开摘要", "public_evidence/model4_summary.csv"),),
            "model5": (("公开摘要", "public_evidence/model5_summary.csv"),),
            "model6": (("公开摘要", "public_evidence/model6_summary.csv"),),
            "model7": (("公开摘要", "public_evidence/model7_summary.csv"),),
        }
        result: list[dict[str, object]] = []
        for model_number in range(1, 8):
            key = f"model{model_number}"
            project = next(item for item in RESEARCH_PROJECTS if item.key == key)
            artifacts = []
            for label, relative_path in files[key]:
                path = root / relative_path
                artifacts.append(
                    {
                        "label": label,
                        "path": relative_path,
                        "available": path.is_file(),
                        "size": path.stat().st_size if path.is_file() else 0,
                        "suffix": path.suffix.lower().lstrip(".") or "file",
                    }
                )
            result.append({"key": key, "title": project.title, "artifacts": artifacts})
        return result
    selections: dict[str, tuple[tuple[str, str], ...]] = {
        "model1": (
            ("成本压力摘要", "data/output/model1_formal_cost_stress_20260507/model1_cost_stress.csv"),
            ("正式参数清单", "data/output/model1_formal_cost_stress_20260507/manifest.json"),
        ),
        "model2": (
            ("股票池验证摘要", "data/output/model2_pool_validation_smoke_decode/model2_pool_validation_summary.csv"),
            ("研究配置", "data/output/model2_pool_validation_smoke_decode/manifest.json"),
        ),
        "model3": (
            ("年度样本外结果", "data/output/model3_vaa_formal_audit_full/model3_vaa_annual_oos.csv"),
            ("参数稳定性", "data/output/model3_vaa_formal_audit_full/model3_vaa_parameter_stability.csv"),
            ("审计清单", "data/output/model3_vaa_formal_audit_full/manifest.json"),
        ),
        "model4": (
            ("执行审计摘要", "data/output/model4_cb_execution_audit/model4_cb_execution_audit_summary.json"),
            ("下一开盘交易记录", "data/output/model4_cb_execution_audit/model4_cb_t_minus_1_next_open_cost2p0x_trades.csv"),
        ),
        "model5": (
            ("PEAD 审计摘要", "data/output/model5_pead_formal_audit/20260507_215750/model5_audit_summary.md"),
            ("成本压力测试", "data/output/model5_pead_formal_audit/20260507_215750/model5_cost_stress.csv"),
            ("年度样本外结果", "data/output/model5_pead_formal_audit/20260507_215750/model5_wfo_yearly.csv"),
        ),
        "model6": (
            ("候选决策说明", "data/output/model6_locked_validation_raw/MODEL6_LOCKED_CANDIDATE_DECISION.md"),
            ("成本敏感性", "data/output/model6_locked_validation_raw/model6_locked_candidate_cost_sensitivity.csv"),
            ("固定折汇总", "data/output/model6_locked_validation_raw/model6_locked_candidate_fixed_fold_summary.csv"),
        ),
        "model7": (
            ("本地回测报告", "模型7/output/latest/MODEL7_LOCAL_BACKTEST_REPORT.md"),
            ("回测指标", "模型7/output/latest/model7_backtest_metrics.csv"),
            ("目标仓位样本", "模型7/output/latest/model7_targets.csv"),
        ),
    }
    result: list[dict[str, object]] = []
    for model_number in range(1, 8):
        key = f"model{model_number}"
        project = next(item for item in RESEARCH_PROJECTS if item.key == key)
        artifacts: list[dict[str, object]] = []
        for label, relative_path in selections[key]:
            path = root / relative_path
            artifacts.append(
                {
                    "label": label,
                    "path": relative_path.replace("\\", "/"),
                    "available": path.is_file(),
                    "size": path.stat().st_size if path.is_file() else 0,
                    "suffix": path.suffix.lower().lstrip(".") or "file",
                }
            )
        result.append({"key": key, "title": project.title, "artifacts": artifacts})
    return result


def _asset_scope(model_key: str) -> str:
    scopes = {
        "model1": "股票横截面",
        "model2": "股票因子组合",
        "model3": "ETF / 跨资产",
        "model4": "可转债",
        "model5": "股票事件驱动",
        "model6": "股票组合筛选",
    }
    return scopes.get(model_key, "研究模型")


def _read_public_summary(root: Path, filename: str) -> pd.DataFrame:
    return pd.read_csv(root / "public_evidence" / filename)


def _public_row(row: object) -> dict[str, object]:
    return {
        "annual_return": None if pd.isna(row.get("annual_return")) else float(row["annual_return"]),
        "sharpe": None if pd.isna(row.get("sharpe")) else float(row["sharpe"]),
        "max_drawdown": None if pd.isna(row.get("max_drawdown")) else float(row["max_drawdown"]),
        "period": str(row.get("period", "")),
        "source": str(row.get("source", "")),
        "cost_assumption": str(row.get("cost_assumption", "")),
        "limitations": str(row.get("limitations", "")),
    }


def _load_public_model_evidence(root: Path) -> dict[str, dict[str, object]]:
    redacted_rows = load_redacted_results(root)
    evidence: dict[str, dict[str, object]] = {}
    for key in (f"model{number}" for number in range(1, 7)):
        model_rows = [row for row in redacted_rows if row["model"] == key]
        if not model_rows:
            raise FileNotFoundError(f"redacted evidence unavailable for {key}")
        row = model_rows[0]
        item = {
            "status": str(row["status"]),
            "status_label": str(row["status_label"]),
            "source": PUBLIC_SOURCE_LABEL,
            "period": str(row["period"]),
            "headline": {field: float(row[field]) for field in ("annual_return", "sharpe", "max_drawdown")},
            "notes": [str(row["limitations"]), str(row["cost_assumption"])],
            "cases": model_rows,
        }
        if key == "model3":
            item["annual_oos"] = [
                {
                    "year": str(record["year"]),
                    "days": int(record["days"]),
                    "start": str(record["period_start"]),
                    "end": str(record["period_end"]),
                    "annualized_return": float(record["annual_return"]),
                    "max_drawdown": float(record["max_drawdown"]),
                    "sharpe_ratio": float(record["sharpe"]),
                    "ending_nav": float(record["ending_nav"]),
                }
                for record in load_redacted_annual_oos(root)
            ]
        evidence[key] = item
    return evidence


def _load_public_model7_evidence(root: Path) -> dict[str, object]:
    rows = load_redacted_model7_results(root)
    if not rows:
        raise FileNotFoundError("redacted evidence unavailable for model7")
    by_case = {str(row["evidence_case"]): row for row in rows}
    selection = by_case["selection_validation"]
    latest = by_case["latest_local_backtest"]
    layers = [
        {"key": case, **_public_row(row), "status": str(row["status"]), "status_label": str(row["status_label"])}
        for case, row in by_case.items()
    ]
    return {
        "available": True,
        "candidate_id": "public_summary_only",
        "published_at": "",
        "source": PUBLIC_SOURCE_LABEL,
        "periods": {
            "full": {
                "annual": float(latest["annual_return"]),
                "sharpe": float(latest["sharpe"]),
                "max_drawdown": float(latest["max_drawdown"]),
                "days": 564,
            }
        },
        "selection_validation": {
            "annual": float(selection["annual_return"]),
            "sharpe": float(selection["sharpe"]),
            "max_drawdown": float(selection["max_drawdown"]),
            "cost_2x_annual": 0.2684096720,
        },
        "layers": layers,
    }
