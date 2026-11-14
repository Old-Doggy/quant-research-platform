from __future__ import annotations

import pandas as pd

from portfolio_app.stock_catalog import (
    build_market_view,
    build_stock_catalog,
    search_stock_catalog,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "600000.SH", "600000.SH"],
            "trade_date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-02", "2025-01-03"]),
            "open": [10.0, 10.2, 8.0, 8.1],
            "high": [10.3, 10.5, 8.2, 8.3],
            "low": [9.8, 10.0, 7.9, 8.0],
            "close": [10.1, 10.4, 8.1, 8.2],
            "pre_close": [10.0, 10.1, 8.0, 8.1],
            "vol": [1000, 1200, 800, 900],
        }
    )


def test_catalog_contains_symbols_names_and_latest_quote_metadata():
    catalog = build_stock_catalog(
        _frame(),
        names={"000001.SZ": "平安银行", "600000.SH": "浦发银行"},
        price_unit="CNY/share",
        volume_unit="shares",
    )

    assert [item["symbol"] for item in catalog] == ["000001.SZ", "600000.SH"]
    assert catalog[0]["name"] == "平安银行"
    assert catalog[0]["latest_date"] == "2025-01-03"
    assert catalog[0]["close"] == 10.4
    assert catalog[0]["price_unit"] == "CNY/share"
    assert catalog[0]["volume_unit"] == "shares"


def test_search_matches_code_or_name_and_empty_query_returns_catalog():
    catalog = build_stock_catalog(_frame(), names={"000001.SZ": "平安银行", "600000.SH": "浦发银行"})

    assert [item["symbol"] for item in search_stock_catalog(catalog, "000001")] == ["000001.SZ"]
    assert [item["symbol"] for item in search_stock_catalog(catalog, "浦发")] == ["600000.SH"]
    assert len(search_stock_catalog(catalog, "")) == 2
    assert search_stock_catalog(catalog, "不存在") == []


def test_market_view_is_pure_quote_view_and_does_not_infer_strategy_state():
    view = build_market_view(
        _frame(),
        symbol="000001.SZ",
        name="平安银行",
        price_unit="CNY/share",
        volume_unit="shares",
    )

    assert view["status"] == "READY"
    assert view["symbol"] == "000001.SZ"
    assert view["name"] == "平安银行"
    assert view["quote"]["previous_close"] == 10.1
    assert view["quote"]["change"] == 10.4 / 10.1 - 1
    assert view["quote"]["price_unit"] == "CNY/share"
    assert "strategy_state" not in view["quote"]
    assert "signal_state" not in view["quote"]
    assert len(view["history"]) == 2


def test_market_view_recovers_from_empty_or_unknown_symbol():
    empty = build_market_view(pd.DataFrame(), symbol="000001.SZ")
    missing = build_market_view(_frame(), symbol="999999.SZ")

    assert empty["status"] == "EMPTY"
    assert empty["history"] == []
    assert missing["status"] == "NOT_FOUND"
    assert missing["history"] == []
