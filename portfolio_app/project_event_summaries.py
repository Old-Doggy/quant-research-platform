"""Authored abstract process notes, never private strategy logic or trade history."""

_NOTES = {
    "model1": {
        "zh": ("横截面特征与模型排序。", "根据研究候选排序形成建仓意图，先检查交易可行性。", "在持有期或再平衡检查点更新候选，并计入退出成本。", "仅使用信号时点已知数据，信号与下一可执行窗口分离。"),
        "en": ("Cross-sectional features and model ranking.", "Form entry intentions from ranked research candidates, subject to execution checks.", "Update candidates at holding-period or rebalance checkpoints and include exit costs.", "Use information available at signal time and separate signals from the next executable window."),
    },
    "model2": {
        "zh": ("股息、低波动和质量等防御特征。", "候选股票池通过暴露与风险预算检查后形成配置意图。", "再平衡时更新防御暴露，未通过门禁的候选不视为可用策略。", "区分因子可得时间、股票池更新和执行时间；研究门禁需复核。"),
        "en": ("Defensive dividend, low-volatility and quality features.", "Form allocation intentions after universe, exposure and risk-budget checks.", "Update defensive exposure at rebalance; a failed gate does not define a deployable candidate.", "Distinguish factor availability, universe updates and execution time; the research gate requires review."),
    },
    "model3": {
        "zh": ("ETF 趋势、动量和风险状态。", "根据已确认风险状态形成跨资产配置意图。", "在再平衡时切换资产或防御状态，并核对执行假设。", "分离收盘信号与下一调仓窗口；核对研究与运行配置的来源时点。"),
        "en": ("ETF trend, momentum and risk state.", "Form cross-asset allocation intentions from confirmed risk states.", "Switch assets or defensive states at rebalance and check execution assumptions.", "Separate closing signals from the next rebalance window; check source dates of research and runtime configurations."),
    },
    "model4": {
        "zh": ("可转债择时特征与流动性、赎回风险检查。", "研究信号经过交易约束检查后形成下一窗口的执行意图。", "事件或风险条件触发退出检查，保留拦截和未成交结论。", "前一时点信号与下一开盘分离；缺少盘中数据时注明代理窗口。"),
        "en": ("Convertible-bond timing features with liquidity and redemption-risk checks.", "Check trading constraints before forming execution intentions for the next window.", "Review exits when event or risk conditions change, retaining blocked and unfilled outcomes.", "Separate prior-time signals from the next open; disclose proxy windows when intraday data is absent."),
    },
    "model5": {
        "zh": ("财报事件、盈利变化与价格确认。", "公告可得性检查通过后，才将事件候选交给下一执行窗口。", "按持有窗口或追踪退出逻辑检查平仓，保留交易成本。", "公告时点不完整时采用保守可得性假设，不能默认当日信号可交易。"),
        "en": ("Earnings events, earnings changes and price confirmation.", "Pass announcement-availability checks before sending event candidates to the next execution window.", "Review closure at holding-window or trailing-exit checkpoints and retain transaction costs.", "Use conservative availability assumptions when announcement timestamps are incomplete; do not assume same-day tradability."),
    },
    "model6": {
        "zh": ("低波动、质量与股票池稳定性。", "候选通过股票池和交易规则检查后形成研究配置。", "再平衡时更新筛选结果，结合换手和成本审查退出。", "保留下一交易日约束；锁定候选未通过最终门禁，不视为上线通过。"),
        "en": ("Low volatility, quality and universe stability.", "Build research allocations after universe and trading-rule checks.", "Update screening results at rebalance and review exits with turnover and costs.", "Retain next-session constraints; the locked candidate has not passed the final gate."),
    },
    "model7": {
        "zh": ("多个候选股票池与组合暴露约束。", "合并候选、处理重复和现金残余后形成组合配置意图。", "再平衡时检查暴露变化与调出候选，统一处理执行约束。", "收盘后配置与下一交易窗口分离；历史运行记录不是实际成交或收益证据。"),
        "en": ("Multiple candidate pools and portfolio-exposure constraints.", "Form portfolio intentions after merging candidates, resolving duplicates and retaining residual cash.", "Review exposure changes and outgoing candidates at rebalance under shared execution constraints.", "Separate after-close configuration from the next trading window; historical runtime records are not actual fills or return evidence."),
    },
}


def build_project_event_summary(model_id, *, language="zh"):
    if model_id not in _NOTES or language not in {"zh", "en"}:
        raise ValueError("Unknown project or language")
    labels = ("因子 / 事件", "买入 / 建仓", "卖出 / 退出", "信息与执行时点") if language == "zh" else (
        "Factors and events", "Buy and entry", "Sell and exit", "Information and execution timing")
    return {"source": "依据既有研究工作说明整理" if language == "zh" else "Authored from existing research-work descriptions",
        "scope_note": "抽象研究流程说明，不是实际买卖记录或可执行规则；核心公式、阈值与精确配置保持私有。" if language == "zh" else "Abstract research workflow, not actual trade records or executable rules. Core formulas, thresholds and exact configurations remain private.",
        "items": [{"id": key, "label": label, "text": text} for key, label, text in zip(
            ["factor", "entry", "exit", "timing"], labels, _NOTES[model_id][language])]}
