from __future__ import annotations

import json

import pytest
import pandas as pd

from portfolio_app.data import normalise_market_frame
from portfolio_app.research import run_single_stock_research
from portfolio_app.strategy_result_details import (
    StrategyArchiveError,
    build_strategy_result_details,
    build_strategy_result_payload,
    build_strategy_result_summary,
    create_strategy_archive,
    load_strategy_archive,
)


def research_frame(rows: int = 180) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=rows, freq="B")
    close = pd.Series(100 + pd.Series(range(rows)), dtype=float)
    return normalise_market_frame(
        pd.DataFrame(
            {
                "date": dates.strftime("%Y%m%d"),
                "symbol": "DEMO",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000,
            }
        )
    )


def events():
    return [
        {
            "event_id": "signal-1",
            "event_type": "SIGNAL",
            "strategy_id": "demo",
            "symbol": "AAA",
            "side": "BUY",
            "decision_date": "2024-01-01",
            "effective_date": "2024-01-02",
            "reason_code": "trend_confirmed",
            "reason_text_public": "趋势条件确认后建立仓位",
            "evidence": {"close_above_fast_ma": True},
            "status": "RECORDED",
        },
        {
            "event_id": "order-1",
            "event_type": "ORDER_INTENT",
            "strategy_id": "demo",
            "symbol": "AAA",
            "side": "BUY",
            "decision_date": "2024-01-01",
            "effective_date": "2024-01-02",
            "reason_code": "trend_confirmed",
            "reason_text_public": "趋势条件确认后建立仓位",
            "evidence": {"close_above_fast_ma": True},
            "order_id": "order-1",
            "quantity": 100,
            "status": "PLANNED",
        },
        {
            "event_id": "fill-1",
            "event_type": "FILL",
            "strategy_id": "demo",
            "symbol": "AAA",
            "side": "BUY",
            "decision_date": "2024-01-01",
            "effective_date": "2024-01-02",
            "fill_date": "2024-01-02",
            "reason_code": "trend_confirmed",
            "reason_text_public": "趋势条件确认后建立仓位",
            "evidence": {"close_above_fast_ma": True},
            "order_id": "order-1",
            "fill_id": "fill-1",
            "quantity": 100,
            "price": 10.0,
            "status": "FILLED",
        },
        {
            "event_id": "signal-2",
            "event_type": "SIGNAL",
            "strategy_id": "demo",
            "symbol": "AAA",
            "side": "SELL",
            "decision_date": "2024-01-03",
            "effective_date": "2024-01-04",
            "reason_code": "trend_break",
            "reason_text_public": "趋势条件破坏后退出",
            "evidence": {"fast_ma_above_slow_ma": False},
            "status": "RECORDED",
        },
        {
            "event_id": "order-2",
            "event_type": "ORDER_INTENT",
            "strategy_id": "demo",
            "symbol": "AAA",
            "side": "SELL",
            "decision_date": "2024-01-03",
            "effective_date": "2024-01-04",
            "reason_code": "trend_break",
            "reason_text_public": "趋势条件破坏后退出",
            "evidence": {"fast_ma_above_slow_ma": False},
            "order_id": "order-2",
            "quantity": 100,
            "status": "REJECTED",
            "constraint_status": "INSUFFICIENT_POSITION",
        },
    ]


def test_details_link_signal_order_fill_and_separate_execution_counts():
    details = build_strategy_result_details(
        events(),
        fills=[{"fill_id": "fill-1", "order_id": "order-1", "symbol": "AAA", "side": "BUY", "quantity": 100, "price": 10.0, "fee": 1.0, "fill_date": "2024-01-02"}],
        initial_cash=2000.0,
    )

    assert details["schema_version"] == "strategy-result-details.v1"
    assert details["summary"] == {"signals": 2, "orders": 2, "fills": 1, "rejected_orders": 1}
    assert details["trades"][0]["signal_id"] == "signal-1"
    assert details["trades"][0]["order_id"] == "order-1"
    assert details["trades"][0]["fill_id"] == "fill-1"
    assert details["trades"][0]["reason_code"] == "trend_confirmed"
    assert details["trades"][1]["status"] == "REJECTED"
    assert details["trades"][1]["fill_id"] is None
    assert details["trades"][1]["constraint_status"] == "INSUFFICIENT_POSITION"
    assert details["positions"][-1] == {"date": "2024-01-02", "symbol": "AAA", "quantity": 100, "cash": 999.0}


