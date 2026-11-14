from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicator_math import ema, moving_average, rate_of_change, rsi


@dataclass(frozen=True)
class StrategyDefinition:
    key: str
    name: str
    description: str
    required_features: tuple[str, ...]
    rules: tuple[str, ...]
    parameters: tuple[dict[str, object], ...]
    execution_lag_days: int = 1

    def config(self) -> dict[str, object]:
        return {
            "strategy_id": self.key,
            "version": "1.0",
            "display_name": self.name,
            "description": self.description,
            "required_features": list(self.required_features),
            "rules": list(self.rules),
            "parameters": [dict(parameter) for parameter in self.parameters],
            "execution_lag_days": self.execution_lag_days,
        }


STRATEGIES = (
    StrategyDefinition(
        "trend",
        "趋势跟踪",
        "用短中期均线判断趋势，体现项目中的趋势与动量研究。",
        required_features=("close", "ma20", "ma60"),
        rules=("收盘价高于短期均线", "短期均线高于中期均线", "信号下一交易日执行"),
        parameters=(
            {"key": "fast_window", "label": "短期均线窗口", "type": "int", "default": 20, "min": 5, "max": 60, "step": 1},
            {"key": "slow_window", "label": "中期均线窗口", "type": "int", "default": 60, "min": 30, "max": 200, "step": 1},
        ),
    ),
    StrategyDefinition(
        "mean_reversion",
        "均值回归",
        "用滚动 z-score 寻找短期偏离，并观察价格回归过程。",
        required_features=("close", "ma20", "rolling_std20", "zscore20"),
        rules=("z-score 低于入场阈值时建立多头", "z-score 回到零轴上方时退出", "信号下一交易日执行"),
        parameters=(
            {"key": "lookback_window", "label": "统计窗口", "type": "int", "default": 20, "min": 10, "max": 120, "step": 1},
            {"key": "entry_zscore", "label": "入场 z-score", "type": "float", "default": 1.0, "min": 0.5, "max": 3.0, "step": 0.1},
            {"key": "exit_zscore", "label": "退出 z-score", "type": "float", "default": 0.0, "min": -1.0, "max": 1.0, "step": 0.1},
        ),
    ),
    StrategyDefinition(
        "quality_momentum",
        "质量动量",
        "结合中期动量、盈利质量和估值字段，体现基本面与动量融合。",
        required_features=("close", "roe", "pb", "ret60"),
        rules=("动量窗口收益为正", "ROE 不低于质量阈值", "PB 不高于估值阈值", "信号下一交易日执行"),
        parameters=(
            {"key": "momentum_window", "label": "动量窗口", "type": "int", "default": 60, "min": 20, "max": 200, "step": 1},
            {"key": "min_roe", "label": "最低 ROE", "type": "float", "default": 8.0, "min": 0.0, "max": 30.0, "step": 0.5},
            {"key": "max_pb", "label": "最高 PB", "type": "float", "default": 6.0, "min": 1.0, "max": 20.0, "step": 0.5},
        ),
    ),
)


def _strategy_definition(strategy_key: str) -> StrategyDefinition:
    try:
        return next(strategy for strategy in STRATEGIES if strategy.key == strategy_key)
    except StopIteration as exc:
        raise KeyError(f"Unknown strategy key: {strategy_key}") from exc


def normalize_strategy_params(strategy_key: str, params: dict[str, object] | None = None) -> dict[str, object]:
    """Validate and normalize public strategy parameters against the schema."""
    strategy = _strategy_definition(strategy_key)
    supplied = dict(params or {})
    definitions = {str(item["key"]): item for item in strategy.parameters}
    unknown = sorted(set(supplied) - set(definitions))
    if unknown:
        raise ValueError(f"unknown strategy parameter: {unknown[0]}")
    normalized: dict[str, object] = {}
    for key, definition in definitions.items():
        raw = supplied.get(key, definition["default"])
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be numeric") from exc
        if not np.isfinite(value) or value < float(definition["min"]) or value > float(definition["max"]):
            raise ValueError(f"{key} must be between {definition['min']} and {definition['max']}")
        if definition["type"] == "int":
            if not value.is_integer():
                raise ValueError(f"{key} must be an integer")
            normalized[key] = int(value)
        else:
            normalized[key] = value
    if strategy_key == "trend" and normalized["fast_window"] >= normalized["slow_window"]:
        raise ValueError("fast_window must be smaller than slow_window")
    return normalized


def build_strategy_config(strategy_key: str) -> dict[str, object]:
    return _strategy_definition(strategy_key).config()


