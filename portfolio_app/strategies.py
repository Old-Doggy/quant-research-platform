from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrategyDefinition:
    key: str
    name: str
    description: str


STRATEGIES = (
    StrategyDefinition("trend", "趋势跟踪", "用短中期均线判断趋势，体现项目中的趋势与动量研究。"),
    StrategyDefinition("mean_reversion", "均值回归", "用滚动 z-score 寻找短期偏离，并观察价格回归过程。"),
    StrategyDefinition("quality_momentum", "质量动量", "结合中期动量、盈利质量和估值字段，体现基本面与动量融合。"),
)


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(window, min_periods=max(3, window // 2)).mean()
    down = (-delta.clip(upper=0)).rolling(window, min_periods=max(3, window // 2)).mean()
    relative_strength = up / down.replace(0, np.nan)
    return 100 - (100 / (1 + relative_strength))


def add_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    close = result["close"]
    result["ma20"] = close.rolling(20, min_periods=5).mean()
    result["ma60"] = close.rolling(60, min_periods=10).mean()
    result["rolling_std20"] = close.rolling(20, min_periods=5).std()
    result["zscore20"] = (close - result["ma20"]) / result["rolling_std20"].replace(0, np.nan)
    result["rsi14"] = _rsi(close)
    result["ret20"] = close.pct_change(20)
    result["ret60"] = close.pct_change(60)
    result["volatility20"] = result["return"].rolling(20, min_periods=5).std() * np.sqrt(252)
    return result


def generate_signal(frame: pd.DataFrame, strategy_key: str, threshold: float = 1.0) -> pd.DataFrame:
    result = add_features(frame)
    if strategy_key == "trend":
        result["signal"] = ((result["close"] > result["ma20"]) & (result["ma20"] > result["ma60"])).astype(int)
        result["signal_label"] = np.where(result["signal"].eq(1), "趋势持有", "观望")
    elif strategy_key == "mean_reversion":
        entry = result["zscore20"] < -abs(threshold)
        exit_signal = result["zscore20"] > 0
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
        quality = (result["roe"].fillna(0) > 8) & (result["pb"].fillna(999) < 6)
        result["signal"] = ((result["ret60"] > 0) & quality).astype(int)
        result["signal_label"] = np.where(result["signal"].eq(1), "质量动量", "观望")
    else:
        raise KeyError(f"Unknown strategy key: {strategy_key}")
    return result

