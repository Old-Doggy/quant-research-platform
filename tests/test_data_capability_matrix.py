from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_app.data_capability import (
    build_capability_matrix,
    scan_local_data_capabilities,
)


def test_demo_and_local_price_tiers_report_explicit_capabilities_without_private_paths(tmp_path: Path):
    (tmp_path / "daily_raw_merged").mkdir()
    (tmp_path / "daily_qfq_merged").mkdir()
    (tmp_path / "daily_hfq_merged").mkdir()
    (tmp_path / "daily_raw_merged" / "000001.SZ.csv").write_text(
        "ts_code,trade_date,open,high,low,close,vol,amount\n"
        "000001.SZ,20240102,10,11,9,10.5,100,1050\n"
        "000001.SZ,20240103,10.5,12,10,11,120,1320\n",
        encoding="utf-8",
    )
    (tmp_path / "daily_qfq_merged" / "000001.SZ.csv").write_text(
        "ts_code,trade_date,open,high,low,close\n"
        "000001.SZ,20240102,10,11,9,10.5\n",
        encoding="utf-8",
    )

    matrix = scan_local_data_capabilities(tmp_path)
    by_id = {item["dataset_id"]: item for item in matrix}

    assert by_id["local.daily_raw_merged"]["source"] == "local_directory"
    assert by_id["local.daily_raw_merged"]["price_mode"] == "raw"
    assert by_id["local.daily_raw_merged"]["point_in_time"] == "unknown"
    assert by_id["local.daily_raw_merged"]["corporate_actions"] == "unknown"
    assert by_id["local.daily_raw_merged"]["coverage_scope"] == "directory_observed"
    assert by_id["local.daily_raw_merged"]["observed_start"] == "2024-01-02"
    assert by_id["local.daily_raw_merged"]["observed_end"] == "2024-01-03"
    assert by_id["local.daily_raw_merged"]["price_relation"] == "raw_only"
    assert by_id["local.daily_qfq_merged"]["price_relation"] == "adjusted_only"
    assert by_id["local.daily_hfq_merged"]["price_relation"] == "adjusted_only"
    assert by_id["local.daily_raw_merged"]["observed_columns"] == [
        "amount", "close", "high", "low", "open", "trade_date", "ts_code", "vol",
    ]
    assert by_id["local.daily_raw_merged"]["file_count"] == 1
    assert "tmp_path" not in str(matrix)
    assert str(tmp_path) not in str(matrix)


def test_matrix_preserves_unknowns_and_does_not_infer_execution_capability():
    matrix = build_capability_matrix()
    assert matrix
    for item in matrix:
        assert set(item) == {
            "dataset_id", "display_name", "source", "license", "frequency",
            "price_mode", "calendar_id", "market", "timezone", "price_unit",
            "volume_unit", "units", "coverage_scope", "observed_start",
            "observed_end", "cutoff_status", "point_in_time",
            "corporate_actions", "price_relation", "adjustment_factor_status",
            "redistribution", "required_columns", "optional_columns",
            "observed_columns", "file_count", "quality_status", "research_uses", "limitations",
        }
        assert isinstance(item["units"], str) and item["units"]
        assert isinstance(item["license"], str) and item["license"]
        for key in ("cutoff_status", "point_in_time", "corporate_actions"):
            assert item[key] in {"known", "unknown", "not_applicable"}
        assert "can_execute" not in item
        assert "can_backtest" not in item


def test_matrix_capabilities_use_manifest_vocabulary_and_keep_price_accounting_explicit():
    matrix = build_capability_matrix()
    demo = matrix[0]

    assert set(demo["research_uses"]).issubset({
        "stock_chart", "indicator_research", "factor_research", "signal_research",
        "demo_backtest", "cash_backtest", "local_backtest_input", "raw_price_share_ledger",
        "universe_research", "derivatives_research", "convertible_bond_research",
        "regime_research", "unknown",
    })
    assert demo["price_relation"] == "raw_only"
    assert demo["adjustment_factor_status"] == "not_applicable"
    assert demo["calendar_id"] == "cn_stock_exchange"
    assert demo["market"] == "CN_STOCK"
    assert demo["price_unit"] == "currency_per_share"
    assert demo["volume_unit"] == "shares"
    assert demo["redistribution"] == "allowed"
    assert demo["point_in_time"] == "not_applicable"
    assert demo["corporate_actions"] == "not_applicable"


def test_empty_or_missing_root_is_safe_and_reports_no_false_data_capabilities(tmp_path: Path):
    matrix = scan_local_data_capabilities(tmp_path / "missing")
    assert matrix == []


def test_scan_rejects_file_root_and_never_writes_to_data(tmp_path: Path):
    root = tmp_path / "data.txt"
    root.write_text("private data", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        scan_local_data_capabilities(root)
    assert list(tmp_path.iterdir()) == [root]


def test_scan_ignores_unapproved_private_runtime_directories(tmp_path: Path):
    private = tmp_path / "capital_controller_runtime"
    private.mkdir()
    (private / "secret.json").write_text('{"account_id":"private"}', encoding="utf-8")
    assert scan_local_data_capabilities(tmp_path) == []


def test_scan_covers_research_asset_directories_with_domain_specific_fields(tmp_path: Path):
    (tmp_path / "index_weights").mkdir()
    (tmp_path / "index_weights" / "weight_000300.SH.csv").write_text(
        "index_code,con_code,trade_date,weight\n000300.SH,000001.SZ,20240102,1.2\n",
        encoding="utf-8",
    )
    (tmp_path / "options_daily").mkdir()
    (tmp_path / "options_daily" / "quotes.csv").write_text(
        "ts_code,trade_date,close,exercise_price,maturity_date\nOPT,20240102,1.2,3.0,20240626\n",
        encoding="utf-8",
    )

    matrix = {item["dataset_id"]: item for item in scan_local_data_capabilities(tmp_path)}
    assert matrix["local.index_weights"]["required_columns"] == [
        "index_code", "con_code", "trade_date", "weight",
    ]
    assert matrix["local.index_weights"]["research_uses"] == ["universe_research"]
    assert matrix["local.options_daily"]["price_mode"] == "unknown"
    assert matrix["local.options_daily"]["corporate_actions"] == "unknown"
    assert "exercise_price" in matrix["local.options_daily"]["observed_columns"]


def test_scan_covers_macro_inputs_but_keeps_pit_and_license_unknown(tmp_path: Path):
    (tmp_path / "macro").mkdir()
    (tmp_path / "macro" / "macro_features.csv").write_text(
        "trade_date,series,value\n20240102,credit_spread,1.2\n",
        encoding="utf-8",
    )
    matrix = {item["dataset_id"]: item for item in scan_local_data_capabilities(tmp_path)}
    assert matrix["local.macro"]["required_columns"] == ["trade_date", "series", "value"]
    assert matrix["local.macro"]["point_in_time"] == "unknown"
    assert matrix["local.macro"]["license"] == "unknown"
    assert matrix["local.macro"]["units"] == "series values: source-defined macro indicator units"


def test_scan_covers_stock_pool_membership_without_claiming_historical_pit(tmp_path: Path):
    (tmp_path / "stock_pools" / "code_lists").mkdir(parents=True)
    (tmp_path / "stock_pools" / "code_lists" / "pool.txt").write_text("000001.SZ\n", encoding="utf-8")
    matrix = {item["dataset_id"]: item for item in scan_local_data_capabilities(tmp_path)}
    assert matrix["local.stock_pools"]["units"] == "symbol: instrument identifier; count: constituent count"
    assert matrix["local.stock_pools"]["point_in_time"] == "unknown"
