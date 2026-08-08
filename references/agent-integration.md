# Agent Integration

## Workflow

1. Read `SKILL.md`.
2. Load `settings.yaml`.
3. Call a script in `scripts/`.
4. Read only the relevant expert files from `references/experts/`.
5. Assemble the committee report.

## Notes

- Keep paths relative to the repository root.
- Prefer structured JSON or markdown output.
- Do not duplicate business logic inside scripts.
