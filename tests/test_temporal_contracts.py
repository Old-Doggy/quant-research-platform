from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from portfolio_app.temporal_contracts import (
    TemporalContractViolation,
    build_session_calendar,
    filter_point_in_time,
    load_session_calendar,
    missing_session_calendar,
    select_membership_as_of,
    temporal_readiness,
    validate_point_in_time_frame,
)
from portfolio_app.contracts import DatasetManifest


def test_session_calendar_uses_explicit_sessions_and_does_not_treat_weekends_as_sessions():
    calendar = build_session_calendar(
        ["2024-02-08", "2024-02-09", "2024-02-19"],
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
    )

    assert calendar.status == "verified"
    assert calendar.is_session("2024-02-09") is True
    assert calendar.is_session("2024-02-10") is False
    assert calendar.is_session("2024-02-12") is False
    assert calendar.is_session("2024-02-19") is True


@pytest.mark.parametrize(
    "sessions",
    [
        ["2024-02-09 09:30:00"],
        ["2024-02-09", "2024-02-09"],
        ["2024-02-10"],
    ],
)
def test_session_calendar_rejects_invalid_or_unverified_session_inputs(sessions):
    with pytest.raises(TemporalContractViolation):
        build_session_calendar(
            sessions,
            calendar_id="cn_stock_exchange",
            market="CN_STOCK",
            timezone="Asia/Shanghai",
        )


def test_session_calendar_distinguishes_date_labels_from_timezone_aware_timestamps():
    calendar = build_session_calendar(
        ["2024-02-09"],
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
    )

    assert calendar.normalize_as_of("2024-02-09").tzinfo is not None
    assert calendar.normalize_as_of("2024-02-09T15:00:00+08:00").hour == 15
    with pytest.raises(TemporalContractViolation, match="timezone"):
        calendar.normalize_as_of("2024-02-09T15:00:00")


def test_session_calendar_can_be_loaded_from_a_session_file(tmp_path: Path):
    source = tmp_path / "sessions.csv"
    source.write_text("trade_date\n20240208\n20240209\n", encoding="utf-8")

    calendar = load_session_calendar(
        source,
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
    )

    assert calendar.sessions == ("2024-02-08", "2024-02-09")
    assert calendar.source_kind == "session_file"


def test_missing_calendar_is_explicitly_blocked_and_never_falls_back_to_weekdays():
    calendar = missing_session_calendar(
        calendar_id="cn_stock_exchange", market="CN_STOCK", timezone="Asia/Shanghai"
    )

    assert calendar.status == "missing"
    assert calendar.can_align is False
    assert calendar.is_session("2024-02-09") is False
    with pytest.raises(TemporalContractViolation, match="calendar"):
        calendar.normalize_as_of("2024-02-09")


def test_point_in_time_validation_rejects_missing_or_naive_available_at():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "effective_from": ["2024-01-02", "2024-01-02"],
            "available_at": ["2024-01-02T16:00:00+08:00", None],
        }
    )
    result = validate_point_in_time_frame(
        frame, as_of="2024-01-03T16:00:00+08:00", timezone="Asia/Shanghai"
    )

    assert result.status == "blocked"
    assert result.missing_available_at == 1
    assert result.can_read is False

    naive = frame.iloc[[0]].copy()
    naive["available_at"] = "2024-01-02T16:00:00"
    with pytest.raises(TemporalContractViolation, match="timezone"):
        validate_point_in_time_frame(
            naive, as_of="2024-01-03T16:00:00+08:00", timezone="Asia/Shanghai"
        )


def test_point_in_time_filter_never_returns_rows_published_after_research_as_of():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB"],
            "effective_from": ["2024-01-02", "2024-01-02", "2024-01-02"],
            "available_at": [
                "2024-01-02T16:00:00+08:00",
                "2024-01-04T09:00:00+08:00",
                "2024-01-03T16:00:00+08:00",
            ],
            "value": [1.0, 2.0, 3.0],
        }
    )

    visible = filter_point_in_time(
        frame, as_of="2024-01-03T16:00:00+08:00", timezone="Asia/Shanghai"
    )

    assert visible["symbol"].tolist() == ["AAA", "BBB"]
    assert visible["value"].tolist() == [1.0, 3.0]


def test_point_in_time_validation_blocks_when_any_available_at_is_after_as_of():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "available_at": ["2024-01-04T09:00:00+08:00"],
        }
    )

    result = validate_point_in_time_frame(
        frame, as_of="2024-01-03T16:00:00+08:00", timezone="Asia/Shanghai"
    )

    assert result.status == "blocked"
    assert result.future_available_at == 1
    assert result.can_read is False


def test_membership_selection_respects_effective_dates_and_available_at():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "effective_from": ["2024-01-01", "2024-01-04", "2024-01-01"],
            "effective_to": ["2024-01-31", "2024-01-31", "2024-01-31"],
            "available_at": [
                "2024-01-02T16:00:00+08:00",
                "2024-01-04T16:00:00+08:00",
                "2024-01-05T16:00:00+08:00",
            ],
        }
    )

    selected = select_membership_as_of(
        frame,
        as_of="2024-01-04T15:00:00+08:00",
        timezone="Asia/Shanghai",
    )

    assert selected["symbol"].tolist() == ["AAA"]


def test_membership_selection_is_blocked_without_available_at():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "effective_from": ["2024-01-01"],
            "effective_to": ["2024-01-31"],
        }
    )

    with pytest.raises(TemporalContractViolation, match="available_at"):
        select_membership_as_of(
            frame,
            as_of="2024-01-04T15:00:00+08:00",
            timezone="Asia/Shanghai",
        )


def test_temporal_readiness_requires_manifest_and_runtime_evidence():
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "available_at": ["2024-01-02T16:00:00+08:00"],
        }
    )
    calendar = build_session_calendar(
        ["2024-01-02"],
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
    )
    manifest = DatasetManifest(
        dataset_id="pit.ready",
        display_name="PIT ready",
        source_kind="user_import",
        license_note="user supplied",
        frequency="1d",
        price_mode="raw",
        start_date="2024-01-02",
        end_date="2024-01-02",
        symbol_count=1,
        row_count=1,
        required_columns=("trade_date", "symbol", "open", "high", "low", "close"),
        quality_status="passed",
        generated_at="2026-10-28T00:00:00Z",
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
        point_in_time="known",
    )

    result = temporal_readiness(
        manifest,
        calendar,
        frame,
        as_of="2024-01-02T16:00:00+08:00",
    )

    assert result.status == "READY"
    assert result.reasons == ()


def test_temporal_readiness_fails_closed_for_unknown_manifest_or_missing_calendar():
    frame = pd.DataFrame({"available_at": ["2024-01-02T16:00:00+08:00"]})
    calendar = missing_session_calendar(
        calendar_id="cn_stock_exchange", market="CN_STOCK", timezone="Asia/Shanghai"
    )
    manifest = DatasetManifest(
        dataset_id="pit.unknown",
        display_name="PIT unknown",
        source_kind="user_import",
        license_note="user supplied",
        frequency="1d",
        price_mode="raw",
        start_date="2024-01-02",
        end_date="2024-01-02",
        symbol_count=1,
        row_count=1,
        required_columns=("trade_date", "symbol", "open", "high", "low", "close"),
        quality_status="passed",
        generated_at="2026-10-28T00:00:00Z",
    )

    result = temporal_readiness(
        manifest,
        calendar,
        frame,
        as_of="2024-01-02T16:00:00+08:00",
    )

    assert result.status == "BLOCKED"
    assert "manifest.point_in_time" in result.reasons
    assert "calendar" in result.reasons
