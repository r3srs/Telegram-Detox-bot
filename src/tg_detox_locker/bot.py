from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from tg_detox_locker.config import load_bot_settings
from tg_detox_locker.db import create_engine, create_session_factory
from tg_detox_locker.duration import format_duration
from tg_detox_locker.errors import ConfigurationError, DetoxError, ForbiddenError
from tg_detox_locker.logging_utils import configure_logging
from tg_detox_locker.presenters import format_health, format_history, format_status
from tg_detox_locker.services import ControlService

LOGGER = logging.getLogger(__name__)


def build_router(service: ControlService) -> Router:
    router = Router()

    async def _guarded_reply(message: Message, action) -> None:
        try:
            await action()
        except ForbiddenError:
            await message.answer("Forbidden.")
        except ConfigurationError as exc:
            await message.answer(str(exc))
        except DetoxError as exc:
            await message.answer(str(exc))
        except Exception:
            LOGGER.exception("Bot command failed")
            await message.answer("Internal error.")

    @router.message(Command("start", "help"))
    async def start_handler(message: Message) -> None:
        async def action() -> None:
            await message.answer(
                "\n".join(
                    [
                        "Telegram Detox Locker",
                        "Commands: /detox <duration>, /status, /history, /health",
                        "Example: /detox 4h",
                    ]
                )
            )

        await _guarded_reply(message, action)

    @router.message(Command("detox"))
    async def detox_handler(message: Message) -> None:
        async def action() -> None:
            parts = (message.text or "").split(maxsplit=1)
            duration = parts[1] if len(parts) > 1 else None
            queued_duration = await service.queue_start(message.chat.id, duration)
            await message.answer(f"Detox queued for {format_duration(queued_duration)}. Worker will arm it shortly.")

        await _guarded_reply(message, action)

    @router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        async def action() -> None:
            settings, run = await service.get_settings_and_run(message.chat.id)
            await message.answer(format_status(settings, run))

        await _guarded_reply(message, action)

    @router.message(Command("history"))
    async def history_handler(message: Message) -> None:
        async def action() -> None:
            runs = await service.get_history(message.chat.id)
            await message.answer(format_history(runs))

        await _guarded_reply(message, action)

    @router.message(Command("health"))
    async def health_handler(message: Message) -> None:
        async def action() -> None:
            settings, _ = await service.get_settings_and_run(message.chat.id)
            await message.answer(format_health(settings))

        await _guarded_reply(message, action)

    return router


async def run_bot() -> None:
    settings = load_bot_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    service = ControlService(session_factory)
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(service))
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
