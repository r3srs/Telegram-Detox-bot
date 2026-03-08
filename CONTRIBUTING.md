# Contributing

## Local setup

```powershell
python -m pip install -e .[dev]
Copy-Item .env.example .env
python -m tg_detox_locker.cli init-db
```

## Development flow

- Keep changes focused and small.
- Add or update tests for behavior changes.
- Avoid committing `.env`, session strings, or local databases.
- Prefer SQLite for local tests and Postgres for deployment validation.

## Validation

```powershell
pytest
python -m compileall src tests
```

## Pull requests

- Describe the behavioral change, not just the files touched.
- Call out Telegram API assumptions or operational risks explicitly.
- Include manual verification steps for onboarding, worker start, and bot commands when relevant.