def test_strategy_result_summary_keeps_first_screen_metrics_and_cost_context():
    summary = build_strategy_result_summary(
        {
            "total_return": 0.125,
            "max_drawdown": -0.08,
            "sharpe": 1.42,
            "annual_return": 0.2,
            "total_cost": 0.003,
            "trades": 7,
        },
        {"signals": 9, "orders": 8, "fills": 7, "rejected_orders": 1},
    )

    assert summary == {
        "total_return": 0.125,
        "max_drawdown": -0.08,
        "trades": 7,
        "total_cost": 0.003,
        "signals": 9,
        "orders": 8,
        "fills": 7,
        "rejected_orders": 1,
        "sharpe": 1.42,
        "annual_return": 0.2,
    }


def test_strategy_result_summary_uses_none_for_missing_metrics():
    summary = build_strategy_result_summary({}, {})

    assert summary["total_return"] is None
    assert summary["max_drawdown"] is None
    assert summary["trades"] == 0
    assert summary["total_cost"] is None


def test_strategy_result_payload_has_one_source_for_summary_curve_details_and_limits():
    performance = {"metrics": {"total_return": 0.1, "max_drawdown": -0.05, "trades": 2}}
    details = {"summary": {"signals": 2, "orders": 2, "fills": 2, "rejected_orders": 0}, "trades": [], "positions": []}
    payload = build_strategy_result_payload(
        metrics=performance["metrics"],
        performance=performance,
        details=details,
        strategy_config={"rules": ["信号下一交易日执行"]},
        research_diagnostics={"data_quality_warnings": []},
        run_manifest={"schema_version": "run-manifest.v1"},
        integrity={"status": "DECLARED_TIMING_CHECKED"},
        limitations=["离线历史研究模拟"],
    )

    assert payload["summary"]["total_return"] == 0.1
    assert payload["performance"] is performance
    assert payload["details"] is details
    assert payload["strategy_config"]["rules"] == ["信号下一交易日执行"]
    assert payload["limitations"] == ["离线历史研究模拟"]


def test_strategy_result_payload_can_carry_parameter_sensitivity_for_detail_views():
    sensitivity = [{"参数": "fast=15,slow=50", "额外滑点bp": 0, "区间收益": 0.12}]
    payload = build_strategy_result_payload(
        metrics={"total_return": 0.1},
        performance={"curve": [], "metrics": {"total_return": 0.1}},
        details={"summary": {}, "trades": [], "positions": []},
        strategy_config={"rules": ["信号下一交易日执行"]},
        research_diagnostics={},
        run_manifest={},
        integrity={},
        limitations=["离线历史研究模拟"],
        sensitivity=sensitivity,
    )

    assert payload["sensitivity"] == sensitivity


def test_details_rejects_duplicate_ids_or_reason_mismatch():
    duplicate = events() + [dict(events()[0])]
    with pytest.raises(ValueError, match="duplicate"):
        build_strategy_result_details(duplicate, fills=[], initial_cash=1000.0)

    mismatch = events()
    mismatch[1] = {**mismatch[1], "reason_code": "wrong_reason"}
    with pytest.raises(ValueError, match="reason"):
        build_strategy_result_details(mismatch, fills=[], initial_cash=1000.0)


