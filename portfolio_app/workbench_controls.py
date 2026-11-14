from __future__ import annotations

import hashlib
import json
import math

import pandas as pd
import streamlit as st

from portfolio_app.data import _normalise_column_name
from portfolio_app.data_catalog import import_source_columns, preview_market_import
from portfolio_app.research_diagnostics import show_safe_error
from portfolio_app.indicators import (
    INDICATOR_REGISTRY,
    normalize_indicator_config,
    validate_indicator_layout,
)


INDICATOR_PRESETS = {
    "默认看盘": (["MA", "BOLL"], ["MACD"]),
    "趋势研究": (["MA", "EMA", "BOLL"], ["MACD", "ATR"]),
    "量价研究": (["MA", "VWAP"], ["OBV", "RSI"]),
    "简洁价格": (["MA"], []),
}


def apply_indicator_preset() -> None:
    overlay, panels = INDICATOR_PRESETS[st.session_state["indicator_preset"]]
    st.session_state["registry_overlay_indicators"] = list(overlay)
    st.session_state["registry_panel_indicators"] = list(panels)
    st.session_state["extra_ma_periods"] = []
    st.session_state["indicator_panel_priority"] = panels[0] if panels else "默认顺序"
    for key, spec in INDICATOR_REGISTRY.items():
        for name, definition in spec.parameters.items():
            st.session_state[f"indicator_{key}_{name}"] = definition["default"]
    st.session_state.pop("imported_indicator_config", None)


def parse_indicator_template(data: bytes) -> list[dict]:
    if len(data) > 100_000:
        raise ValueError("模板文件过大")
    value = json.loads(data)
    if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("indicators"), list):
        raise ValueError("模板必须使用schema=1与指标数组")
    if len(value["indicators"]) > 16 or any(not isinstance(item, dict) for item in value["indicators"]):
        raise ValueError("指标配置无效或数量超过16个")
    return validate_indicator_layout(value["indicators"])


def serialize_indicator_template(config: list[dict]) -> bytes:
    """Serialize a validated visible layout for download and later restore."""
    normalized = validate_indicator_layout(config)
    return json.dumps(
        {"schema": 1, "indicators": normalized},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def render_indicator_template_controls() -> None:
    st.selectbox("指标预设", list(INDICATOR_PRESETS), key="indicator_preset", on_change=apply_indicator_preset, filter_mode=None)
    with st.expander("恢复指标模板", expanded=False):
        source = st.file_uploader("指标模板 JSON", type=["json"], key="indicator_template_upload")
        if st.button("应用指标模板", disabled=source is None):
            try:
                config = parse_indicator_template(source.getvalue())
                st.session_state["imported_indicator_config"] = config
                st.success("已恢复指标模板")
            except (ValueError, KeyError, TypeError) as exc:
                show_safe_error(exc, operation='configuration')


def render_import_preview(uploaded, *, key: str) -> pd.DataFrame | None:
    """Show explicit mapping and quality gates before any research consumes data."""
    fingerprint = hashlib.sha256(uploaded.getvalue()).hexdigest()[:12]
    prefix = f"import_{key}_{fingerprint}"
    try:
        columns = import_source_columns(uploaded)
    except Exception as exc:
        show_safe_error(exc, operation='import')
        return None
    canonical = ["symbol", "trade_date", "open", "high", "low", "close", "vol", "amount", "pre_close",
                 "turnover_rate", "roe", "pb", "pe_ttm", "dv_ratio", "dt_netprofit_yoy"]
    mapping = {}
    with st.expander("字段映射与重复处理", expanded=False):
        for field in canonical:
            matches = [column for column in columns if _normalise_column_name(column) == _normalise_column_name(field)]
            options = ["未指定", *columns]
            choice = st.selectbox(field, options, index=options.index(matches[0]) if matches else 0,
                                  key=f"{prefix}_{field}", filter_mode=None)
            if choice != "未指定":
                if choice in mapping:
                    st.error('同一源字段不能映射两次，请调整字段映射。')
                    return None
                mapping[choice] = field
        policy = st.selectbox("重复日期/股票记录", ["拒绝导入", "保留最后一条"], key=f"{prefix}_duplicates", filter_mode=None)
    preview = preview_market_import(uploaded, column_map=mapping,
                                    duplicate_policy="keep_last" if policy == "保留最后一条" else "reject")
    st.subheader("导入预览")
    st.dataframe(pd.DataFrame([{"原始行数": preview["raw_rows"], "标准化行数": preview["normalised_rows"],
                                "重复记录数": preview["quality"].get("duplicate_key_rows", 0),
                                "检查状态": "通过" if preview["can_import"] else "阻止导入"}]),
                 width="stretch", hide_index=True)
    if not preview["can_import"]:
        show_safe_error(ValueError(preview['error']), operation='import')
        return None
    frame = preview["frame"]
    columns = [item for item in ("symbol", "trade_date", "open", "high", "low", "close", "vol") if item in frame]
    st.dataframe(frame[columns].head(8), width="stretch", hide_index=True)
    if not st.checkbox("确认使用此数据", key=f"{prefix}_confirm"):
        return None
    return frame


def validate_allocation(percentages: dict[str, float], cash_weight: float) -> dict[str, float]:
    if not math.isfinite(cash_weight) or not 0 <= cash_weight <= 1:
        raise ValueError("现金权重必须在 0% 至 100% 之间")
    if not percentages:
        raise ValueError("至少选择一个组合标的")
    weights = {str(symbol): float(value) / 100 for symbol, value in percentages.items()}
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in weights.values()):
        raise ValueError("股票权重必须是 0% 至 100% 的有效数字")
    if abs(sum(weights.values()) + cash_weight - 1) > 1e-9:
        raise ValueError(f"股票与现金权重合计必须等于100%，当前为{sum(weights.values()) + cash_weight:.2%}")
    return weights


def render_allocation(symbols: list[str], cash_weight: float) -> dict[str, float] | None:
    st.subheader("组合资金配置")
    mode = st.radio("配置方式", ["等权配置", "自定义权重"], horizontal=True)
    percentages = {symbol: (1 - cash_weight) * 100 / len(symbols) for symbol in symbols}
    if mode == "自定义权重":
        prefix = hashlib.sha256("|".join(symbols).encode()).hexdigest()[:12]
        for symbol in symbols:
            percentages[symbol] = st.number_input(f"{symbol} 权重（%）", min_value=0.0, max_value=100.0,
                                                  value=float(percentages[symbol]), step=1.0,
                                                  key=f"allocation_{prefix}_{symbol}")
    try:
        weights = validate_allocation(percentages, cash_weight)
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.dataframe(pd.DataFrame([{"标的": key, "目标权重": f"{value:.2%}"} for key, value in weights.items()]
                             + [{"标的": "保留现金", "目标权重": f"{cash_weight:.2%}"}]), width="stretch", hide_index=True)
    return weights
