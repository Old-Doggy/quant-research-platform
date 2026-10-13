from io import BytesIO
from pathlib import Path
import re

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from portfolio_app.backtest import run_backtest, run_equal_weight_portfolio
from portfolio_app.data import build_data_quality_report, read_market_file
from portfolio_app.strategies import STRATEGIES, generate_signal


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "portfolio_app" / "sample_data"


@pytest.mark.parametrize("filename", ["quant_demo_single_symbol.csv", "quant_demo_multi_symbol.csv"])
def test_synthetic_data_quality(filename):
    frame = read_market_file(SAMPLES / filename)
    assert build_data_quality_report(frame)["status"] == "通过"


@pytest.mark.parametrize("strategy", [item.key for item in STRATEGIES])
def test_demo_backtests(strategy):
    frame = read_market_file(SAMPLES / "quant_demo_single_symbol.csv")
    result, metrics = run_backtest(generate_signal(frame, strategy))
    assert len(result) == 300
    assert metrics["observations"] == 300
    assert result["equity"].notna().all()
    frames = {code: group for code, group in read_market_file(SAMPLES / "quant_demo_multi_symbol.csv").groupby("symbol")}
    portfolio, metrics = run_equal_weight_portfolio(frames, strategy)
    assert metrics["symbols"] == 4
    assert portfolio["equity"].notna().all()


@pytest.mark.parametrize("suffix", ["csv", "xlsx", "parquet"])
def test_file_import_formats(suffix):
    raw = pd.read_csv(SAMPLES / "quant_demo_multi_symbol.csv")
    stream = BytesIO()
    stream.name = f"demo.{suffix}"
    if suffix == "csv":
        stream.write(raw.to_csv(index=False).encode("utf-8"))
    elif suffix == "xlsx":
        raw.to_excel(stream, index=False)
    else:
        raw.to_parquet(stream, index=False)
    stream.seek(0)
    frame = read_market_file(stream)
    assert len(frame) == len(raw)
    assert frame["symbol"].nunique() == 4
    assert build_data_quality_report(frame)["status"] == "通过"


@pytest.mark.parametrize("page", ["Quant Dashboard", "数据分析", "策略比较", "项目说明"])
def test_public_pages_have_no_private_controls_or_results(monkeypatch, page):
    monkeypatch.setenv("PORTFOLIO_MODE", "public")
    app = AppTest.from_file(str(ROOT / "portfolio_app" / "app.py"), default_timeout=30).run()
    navigation = app.sidebar.radio[0]
    assert navigation.options == ["Quant Dashboard", "数据分析", "策略比较", "项目说明"]
    navigation.set_value(page).run()
    assert not app.exception
    text = "\n".join(str(element.value) for kind in ("markdown", "caption", "title", "header", "subheader", "info", "warning") for element in app.get(kind))
    assert not re.search(r"模型\d", text)
    assert not any(term in text for term in ("data/output", "manifest.json", "目标仓位"))
    assert not app.get("download_button")
    for select in app.sidebar.selectbox:
        assert "本地行情" not in select.options


def test_public_dashboard_portfolio_and_strategy_controls(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_MODE", "public")
    app = AppTest.from_file(str(ROOT / "portfolio_app" / "app.py"), default_timeout=30).run()
    mode = next(control for control in app.sidebar.radio if control.label == "分析模式")
    mode.set_value("等权组合").run()
    assert not app.exception
    assert any(metric.value == "4 只" for metric in app.metric)
    strategy = next(control for control in app.sidebar.selectbox if control.label == "策略")
    for option in strategy.options:
        strategy.set_value(option).run()
        assert not app.exception
        assert app.get("plotly_chart")


@pytest.mark.parametrize("page", ["Quant Dashboard", "数据分析", "策略比较"])
def test_public_upload_empty_state(monkeypatch, page):
    monkeypatch.setenv("PORTFOLIO_MODE", "public")
    app = AppTest.from_file(str(ROOT / "portfolio_app" / "app.py"), default_timeout=30).run()
    app.sidebar.radio[0].set_value(page).run()
    source = next(control for control in app.sidebar.selectbox if control.label == "数据来源")
    source.set_value("文件导入").run()
    assert not app.exception
    assert app.get("file_uploader")
    assert any(element.value == "暂无导入数据。" for element in app.info)


def test_invalid_import_is_reported():
    stream = BytesIO(b"date,close\n20230103,100\n")
    stream.name = "invalid.csv"
    with pytest.raises(ValueError, match="required columns"):
        read_market_file(stream)
