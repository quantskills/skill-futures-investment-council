from __future__ import annotations

import argparse

from skill_futures_investment_council.research import compare_symbols, write_output


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare futures symbols.")
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbols such as AU_INDEX AG_INDEX.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", default=None)
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logs.")
    args = parser.parse_args()
    write_output(
        compare_symbols(
            args.symbols,
            config_path=args.config,
            output_format=args.format,
            verbose=not args.quiet,
        ),
        args.output,
    )


if __name__ == "__main__":
    main()
