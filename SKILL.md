---
name: skill-futures-investment-council
description: Futures research Skill for analyzing, comparing, and screening futures markets with technical indicators, futures structure, and committee-style reports. Use when Codex needs to analyze a futures symbol, compare futures symbols, screen futures candidates, explain signal changes, or generate a structured futures research report without stock analysis, auto-trading, or deterministic buy/sell promises.
---

# Skill Futures Investment Council

只处理期货研究。

## Workflow

1. Run the matching script in `scripts/` from the skill root.
2. For live futures research, use the bundled default Pandadata config by omitting `--config`.
3. Compute technical, futures-structure, and risk features.
4. Read `references/feature-contract.md` and `references/report-format.md` when shaping output.
5. Load only the relevant expert notes from `references/experts/`.
6. Emit a structured research report.

## Entrypoints

- `scripts/analyze_futures.py`
- `scripts/compare_futures.py`
- `scripts/screen_futures.py`
- `scripts/smoke_test.py`

## Rules

- Prefer `uv run futures-investment-council --symbol <symbol>` for live analysis.
- Markdown reports default to `Downloads` when `--output` is omitted.
- A local `.env` file is optional. If present, read `PANDA_DATA_USERNAME` and `PANDA_DATA_PASSWORD` from it; environment variables still win.
- Do not search for or use local CSV files as a fallback when Pandadata is unavailable.
- Use CSV only when the user explicitly asks for offline/smoke testing or supplies a CSV config.
- If Pandadata login, credentials, or network access fail, report that live data is unavailable instead of switching data sources silently.
- Degrade gracefully when inventory, basis, curve, or supply-demand data are missing.
- Do not invent unavailable data.
- Do not output direct trade commands.
- Do not perform stock research or auto-trading.
- Do not recalculate indicators outside the scripts unless a script fails and the failure is reported.
- Use Pandadata as the default live data source from the bundled `settings.yaml`; use the bundled `settings/smoke.yaml` only for offline tests.
