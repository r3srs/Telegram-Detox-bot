# Telegram Detox Locker

[![CI](https://github.com/r3srs/Telegram-Detox-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/r3srs/Telegram-Detox-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/r3srs/Telegram-Detox-bot/blob/main/LICENSE)

Telegram Detox Locker is a single-user Telegram self-lock service built on top of MTProto. It arms a protected user session, rotates the account's 2FA password to a random detox secret, drops other authorizations, watches for new login attempts, and restores the original password when the timer ends.

## Why this exists

Telegram has no native "lock me out of my own account until a timer expires" feature. This project is a focused implementation of that idea for a single owner:

- one protected Telegram account
- one spare admin Telegram account
- one worker that stays online and reacts to new authorizations

## What v1 does

- Starts manual detox runs from `5m` to `30d`
- Uses a spare Telegram account as the admin interface
- Rotates the protected account's 2FA password to a random detox secret
- Resets other active authorizations after arming
- Monitors new authorizations via MTProto updates and reconciliation
- Revokes unauthorized sessions and rotates the detox secret again
- Restores the baseline 2FA password at the end of the timer
- Retries baseline restore if Telegram rejects the first attempt

## Limits and risk model

This is not a mathematical guarantee that no device can ever log in. It is a hard Telegram-level self-lock with realistic constraints:

- it depends on Telegram client API behavior
- it does not control the operating system or physical devices
- it uses an unofficial MTProto client session, which Telegram may monitor more closely than the official apps

If you need a true device-level lock, that has to be combined with OS or device-side restrictions.

## Architecture

- `detox-worker`: Telethon runtime that owns the protected user session
- `detox-bot`: aiogram companion bot used by the spare admin account
- `Postgres` in production or `SQLite` for local experiments
- `Alembic`: schema migration
- `AES-GCM`: encryption for the MTProto string session and stored secrets

## Requirements

- Python `3.12` or `3.13`
- Telegram API ID and API hash from `https://my.telegram.org`
- Bot token from `@BotFather`
- Protected Telegram account with 2FA and recovery email already configured
- Spare Telegram account that will be the admin interface

## Quick Start

1. Copy the example environment.

```powershell
Copy-Item .env.example .env
```

2. Generate a master key.

```powershell
python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

3. Put the generated key and your Telegram credentials into `.env`.

4. Install the project.

```powershell
python -m pip install -e .[dev]
```

5. Initialize the database.

```powershell
python -m tg_detox_locker.cli init-db
```

6. Run onboarding from the machine that will host the worker.

```powershell
python -m tg_detox_locker.cli onboarding --phone +10000000000 --admin-chat-id 123456789
```

7. Start the worker and the bot in separate terminals.

```powershell
python -m tg_detox_locker.worker
python -m tg_detox_locker.bot
```

## Configuration

Copy `.env.example` to `.env` and set:

- `DATABASE_URL`
- `BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `DETOX_MASTER_KEY`
- `DEFAULT_DETOX_DURATION`

For local testing, `SQLite` is fine:

```env
DATABASE_URL=sqlite+aiosqlite:///./local.db
```

For production, prefer `Postgres`.

## Per-Process Env Requirements

- `init-db`: only `DATABASE_URL`
- `detox-bot`: `DATABASE_URL`, `BOT_TOKEN`
- `onboarding` and `recover`: `DATABASE_URL`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `DETOX_MASTER_KEY`
- `detox-worker`: full configuration from `.env`

## Operational Notes

- The worker must stay online during the entire detox run.
- The current locker session must be at least 24 hours old before the stricter preflight allows arming.
- Re-running onboarding refreshes the stored session and can restart that waiting window.
- There is no in-product early unlock.

## Commands

- `/start`
- `/help`
- `/detox 4h`
- `/status`
- `/history`
- `/health`

Only the configured `admin_chat_id` is allowed to use them.

## Disaster Recovery

If the system must restore the baseline password manually, use the server-side recovery CLI over SSH:

```powershell
python -m tg_detox_locker.cli recover
```

## Development

Run the test suite:

```powershell
pytest
```

GitHub Actions runs the same tests on Python `3.12` and `3.13`.

## Database Model

The service stores:

- `settings`: singleton config and worker health
- `detox_runs`: detox lifecycle records
- `authorizations_seen`: detected and revoked authorizations during a run
- `audit_events`: structured audit log

## Deployment

Example `systemd` units are provided in `systemd/` for `detox-worker` and `detox-bot`.
