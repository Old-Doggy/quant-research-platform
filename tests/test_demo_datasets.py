from __future__ import annotations

import pandas as pd
import pytest

from portfolio_app.demo_datasets import (
    build_fault_fixture,
    build_normal_fixture,
    generate_cross_section_demo,
    summarize_fixture_quality,
)


def test_cross_section_demo_rebuilds_120_assets_and_756_sessions_deterministically():
    first = generate_cross_section_demo()
    second = generate_cross_section_demo()

    assert first.frame.shape[0] == 120 * 756
    assert first.frame["symbol"].nunique() == 120
    assert first.frame["trade_date"].nunique() == 756
    assert first.frame.groupby("symbol")["trade_date"].nunique().eq(756).all()
    assert first.content_hash == second.content_hash
    pd.testing.assert_frame_equal(first.frame, second.frame)


def test_cross_section_demo_is_explicitly_synthetic_and_not_market_evidence():
    demo = generate_cross_section_demo(sessions=80, assets=12, seed=11)
    metadata = demo.metadata
    manifest = demo.manifest.to_dict()

    assert metadata["synthetic"] is True
    assert metadata["source_kind"] == "generated_demo"
    assert metadata["calendar_claim"] == "synthetic_weekday_sequence"
    assert "market meaning" in " ".join(metadata["limitations"])
    assert manifest["source_kind"] == "generated_demo"
    assert manifest["license_note"] == "generated_demo_only"
    assert manifest["calendar_id"] == "custom"
    assert manifest["point_in_time"] == "not_applicable"
    assert "cash_backtest" not in manifest["capabilities"]


@pytest.mark.parametrize(
    "case",
    ["missing_session", "listing_exit", "suspension", "price_limit", "unit_mismatch"],
)
def test_fault_fixtures_are_separate_and_have_explicit_quality_counts(case: str):
    fixture = build_fault_fixture(case)
    quality = summarize_fixture_quality(fixture)

    assert fixture.is_fault is True
    assert quality["status"] == "需复核"
    assert quality["fault_case"] == case
    assert quality["synthetic"] is True
    assert quality["market_evidence"] is False
    assert quality["fault_counts"][case] >= 1


def test_normal_fixture_has_no_fault_labels_or_false_market_claims():
    fixture = build_normal_fixture()
    quality = summarize_fixture_quality(fixture)

    assert fixture.is_fault is False
    assert quality["status"] == "通过"
    assert quality["fault_counts"] == {
        "missing_session": 0,
        "listing_exit": 0,
        "suspension": 0,
        "price_limit": 0,
        "unit_mismatch": 0,
    }
    assert quality["market_evidence"] is False
    assert quality["invalid_ohlc_rows"] == 0
    assert quality["non_positive_price_rows"] == 0


def test_fault_quality_does_not_repair_or_silently_drop_rows():
    fixture = build_fault_fixture("missing_session")
    before = fixture.frame.copy(deep=True)
    quality = summarize_fixture_quality(fixture)

    assert len(fixture.frame) == len(before)
    pd.testing.assert_frame_equal(fixture.frame, before)
    assert quality["fault_counts"]["missing_session"] == 1


def test_price_limit_fault_is_detected_from_price_change_and_marked_explicitly():
    fixture = build_fault_fixture("price_limit")
    quality = summarize_fixture_quality(fixture)

    assert quality["fault_counts"]["price_limit"] >= 1
    assert quality["price_limit_rows"] >= 1
    assert quality["invalid_ohlc_rows"] == 0


def test_unknown_fault_case_is_rejected():
    with pytest.raises(ValueError, match="fault case"):
        build_fault_fixture("future_leak")
