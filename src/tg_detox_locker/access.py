from __future__ import annotations

from tg_detox_locker.errors import ForbiddenError


def ensure_admin_chat(configured_chat_id: int, chat_id: int) -> None:
    if configured_chat_id != chat_id:
        raise ForbiddenError("This bot only accepts commands from the configured admin chat.")
