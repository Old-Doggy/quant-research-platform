from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path


OUTPUT_DIR = Path(__file__).resolve().parent
HEADERS = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "roe", "pb"]


def trading_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def build_rows(symbol: str, days: list[date], seed: int, base: float, drift: float, volatility: float) -> list[dict[str, object]]:
    rng = random.Random(seed)
    close = base
    rows: list[dict[str, object]] = []
    for index, day in enumerate(days):
        regime = 0.0008 if 35 <= index < 145 else (-0.0012 if 145 <= index < 190 else 0.0004)
        shock = math.sin(index / 9.0) * 0.0008 + rng.gauss(0.0, volatility)
        previous = close
        close = max(8.0, close * (1.0 + drift + regime + shock))
        opening = previous * (1.0 + rng.gauss(0.0, volatility / 2.0))
        high = max(opening, close) * (1.0 + abs(rng.gauss(0.0, volatility)))
        low = min(opening, close) * (1.0 - abs(rng.gauss(0.0, volatility)))
        rows.append(
            {
                "ts_code": symbol,
                "trade_date": day.strftime("%Y%m%d"),
                "open": round(opening, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "vol": int(90000 + index * 180 + rng.randint(0, 18000)),
                "roe": round(8.0 + (seed % 7) * 0.8, 2),
                "pb": round(1.4 + (seed % 5) * 0.35, 2),
            }
        )
    return rows


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    days = trading_days(date(2023, 1, 3), 300)
    single_rows = build_rows("SYNTH_SINGLE", days, seed=11, base=100.0, drift=0.0002, volatility=0.009)
    write_rows(OUTPUT_DIR / "quant_demo_single_symbol.csv", single_rows)

    symbols = (
        ("SYNTH_ALPHA", 21, 100.0, 0.0002, 0.009),
        ("SYNTH_BETA", 31, 82.0, 0.0001, 0.011),
        ("SYNTH_DEFENSIVE", 41, 118.0, 0.0003, 0.005),
        ("SYNTH_VOLATILE", 51, 64.0, -0.0001, 0.016),
    )
    multi_rows: list[dict[str, object]] = []
    for symbol, seed, base, drift, volatility in symbols:
        symbol_days = [day for index, day in enumerate(days) if not (symbol == "SYNTH_BETA" and index % 37 == 0) and not (symbol == "SYNTH_VOLATILE" and index % 53 == 0)]
        multi_rows.extend(build_rows(symbol, symbol_days, seed=seed, base=base, drift=drift, volatility=volatility))
    write_rows(OUTPUT_DIR / "quant_demo_multi_symbol.csv", multi_rows)


if __name__ == "__main__":
    main()
