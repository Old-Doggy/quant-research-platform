# Local Chart Assets

This directory vendors the exact `lightweight-charts` 4.2.0 standalone
runtime used by the offline workbench. The application loads this file from
the repository, so the chart does not require a CDN or an internet connection.

## Provenance

- Source: <https://github.com/tradingview/lightweight-charts/tree/v4.2.0>
- License: Apache-2.0, see [LICENSE.txt](LICENSE.txt)
- Attribution: see [NOTICE.txt](NOTICE.txt)
- Runtime checksum: see [METADATA.json](METADATA.json)
- API generation: 4.2 (`addCandlestickSeries`, `addLineSeries`, and related APIs)

The runtime is byte-identical to the file in the official npm 4.2.0 package.
The source tag resolves to commit `23c42ebeddde8073e7748e0b709ba61360a04849`.
Keep the runtime's original header and the upstream attribution at the start
of `NOTICE.txt`; the notice intentionally retains the original Unicode text.

The standalone build includes `fancy-canvas` 2.1.0 (MIT); upstream also
identifies incorporated portions of `tslib` (BSD Zero Clause). Both notices
and permission texts are retained in `NOTICE.txt`. The fancy-canvas npm
archive omits its license file; its license text is taken from upstream
commit `a5e954d0d8da5835ac22a5114e65c1e8c227ed66`. The tslib text is from
the official 2.5.2 package referenced by the chart source's build dependencies.

The chart page keeps its existing TradingView attribution link. No CDN is
needed to load this chart engine; this is not a claim that every application
feature works without a network. Statistical charts continue to use Plotly.

## Version Policy

- Stay on 4.2.0 for this decision; no runtime upgrade is included.
- Do not mix in the 5.x `addSeries` or `createSeriesMarkers` APIs.
- Any future upgrade must review source hashes, API compatibility, licenses,
  offline loading and browser interaction before changing this pin.
- Run `python -m pytest tests/test_chart_asset_policy.py` for the offline
  version and attribution gates. These checks never contact upstream servers.

This directory is not yet included in the public export allowlist. A future
chart-enabled release must ship the runtime and its license/notice files
together; this task does not change that export boundary.
