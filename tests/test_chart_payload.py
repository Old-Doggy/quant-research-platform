from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.chart_payload import build_ohlcv_payload, build_chart_state_key, clamp_chart_range
from portfolio_app.chart_bridge import chart_bridge_html, local_asset_status, _range_presets
from portfolio_app.data_catalog import generate_seeded_baseline


def test_payload_is_sorted_and_exposes_data_derived_zoom_bounds():
    frame = generate_seeded_baseline(sessions=520, seed=2026)
    frame = frame.loc[frame["symbol"].eq("DEMO_TREND")].sample(frac=1, random_state=3)

    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", initial_bars=120, min_visible_bars=30, max_visible_bars=400)

    assert len(payload["bars"]) == 520
    assert payload["period"] == "1d"
    assert payload["bars"][0]["time"] < payload["bars"][-1]["time"]
    assert payload["bounds"] == {"start": payload["bars"][0]["time"], "end": payload["bars"][-1]["time"]}
    assert payload["zoom"] == {
        "min_visible_bars": 30,
        "max_visible_bars": 400,
        "initial_visible_bars": 120,
    }
    assert payload["initial_range"]["from"] == payload["bars"][-120]["time"]
    assert payload["initial_range"]["to"] == payload["bars"][-1]["time"]


def test_payload_exposes_path_free_chart_state_identity_and_density_contract():
    frame = generate_seeded_baseline(sessions=90, seed=2027).loc[lambda data: data["symbol"].eq("DEMO_TREND")]
    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", period="1w", indicator_config=[{"key": "RSI"}])

    state = payload["chart_state"]
    assert state["version"] == 1
    assert state["period"] == "1w"
    assert state["storage_key"].startswith("quant-chart-state-v1:")
    assert "\\" not in state["storage_key"] and "/" not in state["storage_key"]
    assert state["bounds"] == payload["bounds"]
    assert payload["density"]["min_bar_spacing"] >= 2
    assert payload["density"]["max_bar_spacing"] > payload["density"]["min_bar_spacing"]


def test_payload_exposes_period_basis_and_incomplete_period_count():
    frame = generate_seeded_baseline(sessions=90, seed=2028).loc[lambda data: data["symbol"].eq("DEMO_TREND")]
    frame["is_complete"] = True
    frame.loc[frame.index[-1], "is_complete"] = False

    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", period="1w")

    assert payload["period_info"] == {
        "label": "周K",
        "basis": "由日线聚合",
        "incomplete_bars": 1,
    }


def test_chart_state_identity_and_range_clamp_are_deterministic_and_bounded():
    first = build_chart_state_key("000001.SZ", "1d", {"start": "2024-01-01", "end": "2024-03-01"}, [{"key": "RSI"}])
    second = build_chart_state_key("000001.SZ", "1d", {"start": "2024-01-01", "end": "2024-03-01"}, [{"key": "MACD"}])
    assert first == second
    assert clamp_chart_range({"from": -50, "to": 999}, bar_count=100, min_visible_bars=20, max_visible_bars=100) == {"from": 0, "to": 99}
    assert clamp_chart_range({"from": 80, "to": 81}, bar_count=100, min_visible_bars=20, max_visible_bars=100) == {"from": 62, "to": 81}
    assert clamp_chart_range({"from": 40, "to": 10}, bar_count=100, min_visible_bars=20, max_visible_bars=100) == {"from": 10, "to": 40}


def test_payload_applies_as_of_cutoff_to_bars_volume_and_markers():
    frame = generate_seeded_baseline(sessions=120, seed=9)
    symbol_frame = frame.loc[frame["symbol"].eq("DEMO_TREND")].reset_index(drop=True)
    cutoff = symbol_frame["trade_date"].iloc[80]
    events = [
        {"event_id": "before", "event_type": "FILL", "side": "BUY", "effective_date": str(symbol_frame["trade_date"].iloc[40].date())},
        {"event_id": "after", "event_type": "FILL", "side": "SELL", "effective_date": str(symbol_frame["trade_date"].iloc[100].date())},
    ]

    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", as_of=cutoff, events=events)

    assert payload["bounds"]["end"] == cutoff.strftime("%Y-%m-%d")
    assert all(bar["time"] <= cutoff.strftime("%Y-%m-%d") for bar in payload["bars"])
    assert [marker["id"] for marker in payload["markers"]] == ["before"]


