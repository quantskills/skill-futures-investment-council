from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timedelta

from skill_futures_investment_council.api.fundamentals import AkshareFundamentalSource
from skill_futures_investment_council.research import SYMBOL_ALIASES


def _product_from_symbol(symbol: str) -> str:
    resolved = SYMBOL_ALIASES.get(symbol.strip(), symbol.strip())
    match = re.match(r"^[A-Za-z]+", resolved)
    return match.group(0).upper() if match else resolved.upper()


def _parse_date(value: str | None) -> datetime:
    if value:
        return datetime.strptime(value, "%Y-%m-%d")
    return datetime.now()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark one akshare spot-price request.")
    parser.add_argument("--symbol", default="沪铜", help="Symbol alias or product code, such as 沪铜 or CU.")
    parser.add_argument("--start-date", default=None, help="Start date in YYYY-MM-DD.")
    parser.add_argument("--end-date", default=None, help="End date in YYYY-MM-DD.")
    args = parser.parse_args()

    product = _product_from_symbol(args.symbol)
    end_date = _parse_date(args.end_date)
    start_date = _parse_date(args.start_date) if args.start_date else end_date - timedelta(days=420)

    source = AkshareFundamentalSource()
    print(f"product={product}")
    print(f"range={start_date:%Y-%m-%d}..{end_date:%Y-%m-%d}")

    start = time.perf_counter()
    frame = source.load_spot_history(product, start_date, end_date)
    elapsed = time.perf_counter() - start

    print(f"elapsed={elapsed:.2f}s")
    print(f"rows={len(frame)}")
    if not frame.empty:
        print(f"date_range={frame['datetime'].min().date()}..{frame['datetime'].max().date()}")
        print(frame.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