def add_features(frame: pd.DataFrame, params: dict[str, object] | None = None) -> pd.DataFrame:
    params = params or {}
    result = frame.copy()
    close = result["close"]
    fast_window = int(params.get("fast_window", 20))
    slow_window = int(params.get("slow_window", 60))
    lookback_window = int(params.get("lookback_window", 20))
    momentum_window = int(params.get("momentum_window", 60))
    result["ma20"] = moving_average(close, fast_window, min_periods=max(5, fast_window // 4))
    result["ma60"] = moving_average(close, slow_window, min_periods=max(10, slow_window // 4))
    result["rolling_std20"] = close.rolling(lookback_window, min_periods=max(5, lookback_window // 4)).std()
    result["zscore20"] = (close - result["ma20"]) / result["rolling_std20"].replace(0, np.nan)
    result["rsi14"] = rsi(close, 14)
    result["ret20"] = rate_of_change(close, 20) / 100
    result["ret60"] = rate_of_change(close, momentum_window) / 100
    result["volatility20"] = result["return"].rolling(20, min_periods=5).std() * np.sqrt(252)
    return result


def generate_signal(
    frame: pd.DataFrame,
    strategy_key: str,
    threshold: float = 1.0,
    params: dict[str, object] | None = None,
) -> pd.DataFrame:
    raw_params = dict(params or {})
    if strategy_key == "mean_reversion" and "entry_zscore" not in raw_params:
        raw_params["entry_zscore"] = threshold
    params = normalize_strategy_params(strategy_key, raw_params)
    if strategy_key == "mean_reversion" and "entry_zscore" not in params:
        params["entry_zscore"] = threshold
    result = add_features(frame, params=params)
    result["strategy_id"] = strategy_key
    result["decision_date"] = pd.to_datetime(result["trade_date"])
    result["effective_date"] = result["decision_date"] + pd.offsets.BDay(1)
    if strategy_key == "trend":
        result["signal"] = ((result["close"] > result["ma20"]) & (result["ma20"] > result["ma60"])).astype(int)
        result["signal_label"] = np.where(result["signal"].eq(1), "趋势持有", "观望")
    elif strategy_key == "mean_reversion":
        entry = result["zscore20"] < -abs(float(params.get("entry_zscore", threshold)))
        exit_signal = result["zscore20"] > float(params.get("exit_zscore", 0.0))
        position = pd.Series(np.nan, index=result.index)
        position[entry] = 1
        position[exit_signal] = 0
        result["signal"] = position.ffill().fillna(0).astype(int)
        result["signal_label"] = np.select(
            [entry, exit_signal, result["signal"].eq(1)],
            ["偏离买入", "回归退出", "持有"],
            default="观望",
        )
    elif strategy_key == "quality_momentum":
        quality = np.isfinite(result["roe"]) & np.isfinite(result["pb"]) & (result["pb"] > 0) & (result["roe"] >= float(params.get("min_roe", 8.0))) & (result["pb"] <= float(params.get("max_pb", 6.0)))
        result["signal"] = ((result["ret60"] > 0) & quality).astype(int)
        result["signal_label"] = np.where(result["signal"].eq(1), "质量动量", "观望")
    else:
        raise KeyError(f"Unknown strategy key: {strategy_key}")

    previous_signal = result["signal"].shift(1).fillna(0).astype(int)
    entered = result["signal"].eq(1) & previous_signal.ne(1)
    exited = result["signal"].eq(0) & previous_signal.eq(1)
    holding = result["signal"].eq(1) & previous_signal.eq(1)

    if strategy_key == "trend":
        result["reason_code"] = np.select(
            [entered, exited, holding],
            ["trend_confirmed", "trend_break", "trend_hold"],
            default="trend_wait",
        )
        result["reason_text_public"] = np.select(
            [entered, exited, holding],
            ["短期趋势确认后建立仓位", "短期趋势条件破坏后退出", "趋势条件仍然成立，继续持有"],
            default="趋势条件尚未形成，保持观望",
        )
        result["reason_evidence"] = [
            {
                "close_above_fast_ma": bool(pd.notna(row["close"]) and pd.notna(row["ma20"]) and row["close"] > row["ma20"]),
                "fast_ma_above_slow_ma": bool(pd.notna(row["ma20"]) and pd.notna(row["ma60"]) and row["ma20"] > row["ma60"]),
            }
            for _, row in result.iterrows()
        ]
    elif strategy_key == "mean_reversion":
        entry = result["zscore20"] < -abs(float(params.get("entry_zscore", threshold)))
        exit_signal = result["zscore20"] > float(params.get("exit_zscore", 0.0))
        result["reason_code"] = np.select(
            [entered & entry, exited & exit_signal, entered, exited, holding],
            ["mean_reversion_entry", "mean_reversion_exit", "mean_reversion_state_change", "mean_reversion_state_change", "mean_reversion_hold"],
            default="mean_reversion_wait",
        )
        result["reason_text_public"] = np.select(
            [entered & entry, exited & exit_signal, entered, exited, holding],
            ["价格偏离滚动均值后建立仓位", "价格回到退出阈值后离场", "均值回归状态改变，建立仓位", "均值回归状态改变，退出仓位", "价格仍处于均值回归持有状态"],
            default="均值回归条件尚未形成，保持观望",
        )
        result["reason_evidence"] = [
            {
                "zscore": None if pd.isna(row["zscore20"]) else float(row["zscore20"]),
                "entry_threshold": -abs(float(params.get("entry_zscore", threshold))),
                "exit_threshold": float(params.get("exit_zscore", 0.0)),
            }
            for _, row in result.iterrows()
        ]
    else:
        quality = np.isfinite(result["roe"]) & np.isfinite(result["pb"]) & (result["pb"] > 0) & (result["roe"] >= float(params.get("min_roe", 8.0))) & (result["pb"] <= float(params.get("max_pb", 6.0)))
        result["reason_code"] = np.select(
            [entered, exited, holding],
            ["quality_momentum_confirmed", "quality_filter_failed", "quality_momentum_hold"],
            default="quality_momentum_wait",
        )
        result["reason_text_public"] = np.select(
            [entered, exited, holding],
            ["动量、质量和估值条件同时满足后建立仓位", "质量或动量条件不再满足后退出", "质量动量条件仍然成立，继续持有"],
            default="质量动量条件尚未同时满足，保持观望",
        )
        result["reason_evidence"] = [
            {
                "momentum_positive": bool(pd.notna(row["ret60"]) and row["ret60"] > 0),
                "quality_pass": bool(np.isfinite(row["roe"]) and row["roe"] >= float(params.get("min_roe", 8.0))),
                "valuation_pass": bool(np.isfinite(row["pb"]) and 0 < row["pb"] <= float(params.get("max_pb", 6.0))),
            }
            for _, row in result.iterrows()
        ]
    return result