def test_payload_markers_are_aligned_to_real_bars_and_have_stable_semantics():
    frame = generate_seeded_baseline(sessions=90, seed=10)
    events = [
        {"event_id": "sell", "event_type": "FILL", "side": "SELL", "effective_date": str(frame["trade_date"].iloc[10].date())},
        {"event_id": "missing", "event_type": "FILL", "side": "BUY", "effective_date": "2099-01-01"},
        {"event_id": "buy", "event_type": "FILL", "side": "BUY", "effective_date": str(frame["trade_date"].iloc[5].date())},
    ]

    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", events=events)

    assert [marker["id"] for marker in payload["markers"]] == ["buy", "sell"]
    assert payload["markers"][0]["position"] == "belowBar"
    assert payload["markers"][0]["shape"] == "arrowUp"
    assert payload["markers"][1]["position"] == "aboveBar"
    assert payload["markers"][1]["shape"] == "arrowDown"
    assert all(marker["time"] in {bar["time"] for bar in payload["bars"]} for marker in payload["markers"])


def test_payload_rejects_duplicate_symbol_dates_and_invalid_zoom_requests():
    frame = generate_seeded_baseline(sessions=60, seed=11)
    duplicate = pd.concat([frame.loc[frame["symbol"].eq("DEMO_TREND")], frame.loc[frame["symbol"].eq("DEMO_TREND")].iloc[[0]]])

    with pytest.raises(ValueError, match="duplicate"):
        build_ohlcv_payload(duplicate, symbol="DEMO_TREND")
    with pytest.raises(ValueError, match="min_visible_bars"):
        build_ohlcv_payload(frame, symbol="DEMO_TREND", min_visible_bars=0)
    with pytest.raises(ValueError, match="max_visible_bars"):
        build_ohlcv_payload(frame, symbol="DEMO_TREND", max_visible_bars=10)


def test_empty_payload_is_renderable_and_has_no_unbounded_zoom():
    payload = build_ohlcv_payload(pd.DataFrame(), symbol="EMPTY")

    assert payload["bars"] == []
    assert payload["markers"] == []
    assert payload["bounds"] == {"start": None, "end": None}
    assert payload["zoom"]["min_visible_bars"] == 1
    assert payload["zoom"]["max_visible_bars"] == 1


def test_offline_chart_bridge_embeds_payload_without_cdn_dependency():
    payload = build_ohlcv_payload(generate_seeded_baseline(sessions=60).loc[lambda data: data["symbol"].eq("DEMO_TREND")], symbol="DEMO_TREND")
    html = chart_bridge_html(payload)

    assert 'data-chart-engine="lightweight-charts"' in html
    assert "__QUANT_CHART_PAYLOAD__" in html
    assert "<script src=\"http" not in html
    assert "cdn." not in html.lower()
    assert "subscribeVisibleLogicalRangeChange" in html
    assert "minBars" in html and "maxBars" in html
    assert local_asset_status()["available"] is True


def test_chart_bridge_explains_period_basis_and_zoom_limits():
    payload = build_ohlcv_payload(
        generate_seeded_baseline(sessions=60).loc[lambda data: data["symbol"].eq("DEMO_TREND")],
        symbol="DEMO_TREND",
        period="1m",
        min_visible_bars=12,
        max_visible_bars=60,
    )
    html = chart_bridge_html(payload)

    assert "由日线聚合" in html
    assert "当前可见范围" in html
    assert "zoom-limit-label" in html


def test_chart_range_presets_use_units_matching_the_displayed_period():
    assert [label for label, _ in _range_presets("1d")] == ["1个月", "3个月", "6个月", "1年"]
    assert [label for label, _ in _range_presets("1w")] == ["3个月", "6个月", "1年", "2年"]
    assert [label for label, _ in _range_presets("1m")] == ["6个月", "1年", "2年", "5年"]


def test_payload_contains_registry_indicator_series_split_by_pane():
    frame = generate_seeded_baseline(sessions=90, seed=12)
    frame = frame.loc[frame["symbol"].eq("DEMO_TREND")]
    payload = build_ohlcv_payload(
        frame,
        symbol="DEMO_TREND",
        indicator_config=[
            {"key": "MA", "params": {"period": 20}},
            {"key": "BOLL", "params": {"period": 20, "stddev": 2.0}},
            {"key": "RSI", "params": {"period": 14}},
            {"key": "OBV", "params": {}},
        ],
    )

    assert [item["key"] for item in payload["indicators"]] == ["MA", "BOLL", "RSI", "OBV"]
    assert {item["pane"] for item in payload["indicators"]} == {"overlay", "panel"}
    assert {item["label"] for item in payload["indicators"]} >= {"MA20", "BOLL upper20", "RSI14", "OBV"}
    assert all(0 < len(item["data"]) <= len(payload["bars"]) for item in payload["indicators"])


