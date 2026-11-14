from __future__ import annotations

import json
from pathlib import Path


ASSET_ROOT = Path(__file__).resolve().parent / "chart_assets"
VENDOR_ASSET = ASSET_ROOT / "lightweight-charts.standalone.production.js"


def _range_presets(period: str) -> tuple[tuple[str, int], ...]:
    """Return human-readable ranges whose units match the displayed K line."""
    presets = {
        "1d": (("1个月", 30), ("3个月", 60), ("6个月", 120), ("1年", 250)),
        "1w": (("3个月", 13), ("6个月", 26), ("1年", 52), ("2年", 104)),
        "1m": (("6个月", 6), ("1年", 12), ("2年", 24), ("5年", 60)),
    }
    return presets.get(str(period), presets["1d"])


def chart_bridge_html(payload: dict[str, object], *, height: int = 760) -> str:
    """Embed one offline terminal with a shared range policy across all panes."""
    if height < 240:
        raise ValueError("height must be at least 240")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if "</script" in serialized.lower():
        raise ValueError("chart payload contains unsafe script terminator")
    css = (ASSET_ROOT / "workbench.css").read_text(encoding="utf-8")
    runtime = (ASSET_ROOT / "workbench.js").read_text(encoding="utf-8")
    vendor = VENDOR_ASSET.read_text(encoding="utf-8") if VENDOR_ASSET.is_file() else ""
    range_buttons = "".join(
        f'<button data-bars="{bars}">{label}</button>'
        for label, bars in _range_presets(str(payload.get("period", "1d")))
    )
    range_buttons += '<button data-bars="all">全部</button>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>:root {{ --chart-height: {height}px; }}\n{css}</style></head><body>
<div id="chart" data-chart-engine="lightweight-charts">
<div class="toolbar"><div class="periods">
{range_buttons}
</div><div class="tools"><button data-action="zoom-in" title="放大" aria-label="放大">+</button>
<button data-action="zoom-out" title="缩小" aria-label="缩小">−</button>
<button data-action="reset" title="回到最近区间" aria-label="回到最近区间">↺</button>
<button data-action="full" title="全屏" aria-label="全屏">⛶</button></div></div>
<div class="chart-meta" aria-live="polite"><strong id="period-label"></strong><span id="period-basis"></span><span id="period-status"></span><span id="zoom-limit-label"></span></div>
<div class="event-toolbar"><strong>研究事件</strong><button data-layer="all" class="selected">全部</button><button data-layer="SIGNAL">信号</button><button data-layer="ORDER_INTENT">订单</button><button data-layer="FILL">成交</button><button data-action="data-detail">行情详情</button></div>
<div id="event-strip" aria-label="研究事件列表"></div>
<div id="panes"></div><aside id="data-detail-drawer" class="drawer" aria-hidden="true"><div class="drawer-head"><strong id="drawer-title">详情</strong><button data-action="close-drawer" aria-label="关闭详情">×</button></div><div id="drawer-body"></div></aside><div class="chart-footer"><span id="range-label"></span>
<a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView Lightweight Charts</a></div>
</div><script type="application/json" id="chart-payload">{serialized}</script>
<script>window.__QUANT_CHART_PAYLOAD__ = JSON.parse(document.getElementById('chart-payload').textContent);</script>
<script>{vendor}</script><script>{runtime}</script></body></html>'''


def local_asset_status() -> dict[str, object]:
    return {"available": VENDOR_ASSET.is_file(), "path": str(VENDOR_ASSET),
            "size": VENDOR_ASSET.stat().st_size if VENDOR_ASSET.is_file() else 0}