def test_strategy_archive_is_reproducible_and_excludes_private_material():
    archive = create_strategy_archive(
        strategy={"strategy_id": "demo", "version": "1.0", "rules": {"buy": "threshold"}},
        dataset={"dataset_id": "demo-v1", "content_hash": "abc123"},
        execution={"policy_id": "offline-next-open", "fill_model": "next_open", "commission_bps": 5.0},
        result={"details": build_strategy_result_details(events(), fills=[], initial_cash=1000.0)},
        limitations=["synthetic demo data", "offline research simulation"],
    )

    loaded = load_strategy_archive(archive)
    assert loaded["schema_version"] == "strategy-archive.v1"
    assert loaded["manifest"]["checksum"]
    assert loaded["manifest"]["limitations"] == ["synthetic demo data", "offline research simulation"]
    assert loaded["result"]["details"]["summary"]["signals"] == 2
    assert "private_path" not in json.dumps(loaded, ensure_ascii=False)
    assert "callable" not in json.dumps(loaded, ensure_ascii=False)
    assert load_strategy_archive(archive) == loaded


def test_strategy_archive_rejects_private_paths_and_tampering():
    with pytest.raises(StrategyArchiveError, match="private"):
        create_strategy_archive(
            strategy={"strategy_id": "demo", "private_path": "D:/secret"},
            dataset={"dataset_id": "demo-v1"},
            execution={"policy_id": "offline"},
            result={"details": {}},
            limitations=["demo"],
        )

    archive = create_strategy_archive(
        strategy={"strategy_id": "demo"}, dataset={"dataset_id": "demo"},
        execution={"policy_id": "offline"}, result={"details": {}}, limitations=["demo"],
    )
    tampered = dict(archive)
    tampered["result"] = {"details": {"changed": True}}
    with pytest.raises(StrategyArchiveError, match="checksum"):
        load_strategy_archive(tampered)


def test_real_single_stock_events_supply_their_own_fill_details():
    research = run_single_stock_research(
        research_frame(),
        strategy_key="trend",
        params={"fast_window": 15, "slow_window": 50},
        transaction_cost=0.001,
    )

    details = build_strategy_result_details(
        research.trade_events,
        initial_cash=100_000.0,
    )
    event_fills = [event for event in research.trade_events if event["event_type"] == "FILL"]

    assert details["summary"]["signals"] == len(
        [event for event in research.trade_events if event["event_type"] == "SIGNAL"]
    )
    assert details["summary"]["orders"] == len(
        [event for event in research.trade_events if event["event_type"] == "ORDER_INTENT"]
    )
    assert details["summary"]["fills"] == len(event_fills)
    assert len(details["positions"]) == len(event_fills)
    assert details["positions"][-1]["quantity"] == 1
    assert details["positions"][-1]["cash"] < 100_000.0


def test_real_empty_single_stock_events_keep_a_valid_empty_details_state():
    frame = research_frame()
    frame[["open", "high", "low", "close"]] = 100.0
    research = run_single_stock_research(frame, strategy_key="trend")

    details = build_strategy_result_details(research.trade_events, initial_cash=100_000.0)

    assert details["summary"] == {"signals": 0, "orders": 0, "fills": 0, "rejected_orders": 0}
    assert details["trades"] == []
    assert details["positions"] == []


def test_real_single_stock_result_can_be_archived_and_reloaded():
    research = run_single_stock_research(
        research_frame(),
        strategy_key="trend",
        params={"fast_window": 15, "slow_window": 50},
    )
    details = build_strategy_result_details(research.trade_events, initial_cash=100_000.0)
    sensitivity = [{"scenario_id": "baseline", "total_return": 0.1}]
    archive = create_strategy_archive(
        strategy={"strategy_id": "trend", "version": "1.0"},
        dataset={"symbol": "DEMO", "rows": len(research.frame), "content_hash": "fixture-hash"},
        execution={"mode": "offline_research_simulation", "transaction_cost": 0.001},
        result={"details": details, "sensitivity": sensitivity},
        limitations=["离线历史研究模拟", "不代表实时或实盘结果"],
    )

    loaded = load_strategy_archive(archive)

    assert loaded["manifest"]["checksum"] == archive["manifest"]["checksum"]
    assert loaded["result"]["details"]["summary"]["fills"] == details["summary"]["fills"]
    assert loaded["result"]["details"]["positions"] == details["positions"]
    assert loaded["result"]["sensitivity"] == sensitivity