def test_payload_exposes_extended_shared_indicators_with_correct_panes():
    frame = generate_seeded_baseline(sessions=90, seed=2028)
    payload = build_ohlcv_payload(
        frame,
        symbol="DEMO_TREND",
        indicator_config=[
            {"key": "DONCHIAN", "params": {"period": 20}},
            {"key": "ROC", "params": {"period": 20}},
            {"key": "DMI", "params": {"period": 14}},
            {"key": "VOLUME_RATIO", "params": {"period": 20}},
        ],
    )

    by_key = {item["key"]: item for item in payload["indicators"]}
    assert by_key["DONCHIAN"]["pane"] == "overlay"
    assert by_key["ROC"]["pane"] == "panel"
    assert by_key["DMI"]["pane"] == "panel"
    assert by_key["VOLUME_RATIO"]["pane"] == "panel"
    assert {series["column"] for series in by_key["DMI"]["series"]} == {"plus_di14", "minus_di14", "adx14"}


def test_chart_bridge_renders_configured_indicator_series():
    frame = generate_seeded_baseline(sessions=60, seed=13)
    payload = build_ohlcv_payload(
        frame,
        symbol="DEMO_TREND",
        indicator_config=[{"key": "EMA", "params": {"period": 12}}, {"key": "MACD", "params": {}}],
    )
    html = chart_bridge_html(payload)
    assert "payload.indicators" in html
    assert "addLineSeries" in html
    assert "MACD" in html


def test_chart_markers_only_use_fills_not_signals_or_orders():
    frame = generate_seeded_baseline(sessions=60)
    day = str(frame["trade_date"].iloc[20].date())
    events = [{"event_id": kind, "event_type": kind, "side": "BUY", "effective_date": day}
              for kind in ("SIGNAL", "ORDER_INTENT", "FILL")]
    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", events=events)
    assert [marker["id"] for marker in payload["markers"]] == ["FILL"]


def test_payload_preserves_a_public_focus_event_for_result_to_chart_linking():
    frame = generate_seeded_baseline(sessions=60).loc[lambda data: data["symbol"].eq("DEMO_TREND")]
    day = str(frame["trade_date"].iloc[20].date())
    events = [
        {"event_id": "signal-1", "event_type": "SIGNAL", "side": "BUY", "effective_date": day},
        {"event_id": "order-1", "event_type": "ORDER_INTENT", "side": "BUY", "effective_date": day},
        {"event_id": "fill-1", "event_type": "FILL", "side": "BUY", "effective_date": day},
    ]

    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", events=events, focus_event_id="fill-1")

    assert payload["focus_event_id"] == "fill-1"
    assert "private_path" not in str(payload)


def test_chart_bridge_contains_focus_event_range_and_drawer_link():
    frame = generate_seeded_baseline(sessions=60).loc[lambda data: data["symbol"].eq("DEMO_TREND")]
    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", focus_event_id="fill-1")
    html = chart_bridge_html(payload)

    assert "focus_event_id" in html
    assert "showEventGroup" in html
    assert "focused event" in html.lower()


def test_bridge_has_distinct_volume_and_macd_histogram_and_shared_range_policy():
    payload = build_ohlcv_payload(generate_seeded_baseline(sessions=90), symbol="DEMO_TREND",
                                  indicator_config=[{"key": "RSI"}, {"key": "MACD"}])
    html = chart_bridge_html(payload, height=760)
    assert "volume-pane" in html
    assert 'data-action="zoom-in"' in html
    assert "series.column === 'macd_hist'" in html
    assert "subscribeCrosshairMove" in html
    assert "minBarSpacing" in html


def test_same_period_bollinger_instances_do_not_overwrite_each_other():
    frame = generate_seeded_baseline(sessions=90).loc[lambda value: value["symbol"].eq("DEMO_TREND")]
    payload = build_ohlcv_payload(frame, symbol="DEMO_TREND", indicator_config=[
        {"key": "BOLL", "params": {"period": 20, "stddev": 1}},
        {"key": "BOLL", "params": {"period": 20, "stddev": 3}},
    ])
    first, second = payload["indicators"]
    assert first["series"][0]["data"][-1]["value"] < second["series"][0]["data"][-1]["value"]
