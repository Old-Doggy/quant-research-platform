"""Small path-independent persistence for watchlist and recent symbols."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
import tempfile
import uuid

from .process_lock import process_lock


_SYMBOL = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


def _clean(values: object, *, limit: int = 50) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = str(value).strip().upper()
        if text and _SYMBOL.fullmatch(text) and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


class WatchlistStore:
    """Persist only symbol IDs; local data paths never enter the state file."""

    def __init__(self, path: str | Path, *, recent_limit: int = 20) -> None:
        self.path = Path(path)
        self.recent_limit = max(1, int(recent_limit))
        self._symbols: list[str] = []
        self._recent: list[str] = []
        with process_lock(self.path.with_suffix('.lock'), wait=True):
            self._load()

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    @property
    def recent(self) -> list[str]:
        return list(self._recent)

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or any(
                key in payload and not isinstance(payload[key], list) for key in ('symbols', 'recent')
            ):
                raise ValueError('invalid watchlist structure')
        except FileNotFoundError:
            payload = {}
        except (ValueError, UnicodeError):
            # Preserve damaged input before a later write starts a fresh list.
            self.path.rename(self.path.with_name(f'{self.path.stem}.corrupt-{uuid.uuid4().hex}.json'))
            payload = {}
        self._symbols = _clean(payload.get("symbols"))
        self._recent = _clean(payload.get("recent"), limit=self.recent_limit)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"symbols": self._symbols, "recent": self._recent}, ensure_ascii=False, indent=2)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{self.path.stem}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def add(self, symbol: str) -> None:
        values = _clean([symbol])
        if not values:
            raise ValueError("symbol must be a simple identifier")
        value = values[0]
        with process_lock(self.path.with_suffix('.lock'), wait=True):
            self._load()
            if value not in self._symbols:
                if len(self._symbols) >= 50:
                    raise ValueError('watchlist supports at most 50 symbols')
                self._symbols.append(value)
                self._save()

    def remove(self, symbol: str) -> None:
        value = str(symbol or "").strip().upper()
        with process_lock(self.path.with_suffix('.lock'), wait=True):
            self._load()
            updated = [item for item in self._symbols if item != value]
            if updated != self._symbols:
                self._symbols = updated
                self._save()

    def record_recent(self, symbol: str) -> None:
        values = _clean([symbol])
        if not values:
            raise ValueError("symbol must be a simple identifier")
        value = values[0]
        with process_lock(self.path.with_suffix('.lock'), wait=True):
            self._load()
            self._recent = [item for item in self._recent if item != value]
            self._recent.insert(0, value)
            self._recent = self._recent[: self.recent_limit]
            self._save()
