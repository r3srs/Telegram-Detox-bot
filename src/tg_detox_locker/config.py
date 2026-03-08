from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _load_dotenv() -> None:
    candidate_paths = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for path in candidate_paths:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
        return


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return int(raw)


@dataclass(frozen=True, slots=True)
class AppSettings:
    database_url: str
    bot_token: str
    telegram_api_id: int
    telegram_api_hash: str
    master_key: bytes
    check_interval_seconds: int
    reconcile_interval_seconds: int
    restore_retry_seconds: int
    default_detox_duration: str
    log_level: str


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    database_url: str


@lru_cache(maxsize=1)
def load_database_settings() -> DatabaseSettings:
    _load_dotenv()
    return DatabaseSettings(database_url=_env("DATABASE_URL"))


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    _load_dotenv()
    raw_key = _env("DETOX_MASTER_KEY")
    padding = "=" * (-len(raw_key) % 4)
    master_key = base64.urlsafe_b64decode(raw_key + padding)
    if len(master_key) != 32:
        raise RuntimeError("DETOX_MASTER_KEY must decode to exactly 32 bytes")
    return AppSettings(
        database_url=_env("DATABASE_URL"),
        bot_token=_env("BOT_TOKEN"),
        telegram_api_id=int(_env("TELEGRAM_API_ID")),
        telegram_api_hash=_env("TELEGRAM_API_HASH"),
        master_key=master_key,
        check_interval_seconds=_env_int("CHECK_INTERVAL_SECONDS", 2),
        reconcile_interval_seconds=_env_int("RECONCILE_INTERVAL_SECONDS", 30),
        restore_retry_seconds=_env_int("RESTORE_RETRY_SECONDS", 60),
        default_detox_duration=os.getenv("DEFAULT_DETOX_DURATION", "4h"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
