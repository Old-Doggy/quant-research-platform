"""Download one symbol's unadjusted daily bars without persisting credentials."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen
import pandas as pd
import numpy as np


def fetch_daily(symbol, start, end, token):
    if not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", symbol):
        raise ValueError("symbol must look like 600000.SH")
    first, last = (datetime.strptime(value, "%Y%m%d") for value in (start, end))
    if first > last:
        raise ValueError("start must not be after end")
    if not token:
        raise ValueError("Set TUSHARE_TOKEN in your terminal first")
    body = json.dumps(dict(api_name="daily", token=token,
        params=dict(ts_code=symbol, start_date=start, end_date=end),
        fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount")).encode()
    request = Request("https://api.waditu.com", data=body,
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=45) as response:
        result = json.load(response)
    if result.get("code") != 0:
        raise ValueError("Tushare rejected the request; check interface permissions and quota")
    data = result["data"]
    frame = pd.DataFrame(data["items"], columns=data["fields"])
    if frame.empty:
        raise ValueError("No daily bars returned for this symbol and date range")
    if len(frame) >= 6000:
        raise ValueError("Possible interface row limit; download a smaller date range")
    dates = pd.to_datetime(frame.trade_date, format="%Y%m%d", errors="raise")
    prices = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="raise")
    if (not frame.ts_code.eq(symbol).all() or dates.duplicated().any()
            or not dates.between(first, last).all() or prices.isna().any().any()
            or not np.isfinite(prices.to_numpy()).all() or prices.le(0).any().any()
            or prices.high.lt(prices[["open", "close"]].max(axis=1)).any()
            or prices.low.gt(prices[["open", "close"]].min(axis=1)).any()):
        raise ValueError("Source bars failed symbol, date or price validation")
    return frame.sort_values("trade_date").reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new filename")
    try:
        frame = fetch_daily(args.symbol.upper(), args.start, args.end, os.environ.get("TUSHARE_TOKEN", ""))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="") as handle:
            frame.to_csv(handle, index=False)
        metadata = dict(source="Tushare Pro daily", symbol=args.symbol.upper(),
                        price_basis="raw", rows=len(frame), start=str(frame.trade_date.iloc[0]),
                        end=str(frame.trade_date.iloc[-1]), volume_unit="source-defined")
        args.output.with_suffix(args.output.suffix + ".metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Saved {len(frame)} unadjusted daily bars to {args.output}")
    except Exception as exc:
        # Provider errors can contain request details; never echo token or payload.
        parser.exit(1, f"Download failed ({type(exc).__name__}). Check symbol, dates, permissions and connection.\n")


if __name__ == "__main__":
    main()
