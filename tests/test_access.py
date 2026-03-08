from __future__ import annotations

import pytest

from tg_detox_locker.access import ensure_admin_chat
from tg_detox_locker.errors import ForbiddenError


def test_ensure_admin_chat_allows_matching_chat() -> None:
    ensure_admin_chat(123, 123)


def test_ensure_admin_chat_rejects_other_chat() -> None:
    with pytest.raises(ForbiddenError):
        ensure_admin_chat(123, 456)
