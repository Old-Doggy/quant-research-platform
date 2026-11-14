from __future__ import annotations

import json

import pandas as pd
import pytest

from portfolio_app.contracts import ContractViolation, DatasetManifest
from portfolio_app.data_catalog import build_dataset_manifest


def _legacy_manifest(**overrides: object) -> DatasetManifest:
    values: dict[str, object] = {
        "dataset_id": "legacy.daily.v1",
        "display_name": "Legacy daily bars",
        "source_kind": "imported_file",
        "license_note": "user supplied",
        "frequency": "1d",
        "price_mode": "raw",
        "start_date": "2024-01-02",
        "end_date": "2024-01-03",
        "symbol_count": 1,
        "row_count": 2,
        "required_columns": ("trade_date", "symbol", "open", "high", "low", "close"),
        "quality_status": "passed",
        "generated_at": "2026-10-28T00:00:00Z",
    }
    values.update(overrides)
    return DatasetManifest(**values)


def test_legacy_manifest_still_constructs_with_safe_unknown_capabilities():
    manifest = _legacy_manifest()

    assert manifest.calendar_id == "unknown"
    assert manifest.price_unit == "unknown"
    assert manifest.volume_unit == "unknown"
    assert manifest.availability_status == "unknown"
    assert manifest.point_in_time == "unknown"
    assert manifest.corporate_actions == "unknown"
    assert manifest.redistribution == "unknown"
    assert manifest.capabilities == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("frequency", "5d"),
        ("price_mode", "split_adjusted"),
        ("price_unit", "lots"),
        ("volume_unit", "money"),
        ("availability_status", "live_guess"),
        ("point_in_time", "maybe"),
        ("corporate_actions", "partialish"),
        ("redistribution", "unclear"),
    ],
)
def test_manifest_rejects_unknown_enum_values(field: str, value: str):
    with pytest.raises(ContractViolation):
        _legacy_manifest(**{field: value})


def test_unknown_capabilities_never_become_positive_support_claims():
    manifest = _legacy_manifest(
        capabilities=("unknown",),
        point_in_time="unknown",
        corporate_actions="unknown",
    )

    assert "unknown" in manifest.capabilities
    assert "cash_backtest" not in manifest.capabilities
    assert manifest.point_in_time == "unknown"
    assert manifest.corporate_actions == "unknown"


def test_adjusted_prices_cannot_claim_raw_price_share_ledger():
    with pytest.raises(ContractViolation, match="raw_price_share_ledger"):
        _legacy_manifest(price_mode="qfq", capabilities=("raw_price_share_ledger",))


def test_cash_backtest_requires_raw_prices_and_complete_corporate_actions():
    with pytest.raises(ContractViolation, match="corporate_actions"):
        _legacy_manifest(capabilities=("cash_backtest",), corporate_actions="unknown")

    with pytest.raises(ContractViolation, match="price_mode"):
        _legacy_manifest(
            price_mode="hfq",
            corporate_actions="complete",
            capabilities=("cash_backtest",),
        )


def test_manifest_to_dict_serializes_all_capability_fields():
    manifest = _legacy_manifest(
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
        price_unit="currency_per_share",
        volume_unit="shares",
        availability_status="historical_cutoff",
        point_in_time="known",
        corporate_actions="complete",
        redistribution="allowed",
        price_relation="raw_or_adjusted_explicit",
        adjustment_factor_status="not_applicable",
        capabilities=("stock_chart", "factor_research"),
    )

    payload = manifest.to_dict()

    assert payload["calendar_id"] == "cn_stock_exchange"
    assert payload["price_relation"] == "raw_or_adjusted_explicit"
    assert payload["capabilities"] == ["stock_chart", "factor_research"]
    json.dumps(payload)


def test_build_manifest_accepts_explicit_data_semantics_and_capabilities():
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "symbol": ["AAA", "AAA"],
            "open": [10.0, 10.5],
            "high": [11.0, 11.5],
            "low": [9.0, 10.0],
            "close": [10.5, 11.0],
            "vol": [100, 120],
        }
    )

    manifest = build_dataset_manifest(
        frame,
        dataset_id="explicit.v1",
        display_name="Explicit semantics",
        source_kind="imported_file",
        license_note="user supplied",
        price_mode="raw",
        calendar_id="cn_stock_exchange",
        market="CN_STOCK",
        timezone="Asia/Shanghai",
        price_unit="currency_per_share",
        volume_unit="shares",
        availability_status="historical_cutoff",
        point_in_time="known",
        corporate_actions="complete",
        redistribution="restricted",
        price_relation="raw_or_adjusted_explicit",
        adjustment_factor_status="available_separately",
        capabilities=("stock_chart", "factor_research", "cash_backtest"),
    )

    assert manifest.market == "CN_STOCK"
    assert manifest.capabilities == ("stock_chart", "factor_research", "cash_backtest")
    assert manifest.optional_columns == ("vol",)
