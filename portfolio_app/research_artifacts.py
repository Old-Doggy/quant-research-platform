"""Read-only adapters for reviewed local research artifacts.

The adapter deliberately exposes result-shaped data only.  It never returns
source paths, model parameters, holdings, target symbols, or runtime payloads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from portfolio_app.redacted_results import load_redacted_model7_results, load_redacted_results


_MODEL1 = "data/output/model1_formal_cost_stress_20260507"
_MODEL2 = "data/model2_pool_validation/20260505_125747"
_MODEL3 = "data/output/model3_vaa_formal_audit_full"
_MODEL4 = "data/output/model4_cb_execution_audit"
_MODEL5 = "data/output/model5_pead_formal_audit/20260507_215750"
_MODEL6 = "data/output/model6_locked_validation_raw"
_MODEL7 = "模型7/output/latest"


def _read_csv(root: Path, relative: str, **kwargs: Any) -> pd.DataFrame:
    """Read one hard-coded reviewed artifact; no user-provided path is accepted."""
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    return pd.read_csv(path, **kwargs)


def _read_json(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {relative}")
    return value


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _metric(row: dict[str, Any], annual: str = "annual_return", sharpe: str = "sharpe", drawdown: str = "max_drawdown") -> dict[str, float | None]:
    return {
        "annual_return": _number(row.get(annual)),
        "sharpe": _number(row.get(sharpe)),
        "max_drawdown": _number(row.get(drawdown)),
    }


def _period(row: dict[str, Any], start: str = "start", end: str = "end") -> str:
    return f"{row.get(start, '')} 至 {row.get(end, '')}".strip(" 至")


def _curve(frame: pd.DataFrame, date_column: str, value_column: str, return_column: str | None = None) -> list[dict[str, object]]:
    if date_column not in frame or value_column not in frame:
        return []
    data = frame.copy()
    dates = pd.to_datetime(data[date_column].astype(str), errors="coerce")
    values = pd.to_numeric(data[value_column], errors="coerce")
    returns = pd.to_numeric(data[return_column], errors="coerce") if return_column and return_column in data else None
    result: list[dict[str, object]] = []
    nav = pd.Series(values, index=data.index).astype(float)
    running_max = nav.cummax()
    drawdown = nav / running_max - 1.0
    for index, date, value in zip(data.index, dates, values):
        if pd.isna(date) or pd.isna(value):
            continue
        record: dict[str, object] = {
            "date": date.strftime("%Y-%m-%d"),
            "value": float(value),
            "drawdown": float(drawdown.loc[index]) if pd.notna(drawdown.loc[index]) else None,
        }
        if returns is not None and pd.notna(returns.loc[index]):
            record["daily_return"] = float(returns.loc[index])
        result.append(record)
    return result


def _return_curve(frame: pd.DataFrame, date_column: str, return_column: str) -> list[dict[str, object]]:
    if date_column not in frame or return_column not in frame:
        return []
    data = frame.copy()
    dates = pd.to_datetime(data[date_column].astype(str), errors="coerce")
    returns = pd.to_numeric(data[return_column], errors="coerce")
    nav = (1.0 + returns.fillna(0.0)).cumprod()
    return _curve(pd.DataFrame({"date": dates, "return": returns, "nav": nav}), "date", "nav", "return")


def _normalize_curve(curve: list[dict[str, object]]) -> list[dict[str, object]]:
    """Convert account-value curves to a unit-start NAV without exposing scale."""
    if not curve:
        return []
    baseline = float(curve[0]["value"])
    if baseline == 0:
        return curve
    return [{**row, "value": float(row["value"]) / baseline} for row in curve]


def _base(model_id: str, *, disclosure_mode: str, curve_status: str = "unavailable") -> dict[str, Any]:
    return {
        "model_id": model_id,
        "disclosure_mode": disclosure_mode,
        "curve_status": curve_status,
        "curve": [],
        "cost_cases": [],
        "annual_oos": [],
        "blocked_trade_summary": {},
        "research_gate": "not_reported",
        "evidence_layers": [],
        "runtime_state": {"metrics": {}},
        "artifacts": [],
        "trade_evidence_status": "not_available",
        "execution_explanation": {
            "entry": "研究信号与执行时点由正式产物定义；精确规则不在展示层。",
            "exit": "退出/调仓规则仅展示抽象口径。",
            "execution_window": "未提供",
            "portfolio_constraints": "未提供",
        },
    }


def _private_model1(root: Path) -> dict[str, Any]:
    view = _base("model1", disclosure_mode="private_redacted")
    folder = f"{_MODEL1}/"
    stress = _read_csv(root, f"{folder}model1_cost_stress.csv")
    rows = stress.to_dict("records")
    view["cost_cases"] = [
        {"case": str(row.get("case", "")), "metrics": _metric(row), "period": _period(row, "start_date", "end_date"), "trade_days": _int(row.get("trade_days"))}
        for row in rows
    ]
    curve = _read_csv(root, f"{folder}model1_stress_base_daily_curve.csv")
    view["curve"] = _normalize_curve(_curve(curve, "trade_date", "nav", "daily_return"))
    view["curve_status"] = "available" if view["curve"] else "unavailable"
    view["research_gate"] = "validated"
    view["evidence_layers"] = ["formal_cost_stress_audit"]
    view["trade_evidence_status"] = "aggregate_only"
    view["execution_explanation"] = {
        "entry": "按可得信息时点生成横截面候选，下一可执行交易窗口建仓。",
        "exit": "按持有期、再平衡和退出约束管理信号生命周期。",
        "execution_window": "信号确认 -> 下一可执行窗口",
        "portfolio_constraints": "Top-K、持有期、换手和成本压力测试",
    }
    return view


def _private_model2(root: Path) -> dict[str, Any]:
    view = _base("model2", disclosure_mode="private_redacted")
    frame = _read_csv(root, f"{_MODEL2}/model2_pool_validation_summary.csv")
    view["cost_cases"] = [
        {
            "case": "pool_validation",
            "pool_label": "股票池验证结果",
            "metrics": {"annual_return": _number(row.get("ann")), "sharpe": _number(row.get("sharpe")), "max_drawdown": _number(row.get("dd"))},
            "status": "review_required",
            "pass_gate": bool(row.get("pass_gate", False)),
        }
        for row in frame.to_dict("records")
    ]
    view["research_gate"] = "review_required"
    view["evidence_layers"] = ["pool_validation_summary", "wfo_comparison_artifacts"]
    view["artifacts"] = [{"type": "wfo_comparison", "count": 7}]
    view["trade_evidence_status"] = "aggregate_only"
    view["execution_explanation"] = {
        "entry": "因子标准化、排序后进入候选股票池。",
        "exit": "按股票池再平衡和防御暴露约束更新。",
        "execution_window": "股票池更新 -> 组合再平衡",
        "portfolio_constraints": "低换手、因子暴露和风险预算",
    }
    return view


def _private_model3(root: Path) -> dict[str, Any]:
    view = _base("model3", disclosure_mode="private_redacted")
    manifest = _read_json(root, f"{_MODEL3}/manifest.json")
    frame = _read_csv(root, f"{_MODEL3}/model3_vaa_wfo_daily_returns.csv")
    view["curve"] = _normalize_curve(_return_curve(frame, "trade_date", "daily_ret"))
    view["curve_status"] = "available" if view["curve"] else "unavailable"
    annual = _read_csv(root, f"{_MODEL3}/model3_vaa_annual_oos.csv")
    view["annual_oos"] = [
        {"year": str(row.get("year")), "period": f"{row.get('start', '')} 至 {row.get('end', '')}", "days": _int(row.get("days")), "metrics": _metric(row, "annualized_return", "sharpe_ratio", "max_drawdown")}
        for row in annual.to_dict("records")
        if str(row.get("year")) != "ALL_OOS"
    ]
    metrics = manifest.get("wfo_metrics", {})
    view["cost_cases"] = [{"case": "all_oos", "period": _period(metrics), "metrics": _metric(metrics, "annualized_return", "sharpe_ratio", "max_drawdown")}]
    view["research_gate"] = "validated"
    view["evidence_layers"] = ["formal_wfo_audit", "annual_oos", "negative_controls", "block_bootstrap"]
    view["trade_evidence_status"] = "aggregate_only"
    view["execution_explanation"] = {
        "entry": "趋势/动量状态切换后生成跨资产配置信号。",
        "exit": "再平衡时切换风险状态对应的资产配置。",
        "execution_window": "收盘后信号 -> 下一调仓窗口",
        "portfolio_constraints": "目标暴露、持仓数量和防御资产切换",
    }
    return view


def _private_model4(root: Path) -> dict[str, Any]:
    view = _base("model4", disclosure_mode="private_redacted")
    summary = _read_json(root, f"{_MODEL4}/model4_cb_execution_audit_summary.json")
    safe_cases = []
    for row in summary.get("summaries", []):
        safe_cases.append({
            "case": str(row.get("scenario", "")),
            "cost_multiplier": _number(row.get("cost_multiplier")),
            "period": _period(row),
            "metrics": _metric(row),
            "trade_count": _int(row.get("trade_count")),
            "events": _int(row.get("events")),
        })
    view["cost_cases"] = safe_cases
    selected = next((row for row in summary.get("summaries", []) if row.get("scenario") == "t_minus_1_next_open" and row.get("cost_multiplier") == 2), None)
    if selected:
        view["blocked_trade_summary"] = {"blocked_buys": _int(selected.get("blocked_buys")), "blocked_sells": _int(selected.get("blocked_sells")), "partial_fills": _int(selected.get("partial_fills"))}
        view["curve"] = _normalize_curve(_curve(_read_csv(root, f"{_MODEL4}/model4_cb_t_minus_1_next_open_cost2p0x_daily.csv"), "trade_date", "nav", "daily_return"))
    view["curve_status"] = "available" if view["curve"] else "unavailable"
    view["research_gate"] = "validated_with_limitations"
    view["evidence_layers"] = ["execution_audit", "cost_sensitivity", "constraint_intercepts"]
    view["trade_evidence_status"] = "execution_audit_summary"
    view["execution_explanation"] = {
        "entry": "T-1 信号经过可转债交易约束检查后生成执行意图。",
        "exit": "事件和风险条件触发退出或调仓；拦截计数保留在审计摘要。",
        "execution_window": "T-1 信号 -> 下一开盘",
        "portfolio_constraints": "最小成交额、手数、参与率、赎回风险和成交可用性",
    }
    return view


def _private_model5(root: Path) -> dict[str, Any]:
    view = _base("model5", disclosure_mode="private_redacted")
    folder = f"{_MODEL5}/"
    summary = _read_json(root, f"{folder}model5_audit_summary.json")
    frame = _read_csv(root, f"{folder}model5_wfo_daily_returns.csv")
    view["curve"] = _normalize_curve(_return_curve(frame, "trade_date", "daily_ret"))
    view["curve_status"] = "available" if view["curve"] else "unavailable"
    cost = _read_csv(root, f"{folder}model5_cost_stress.csv")
    view["cost_cases"] = [{"case": str(row.get("case", "")), "metrics": _metric(row), "days": _int(row.get("days"))} for row in cost.to_dict("records")]
    base = summary.get("base_wfo_metrics", {})
    yearly = _read_csv(root, f"{folder}model5_wfo_yearly.csv")
    view["annual_oos"] = [{"year": str(row.get("year")), "metrics": _metric(row), "days": _int(row.get("days"))} for row in yearly.to_dict("records")]
    view["cost_cases"].insert(0, {"case": "base_wfo", "metrics": _metric(base), "days": _int(base.get("days"))})
    view["research_gate"] = "validated"
    view["evidence_layers"] = ["formal_wfo_audit", "event_time_control", "cost_stress", "negative_controls", "block_bootstrap"]
    view["trade_evidence_status"] = "aggregate_only"
    view["execution_explanation"] = {
        "entry": "公告/财报信息在可得时点确认后生成事件信号。",
        "exit": "按事件持有期和价格确认条件退出。",
        "execution_window": "公告可得 -> 保守 T+1 执行",
        "portfolio_constraints": "事件去重、持仓上限和交易成本压力测试",
    }
    return view


def _private_model6(root: Path) -> dict[str, Any]:
    view = _base("model6", disclosure_mode="private_redacted")
    frame = _read_csv(root, f"{_MODEL6}/model6_locked_candidate_daily_curves.csv")
    if "cost_multiplier" in frame:
        frame = frame.loc[pd.to_numeric(frame["cost_multiplier"], errors="coerce").eq(1.0)]
    view["curve"] = _normalize_curve(_curve(frame, "trade_date", "equity", "daily_ret"))
    view["curve_status"] = "available" if view["curve"] else "unavailable"
    cost = _read_csv(root, f"{_MODEL6}/model6_locked_candidate_cost_sensitivity.csv")
    view["cost_cases"] = [{"case": str(row.get("cost_multiplier", "")), "metrics": _metric(row, "annual", "sharpe", "max_drawdown"), "positive_folds": f"{_int(row.get('positive_fold_count'))}/{_int(row.get('fold_count'))}"} for row in cost.to_dict("records")]
    view["research_gate"] = "review_required"
    view["evidence_layers"] = ["locked_candidate_validation", "fixed_fold_check", "cost_sensitivity"]
    view["trade_evidence_status"] = "aggregate_only"
    view["execution_explanation"] = {
        "entry": "锁定候选按股票池评分进入组合。",
        "exit": "按固定再平衡周期和交易约束更新。",
        "execution_window": "收盘信号 -> 下一开盘",
        "portfolio_constraints": "固定折验证、持仓数量、换手和成本敏感性",
    }
    return view


def _private_model7(root: Path) -> dict[str, Any]:
    view = _base("model7", disclosure_mode="private_redacted")
    view["evidence_layers"] = ["selection_validation", "latest_local_backtest", "runtime_state"]
    manifest = _read_json(root, f"{_MODEL7}/manifest.json")
    selection = manifest.get("params", {}).get("selection_validation", {})
    view["cost_cases"] = [{"case": "selection_validation", "metrics": {"annual_return": _number(selection.get("full_sample_annual")), "sharpe": _number(selection.get("full_sample_sharpe")), "max_drawdown": _number(selection.get("full_sample_max_drawdown"))}}, {"case": "selection_validation_cost_x2", "metrics": {"annual_return": _number(selection.get("cost_2x_annual"))}}]
    metrics = _read_csv(root, f"{_MODEL7}/model7_backtest_metrics.csv")
    latest = metrics.loc[metrics["period"].eq("full")]
    if not latest.empty:
        row = latest.iloc[0].to_dict()
        view["cost_cases"].append({"case": "latest_local_backtest", "metrics": _metric(row, "annual", "sharpe", "max_drawdown"), "days": _int(row.get("days"))})
    curve = _read_csv(root, f"{_MODEL7}/small_model2_top4_equal_top5_cap12_ind45_reb10_daily_curve.csv")
    view["curve"] = _normalize_curve(_curve(curve, "trade_date", "equity", "daily_ret"))
    view["curve_status"] = "available" if view["curve"] else "unavailable"
    view["runtime_state"] = {"metrics": {}, "status": "runtime_only", "note": "运行状态仅保留层级，不展示标的级目标信息。"}
    view["research_gate"] = "validated_with_separate_runtime_layer"
    view["trade_evidence_status"] = "runtime_symbols_private"
    view["execution_explanation"] = {
        "entry": "多个股票池候选合并、去重并经过组合约束后形成配置意图。",
        "exit": "调仓时按新目标配置与当前组合差异执行退出/买入。",
        "execution_window": "收盘后信号 -> 下一开盘",
        "portfolio_constraints": "个股权重上限、行业暴露上限、现金残余、重复股票合并和 skipped-leg 预检",
    }
    return view


_PRIVATE_LOADERS = {
    "model1": _private_model1,
    "model2": _private_model2,
    "model3": _private_model3,
    "model4": _private_model4,
    "model5": _private_model5,
    "model6": _private_model6,
    "model7": _private_model7,
}


def _public_views(root: Path) -> list[dict[str, Any]]:
    rows = load_redacted_results(root) + load_redacted_model7_results(root)
    grouped = {model_id: [row for row in rows if row.get("model") == model_id] for model_id in _PRIVATE_LOADERS}
    result: list[dict[str, Any]] = []
    for model_id in _PRIVATE_LOADERS:
        view = _base(model_id, disclosure_mode="public_redacted", curve_status="not_in_reviewed_bundle")
        view["cost_cases"] = [{"case": str(row.get("evidence_case", "summary")), "period": str(row.get("period", "")), "metrics": _metric(row), "status": str(row.get("status", ""))} for row in grouped[model_id]]
        view["research_gate"] = "review_required" if model_id in {"model2", "model6"} else (str(grouped[model_id][0].get("status", "unavailable")) if grouped[model_id] else "unavailable")
        view["evidence_layers"] = [str(row.get("evidence_case", "summary")) for row in grouped[model_id]]
        view["artifacts"] = []
        result.append(view)
    return result


def build_research_artifact_views(project_root: str | Path, *, public_only: bool = False) -> list[dict[str, Any]]:
    """Return seven disclosure-safe result views in stable model order."""
    root = Path(project_root)
    if public_only:
        return _public_views(root)
    result: list[dict[str, Any]] = []
    for model_id, loader in _PRIVATE_LOADERS.items():
        try:
            result.append(loader(root))
        except (FileNotFoundError, KeyError, IndexError, TypeError, ValueError, pd.errors.ParserError):
            result.append(_base(model_id, disclosure_mode="private_redacted"))
            result[-1]["research_gate"] = "unavailable"
    return result
