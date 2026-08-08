from __future__ import annotations

import argparse
import sys

from .research import analyze_symbol, default_markdown_output_path, write_output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a futures research report.")
    parser.add_argument("--symbol", required=True, help="Symbol such as AU_INDEX, CU_INDEX, or DEMO_INDEX.")
    parser.add_argument("--config", default=None, help="Research YAML config. Defaults to bundled settings.yaml.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output", default=None, help="Output file path. Markdown defaults to Downloads when omitted.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logs.")
    args = parser.parse_args()
    report = analyze_symbol(
        args.symbol,
        config_path=args.config,
        output_format=args.format,
        start_date=args.start_date,
        end_date=args.end_date,
        verbose=not args.quiet,
    )
    output_path = args.output
    if output_path is None and args.format == "markdown":
        output_path = default_markdown_output_path(args.symbol, end_date=args.end_date)
    written_path = write_output(report, output_path)
    if written_path is not None and args.output is None and args.format == "markdown":
        print(f"长文报告已写入：{written_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
