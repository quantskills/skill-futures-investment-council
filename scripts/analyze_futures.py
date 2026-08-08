from __future__ import annotations

import argparse

from skill_futures_investment_council.research import analyze_symbol, write_output


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze one futures symbol.")
    parser.add_argument("--symbol", required=True, help="Symbol such as CU_INDEX, AU_INDEX, or DEMO_INDEX.")
    parser.add_argument("--config", default=None, help="Research settings YAML. Defaults to bundled settings.yaml.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output", default=None, help="Optional report path. Defaults to stdout.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logs.")
    args = parser.parse_args()
    content = analyze_symbol(
        args.symbol,
        config_path=args.config,
        output_format=args.format,
        start_date=args.start_date,
        end_date=args.end_date,
        verbose=not args.quiet,
    )
    write_output(content, args.output)


if __name__ == "__main__":
    main()
