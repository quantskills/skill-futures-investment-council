# Futures Investment Council

An AI futures research skill that combines quantitative indicators, futures structure, and investor frameworks.

## What it does

- Analyze a single futures symbol
- Compare multiple futures symbols
- Screen stronger trend candidates
- Explain quantitative signals
- Produce committee-style research reports

## What it does not do

- Auto trade
- Promise profits
- Do stock research
- Output deterministic buy or sell commands

## Use

### uv

```bash
uv run futures-investment-council --symbol CU_INDEX
uv run python scripts/compare_futures.py --symbols AU_INDEX AG_INDEX
uv run python scripts/screen_futures.py --limit 10
uv run python scripts/smoke_test.py
```

### pip / python

```bash
python -m pip install .
futures-investment-council --symbol CU_INDEX
```

Editable install for development:

```bash
python -m pip install -e .
```

Optional extras:

```bash
python -m pip install ".[advanced]"
```

## Notes

- Default live research uses bundled `settings.yaml` with PandaData.
- `settings/smoke.yaml` is for offline demo and test runs only.
- A local `.env` file may contain `PANDA_DATA_USERNAME` and `PANDA_DATA_PASSWORD`; environment variables take precedence.
- The report pipeline works in memory by default.
- Missing inventory, basis, curve structure, or supply-demand data are marked as `unknown`.
- Expert notes live in `references/experts/`.
- The project is licensed under GPL-3.0-only.
