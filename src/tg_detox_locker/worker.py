from __future__ import annotations

import asyncio

from tg_detox_locker.config import load_settings
from tg_detox_locker.crypto import SecretBox
from tg_detox_locker.db import create_engine, create_session_factory
from tg_detox_locker.logging_utils import configure_logging
from tg_detox_locker.notifications import TelegramBotNotifier
from tg_detox_locker.services import LockerRuntime
from tg_detox_locker.telethon_gateway import TelethonGateway


async def run_worker() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    notifier = TelegramBotNotifier(settings.bot_token)
    runtime = LockerRuntime(
        session_factory=session_factory,
        app_settings=settings,
        secret_box=SecretBox(settings.master_key),
        gateway_factory=lambda: TelethonGateway(settings.telegram_api_id, settings.telegram_api_hash),
        notifier=notifier,
    )
    try:
        while True:
            await runtime.tick()
            await asyncio.sleep(settings.check_interval_seconds)
    finally:
        await runtime.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
