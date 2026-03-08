from __future__ import annotations

from typing import Protocol

from aiogram import Bot


class Notifier(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...

    async def close(self) -> None: ...


class TelegramBotNotifier:
    def __init__(self, token: str) -> None:
        self._bot = Bot(token=token)

    async def send(self, chat_id: int, text: str) -> None:
        await self._bot.send_message(chat_id=chat_id, text=text)

    async def close(self) -> None:
        await self._bot.session.close()
