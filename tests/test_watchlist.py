from __future__ import annotations

import json

from portfolio_app.watchlist import WatchlistStore


def test_watchlist_add_remove_and_recent_are_deduplicated(tmp_path):
    store = WatchlistStore(tmp_path / "state" / "watchlist.json")

    store.add("000001.SZ")
    store.add("000001.SZ")
    store.add("600000.SH")
    store.record_recent("000001.SZ")
    store.record_recent("600000.SH")
    store.record_recent("000001.SZ")

    assert store.symbols == ["000001.SZ", "600000.SH"]
    assert store.recent == ["000001.SZ", "600000.SH"]
    store.remove("000001.SZ")
    assert store.symbols == ["600000.SH"]
    assert store.recent == ["000001.SZ", "600000.SH"]


def test_watchlist_survives_restart_without_persisting_local_paths(tmp_path):
    state_path = tmp_path / "state" / "watchlist.json"
    first = WatchlistStore(state_path)
    first.add("000001.SZ")
    first.record_recent("000001.SZ")

    restarted = WatchlistStore(state_path)
    assert restarted.symbols == ["000001.SZ"]
    assert restarted.recent == ["000001.SZ"]
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(payload) == {"symbols", "recent"}
    assert str(tmp_path) not in json.dumps(payload)


def test_watchlist_recovers_from_corrupt_state_and_validates_symbols(tmp_path):
    state_path = tmp_path / "watchlist.json"
    state_path.write_text("{broken", encoding="utf-8")
    store = WatchlistStore(state_path)

    assert store.symbols == []
    assert store.recent == []
    store.add("000001.SZ")
    assert store.symbols == ["000001.SZ"]
