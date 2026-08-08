from __future__ import annotations

import argparse

from skill_futures_investment_council.research import screen_symbols, write_output


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen futures by trend evidence.")
    parser.add_argument("--symbols", nargs="*", default=None, help="Optional explicit symbol list.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", default=None)
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logs.")
    args = parser.parse_args()
    write_output(
        screen_symbols(
            args.symbols,
            config_path=args.config,
            limit=args.limit,
            output_format=args.format,
            verbose=not args.quiet,
        ),
        args.output,
    )


if __name__ == "__main__":
    main()
