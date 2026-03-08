from __future__ import annotations

from argparse import Namespace

import pytest

from tg_detox_locker import cli


@pytest.mark.asyncio
async def test_init_db_uses_database_only_settings(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class _FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def run_sync(self, fn):
            captured["run_sync"] = fn.__name__

    class _FakeEngine:
        def begin(self):
            return _FakeConnection()

        async def dispose(self) -> None:
            captured["disposed"] = "yes"

    monkeypatch.setattr(cli, "load_database_settings", lambda: Namespace(database_url="sqlite+aiosqlite:///./local.db"))
    def _fake_create_engine(url: str) -> _FakeEngine:
        captured["database_url"] = url
        return _FakeEngine()

    monkeypatch.setattr(cli, "create_engine", _fake_create_engine)

    await cli._init_db()  # noqa: SLF001 - direct async unit test

    assert captured["database_url"] == "sqlite+aiosqlite:///./local.db"
    assert captured["run_sync"] == "create_all"
    assert captured["disposed"] == "yes"
