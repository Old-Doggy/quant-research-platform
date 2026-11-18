from __future__ import annotations

import json
import pytest

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


@pytest.mark.parametrize('body', [b'{broken', b'\xff', b'[]', b'{"symbols": "bad"}'])
def test_corrupt_watchlist_is_preserved_before_recovery(tmp_path, body):
    path = tmp_path / 'watchlist.json'
    path.write_bytes(body)
    store = WatchlistStore(path)
    store.add('600000.SH')
    assert store.symbols == ['600000.SH']
    backups = list(tmp_path.glob('watchlist.corrupt-*.json'))
    assert len(backups) == 1 and backups[0].read_bytes() == body


def test_unreadable_watchlist_is_not_treated_as_empty(tmp_path, monkeypatch):
    from pathlib import Path
    path = tmp_path / 'watchlist.json'
    path.write_text('{"symbols": ["AAA"], "recent": []}', encoding='utf8')
    original = Path.read_text
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError('unreadable')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', denied)
    with pytest.raises(PermissionError):
        WatchlistStore(path)
    assert b'AAA' in path.read_bytes()


def test_separate_watchlist_instances_preserve_each_others_changes(tmp_path):
    path = tmp_path / 'watchlist.json'
    first, second = WatchlistStore(path), WatchlistStore(path)
    first.add('AAA')
    second.add('BBB')
    first.record_recent('AAA')
    assert WatchlistStore(path).symbols == ['AAA', 'BBB']
