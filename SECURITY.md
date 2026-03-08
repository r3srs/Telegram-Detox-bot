# Security Policy

## Supported use

This repository is a personal-use Telegram detox service. It is not intended for mass automation, growth tooling, or spam workflows.

## Sensitive data

Treat the following as secrets:

- `BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `DETOX_MASTER_KEY`
- Telethon string sessions
- Stored baseline or detox passwords

Never commit `.env`, local database files, or exported session data.

## Operational guidance

- Prefer running the worker on a dedicated VPS.
- Restrict SSH access to the host.
- Rotate the bot token if it is ever exposed.
- Keep the master key backed up securely. Losing it can make encrypted secrets unrecoverable.

## Reporting

If you find a security issue, report it privately to the maintainer before opening a public issue.
