from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_app.factor_contracts import LabelSpec
from portfolio_app.factor_labels import (
    LabelBuildError,
    ResearchCache,
    build_forward_labels,
    build_research_cache_key,
    fingerprint_frame,
)


def bars() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-02", periods=5)
    return pd.DataFrame(
        {
            "trade_date": list(dates) * 2,
            "symbol": ["AAA"] * 5 + ["BBB"] * 5,
            "open": [10, 11, 12, 13, 14, 20, 21, 22, 23, 24],
            "close": [11, 12, 13, 14, 15, 21, 22, 23, 24, 25],
        }
    )


def label_spec(**overrides: object) -> LabelSpec:
    values: dict[str, object] = {
        "label_id": "demo.forward_return.2d",
        "version": "1.0.0",
        "prediction_direction": "forward_return",
        "horizon_sessions": 2,
        "anchor": "observation_close",
        "return_convention": "close_to_close",
        "tail_policy": "preserve_missing",
        "overlapping": True,
        "available_at_policy": "future_session_close",
    }
    values.update(overrides)
    return LabelSpec(**values)


def test_close_to_close_labels_use_sessions_per_symbol_and_preserve_tail() -> None:
    result = build_forward_labels(bars(), label_spec())

    aaa = result.data[result.data["symbol"] == "AAA"]
    assert aaa["forward_label"].iloc[0] == pytest.approx(13 / 11 - 1)
    assert aaa["label_available_at"].iloc[0] == pd.Timestamp("2026-01-06")
    assert aaa["forward_label"].iloc[-1] != aaa["forward_label"].iloc[-1]
    assert aaa["label_status"].iloc[-1] == "incomplete_tail"
    assert result.diagnostics["input_rows"] == 10
    assert result.diagnostics["valid_labels"] == 6


def test_horizon_counts_sessions_when_calendar_days_are_missing() -> None:
    frame = bars()
    frame = frame[frame["trade_date"] != pd.Timestamp("2026-01-05")].copy()

    result = build_forward_labels(frame, label_spec(horizon_sessions=1))

    aaa = result.data[result.data["symbol"] == "AAA"]
    assert aaa["trade_date"].iloc[0] == pd.Timestamp("2026-01-02")
    assert aaa["label_available_at"].iloc[0] == pd.Timestamp("2026-01-06")
    assert aaa["forward_label"].iloc[0] == pytest.approx(13 / 11 - 1)


def test_next_open_to_next_close_uses_next_session_open_as_anchor() -> None:
    result = build_forward_labels(
        bars(),
        label_spec(anchor="next_open", return_convention="next_open_to_next_close", horizon_sessions=2),
    )

    aaa = result.data[result.data["symbol"] == "AAA"]
    assert aaa["forward_label"].iloc[0] == pytest.approx(13 / 11 - 1)
    assert aaa["label_available_at"].iloc[0] == pd.Timestamp("2026-01-06")


def test_observation_open_to_close_uses_observation_session_open() -> None:
    result = build_forward_labels(
        bars(),
        label_spec(anchor="observation_open", return_convention="open_to_close", horizon_sessions=1),
    )

    aaa = result.data[result.data["symbol"] == "AAA"]
    assert aaa["forward_label"].iloc[0] == pytest.approx(12 / 10 - 1)
    assert aaa["label_available_at"].iloc[0] == pd.Timestamp("2026-01-05")


def test_forward_rank_is_cross_sectional_and_keeps_tail_missing() -> None:
    result = build_forward_labels(
        bars(),
        label_spec(prediction_direction="forward_rank", horizon_sessions=1),
    )

    first_date = result.data[result.data["trade_date"] == pd.Timestamp("2026-01-02")]
    assert first_date["forward_label"].tolist() == [1.0, 0.0]
    tail = result.data[result.data["trade_date"] == pd.Timestamp("2026-01-08")]
    assert tail["forward_label"].isna().all()


def test_excess_return_requires_and_uses_independent_benchmark() -> None:
    benchmark = bars().query("symbol == 'AAA'").assign(symbol="BENCH", open=lambda data: data["open"] * 2, close=lambda data: data["close"] * 2)
    result = build_forward_labels(
        bars(),
        label_spec(prediction_direction="forward_excess_return"),
        benchmark_frame=benchmark,
    )

    aaa = result.data[result.data["symbol"] == "AAA"]
    assert aaa["forward_label"].dropna().abs().max() == pytest.approx(0.0)
    with pytest.raises(LabelBuildError, match="benchmark"):
        build_forward_labels(bars(), label_spec(prediction_direction="forward_excess_return"))


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda frame: frame.assign(trade_date=frame["trade_date"].where(frame.index != 0, "bad")), "trade_date"),
        (lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True), "duplicate"),
        (lambda frame: frame.assign(close=frame["close"].where(frame.index != 0, np.nan)), "close"),
    ],
)
def test_label_input_contract_is_strict(mutator, message: str) -> None:
    with pytest.raises(LabelBuildError, match=message):
        build_forward_labels(mutator(bars()), label_spec())


def test_fingerprint_is_order_independent_but_data_sensitive() -> None:
    frame = bars()
    first = fingerprint_frame(frame)
    shuffled = frame.sample(frac=1.0, random_state=7).reset_index(drop=True)

    assert first == fingerprint_frame(shuffled)
    changed = frame.copy()
    changed["close"] = changed["close"].astype(float)
    changed.loc[0, "close"] += 0.01
    assert first != fingerprint_frame(changed)


def test_cache_key_contains_all_reproducibility_versions_and_changes_on_any_component() -> None:
    frame = bars()
    key = build_research_cache_key(
        frame,
        factor_version="factor-1",
        processing_version="processing-1",
        label_spec=label_spec(),
        engine_id="offline-labels",
        engine_version="2026.10",
    )

    payload = key.to_dict()
    assert payload["data_fingerprint"] == fingerprint_frame(frame)
    assert payload["factor_version"] == "factor-1"
    assert payload["processing_version"] == "processing-1"
    assert payload["label_version"] == "1.0.0"
    assert payload["engine_version"] == "2026.10"
    assert "D:\\" not in repr(payload)

    changed = build_research_cache_key(
        frame,
        factor_version="factor-2",
        processing_version="processing-1",
        label_spec=label_spec(),
        engine_id="offline-labels",
        engine_version="2026.10",
    )
    assert key.cache_id != changed.cache_id
    label_changed = build_research_cache_key(
        frame,
        factor_version="factor-1",
        processing_version="processing-1",
        label_spec=label_spec(horizon_sessions=3),
        engine_id="offline-labels",
        engine_version="2026.10",
    )
    assert key.cache_id != label_changed.cache_id


def test_memory_cache_hits_and_misses_by_complete_key_without_mutating_frames() -> None:
    frame = bars()
    key = build_research_cache_key(frame, factor_version="f1", processing_version="p1", label_spec=label_spec(), engine_id="e", engine_version="1")
    cache = ResearchCache()
    assert cache.get(key) is None
    cache.put(key, frame)
    cached = cache.get(key)
    assert cached is not None
    cached.loc[0, "close"] = -1
    assert cache.get(key).loc[0, "close"] == 11
    assert cache.stats() == {"hits": 2, "misses": 1, "entries": 1}
