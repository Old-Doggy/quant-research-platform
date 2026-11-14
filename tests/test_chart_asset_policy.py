from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "portfolio_app" / "chart_assets"
RUNTIME = ASSETS / "lightweight-charts.standalone.production.js"
RUNTIME_SHA256 = "46fc69534ec098f095bbcd1d9a26d693d39a8b9eeff7343536765b3dd28c2bdf"


def test_vendor_license_and_notice_preserve_pinned_upstream_content():
    license_text = (ASSETS / "LICENSE.txt").read_text(encoding="utf-8")
    normalized = license_text.rstrip() + "\n"
    assert hashlib.sha256(normalized.encode("utf-8")).hexdigest() == (
        "70c9d5382506dd184465425c08a99ad9bd6d9ac1313c252968ba0b585e5ef823"
    )
    notice = (ASSETS / "NOTICE.txt").read_text(encoding="utf-8")
    # Upstream uses the trademark symbol and Cyrillic small es in its notice.
    assert notice.startswith(
        "TradingView Lightweight Charts\u2122\n"
        "Copyright (\u0441) 2023 TradingView, Inc. https://www.tradingview.com/\n"
    )
    assert "Copyright (c) 2019 TradingView, Inc" in notice
    assert "The above copyright notice and this permission notice shall be included" in notice
    assert "Copyright (c) Microsoft Corporation." in notice


def test_vendored_chart_asset_has_pinned_metadata_license_and_attribution():
    assert hashlib.sha256(RUNTIME.read_bytes()).hexdigest() == RUNTIME_SHA256
    metadata = json.loads((ASSETS / "METADATA.json").read_text(encoding="utf-8"))
    assert metadata == {
        "package": "lightweight-charts",
        "version": "4.2.0",
        "license": "Apache-2.0",
        "source": "https://github.com/tradingview/lightweight-charts/tree/v4.2.0",
        "sha256": RUNTIME_SHA256,
        "cdn_required": False,
        "api_generation": "4.2",
    }
    header = RUNTIME.read_text(encoding="utf-8")[:400]
    assert "TradingView Lightweight Charts" in header
    assert "v4.2.0" in header
    assert "Apache License 2.0" in header
    license_text = (ASSETS / "LICENSE.txt").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in license_text
    assert len(license_text) > 10_000
    assert "Copyright 2023 TradingView, Inc." in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
    notice = (ASSETS / "NOTICE.txt").read_text(encoding="utf-8")
    assert "TradingView Lightweight Charts" in notice
    assert "https://www.tradingview.com/" in notice
    assert "fancy-canvas 2.1.0" in notice
    assert "BSD Zero Clause License" in notice


def test_chart_sources_use_only_pinned_42_api_and_no_cdn_dependency():
    sources = [ASSETS / "workbench.js", ROOT / "portfolio_app" / "chart_bridge.py"]
    sources.extend((ROOT / "tools" / "probes" / "chart_component").glob("*.js"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    assert "addCandlestickSeries" in text
    assert "subscribeVisibleLogicalRangeChange" in text
    assert not re.search(r"\.addSeries\s*\(", text)
    assert "createSeriesMarkers(" not in text
    assert "<script src=\"http" not in text
    assert "cdn." not in text.lower()


def test_rendered_chart_embeds_runtime_and_preserves_visible_attribution():
    from portfolio_app.chart_bridge import chart_bridge_html
    from portfolio_app.chart_payload import build_ohlcv_payload
    import pandas as pd

    class Resources(HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts = []
            self.links = []

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.scripts.append(dict(attrs))
            elif tag == "a":
                self.links.append(dict(attrs))

    html = chart_bridge_html(build_ohlcv_payload(pd.DataFrame(), symbol="EMPTY"))
    resources = Resources()
    resources.feed(html)
    assert resources.scripts
    assert all("src" not in script for script in resources.scripts)
    assert any(link.get("href") == "https://www.tradingview.com/" for link in resources.links)
    assert RUNTIME.read_text(encoding="utf-8") in html


def test_metadata_and_license_have_final_newlines():
    for name in ("METADATA.json", "LICENSE.txt", "NOTICE.txt", "README.md"):
        content = (ASSETS / name).read_bytes()
        content.decode("utf-8")
        assert content.endswith(b"\n")


@pytest.mark.parametrize("name", ["METADATA.json", "LICENSE.txt", "NOTICE.txt"])
def test_required_attribution_files_are_regular_files(name):
    path = ASSETS / name
    assert path.is_file()
    assert not path.is_symlink()
