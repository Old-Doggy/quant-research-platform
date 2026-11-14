from __future__ import annotations

from pathlib import Path

import pandas as pd

from portfolio_app.redacted_results import load_redacted_annual_oos


def evidence_table(card: dict[str, object]) -> pd.DataFrame:
    rows = []
    for layer in card.get("evidence_layers", []):
        metrics = layer.get("metrics", {})
        rows.append({
            "证据层": layer.get("label", ""),
            "状态": layer.get("status_label", ""),
            "区间/时点": layer.get("period", ""),
            "年化收益": f"{float(metrics['annual_return']):.2%}" if metrics.get("annual_return") is not None else "未提供",
            "夏普": f"{float(metrics['sharpe']):.2f}" if metrics.get("sharpe") is not None else "未提供",
            "最大回撤": f"{float(metrics['max_drawdown']):.2%}" if metrics.get("max_drawdown") is not None else "未提供",
            "成本口径": layer.get("cost_assumption", "未提供"),
            "限制": layer.get("limitations", ""),
        })
    return pd.DataFrame(rows, columns=["证据层", "状态", "区间/时点", "年化收益", "夏普", "最大回撤", "成本口径", "限制"])


def annual_oos_table(root: str | Path) -> pd.DataFrame:
    rows = [row for row in load_redacted_annual_oos(root) if str(row.get("year")) != "ALL_OOS"]
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=["年度", "区间", "交易日数", "年化收益", "夏普", "最大回撤", "不完整年度", "限制"])
    result["年度"] = result["year"].astype(str)
    result["区间"] = result["period_start"].astype(str) + " 至 " + result["period_end"].astype(str)
    result["交易日数"] = result["days"].astype(int)
    result["年化收益"] = pd.to_numeric(result["annual_return"], errors="coerce")
    result["夏普"] = result["sharpe"].map(lambda value: f"{float(value):.2f}")
    result["最大回撤"] = result["max_drawdown"].map(lambda value: f"{float(value):.2%}")
    result["不完整年度"] = result["limitations"].fillna("").str.contains("不完整年度")
    result["限制"] = result["limitations"].astype(str)
    return result[["年度", "区间", "交易日数", "年化收益", "夏普", "最大回撤", "不完整年度", "限制"]]
