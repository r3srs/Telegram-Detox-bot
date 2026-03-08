from __future__ import annotations

import base64
import os

from tg_detox_locker import config


def _clear_caches() -> None:
    config.load_database_settings.cache_clear()
    config.load_bot_settings.cache_clear()
    config.load_cli_settings.cache_clear()
    config.load_settings.cache_clear()


def test_load_cli_settings_does_not_require_bot_token(monkeypatch) -> None:
    _clear_caches()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./local.db")
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("DETOX_MASTER_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    settings = config.load_cli_settings()

    assert settings.database_url == "sqlite+aiosqlite:///./local.db"
    assert settings.telegram_api_id == 1


def test_load_bot_settings_does_not_require_telegram_api_or_master_key(monkeypatch) -> None:
    _clear_caches()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./local.db")
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.delenv("DETOX_MASTER_KEY", raising=False)

    settings = config.load_bot_settings()

    assert settings.database_url == "sqlite+aiosqlite:///./local.db"
    assert settings.bot_token == "token"
