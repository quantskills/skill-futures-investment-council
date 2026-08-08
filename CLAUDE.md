# Claude Code Instructions

This repository is a futures-only research skill.

## Use

- Prefer `uv run futures-investment-council --symbol <symbol>` for live analysis.
- If `uv` is unavailable, use `python -m pip install .` and then run `futures-investment-council --symbol <symbol>`.
- Keep the default Pandadata config in `settings.yaml`.
- Use `settings/smoke.yaml` only for offline smoke tests.
- Treat `.env` as optional. Read `PANDA_DATA_USERNAME` and `PANDA_DATA_PASSWORD` from it if present.
- Let markdown reports default to `Downloads` when `--output` is omitted.

## Workflow

1. Read `SKILL.md` first.
2. Read `references/agent-integration.md`, `references/research-boundaries.md`, and `references/report-format.md` when shaping behavior or output.
3. Load only the relevant expert notes from `references/experts/`.
4. Call the bundled scripts in `scripts/` instead of reimplementing business logic.

## Boundaries

- Futures only.
- No stock research.
- No auto trading.
- No deterministic buy/sell promises.
- Do not invent missing inventory, basis, curve, supply, or demand data.
- Do not use `references/legacy/` or `scripts/cron/`.

## Output

- Prefer structured markdown for reports.
- Use JSON only when explicitly requested.
