from __future__ import annotations

import os
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_detox_locker.config import AppSettings
from tg_detox_locker.crypto import SecretBox
from tg_detox_locker.enums import LockerState, PendingCommand
from tg_detox_locker.models import AuthorizationSeen, Base, DetoxRun, Settings
from tg_detox_locker.services import LockerRuntime
from tg_detox_locker.telethon_gateway import AuthorizationSnapshot, NewAuthorizationEvent
from tg_detox_locker.time_utils import utc_now


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

    async def close(self) -> None:
        return None


class FakeGateway:
    def __init__(self, *, fail_reset: bool = False) -> None:
        self.fail_reset = fail_reset
        self.connected = False
        self.revoked: list[int] = []
        self.change_calls: list[tuple[str, str]] = []
        self.authorizations = [
            AuthorizationSnapshot(
                authorization_hash=1,
                current=True,
                device="device",
                location="location",
                created_at=utc_now() - timedelta(days=2),
            )
        ]

    async def connect(self, session_string: str, on_new_authorization=None) -> None:
        self.connected = True
        self.on_new_authorization = on_new_authorization

    async def disconnect(self) -> None:
        self.connected = False

    async def list_authorizations(self) -> list[AuthorizationSnapshot]:
        return self.authorizations

    async def change_2fa(self, current_password: str, new_password: str) -> None:
        self.change_calls.append((current_password, new_password))

    async def reset_other_authorizations(self) -> None:
        if self.fail_reset:
            raise RuntimeError("reset failed")

    async def revoke_authorization(self, authorization_hash: int) -> None:
        self.revoked.append(authorization_hash)


def make_settings() -> AppSettings:
    return AppSettings(
        database_url="sqlite+aiosqlite:///unused.db",
        bot_token="token",
        telegram_api_id=1,
        telegram_api_hash="hash",
        master_key=os.urandom(32),
        check_interval_seconds=1,
        reconcile_interval_seconds=30,
        restore_retry_seconds=60,
        default_detox_duration="4h",
        log_level="INFO",
    )


async def prepare_db(tmp_path, app_settings: AppSettings, secret_box: SecretBox) -> async_sessionmaker:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            Settings(
                id=1,
                encrypted_string_session=secret_box.encrypt("session"),
                encrypted_baseline_password=secret_box.encrypt("baseline"),
                admin_chat_id=777,
                current_state=LockerState.IDLE,
                default_duration_seconds=14400,
                pending_command_kind=PendingCommand.START_DETOX.value,
                pending_command_payload={"duration_seconds": 3600, "requested_by_chat_id": 777},
                pending_command_requested_at=utc_now(),
                onboarded_at=utc_now() - timedelta(days=2),
                baseline_password_verified_at=utc_now() - timedelta(days=2),
                updated_at=utc_now(),
            )
        )
        await session.commit()
    return session_factory


@pytest.mark.asyncio
async def test_runtime_rolls_back_if_reset_authorizations_fails(tmp_path) -> None:
    app_settings = make_settings()
    secret_box = SecretBox(app_settings.master_key)
    session_factory = await prepare_db(tmp_path, app_settings, secret_box)
    notifier = FakeNotifier()
    gateway = FakeGateway(fail_reset=True)
    runtime = LockerRuntime(
        session_factory=session_factory,
        app_settings=app_settings,
        secret_box=secret_box,
        gateway_factory=lambda: gateway,
        notifier=notifier,
        password_generator=lambda length=64: "detox-password",
    )

    await runtime.tick()

    async with session_factory() as session:
        settings = await session.get(Settings, 1)
        run = await session.scalar(select(DetoxRun).order_by(DetoxRun.created_at.desc()))
        assert settings is not None
        assert run is not None
        assert settings.current_state == LockerState.IDLE
        assert run.state == LockerState.START_FAILED
        assert run.end_reason == "start_failed"
        assert run.encrypted_current_detox_password is None
    assert gateway.change_calls == [("baseline", "detox-password"), ("detox-password", "baseline")]
    assert notifier.messages
    assert "start failed" in notifier.messages[0][1].lower()

    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_revokes_and_rotates_on_new_authorization(tmp_path) -> None:
    app_settings = make_settings()
    secret_box = SecretBox(app_settings.master_key)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rotate.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            Settings(
                id=1,
                encrypted_string_session=secret_box.encrypt("session"),
                encrypted_baseline_password=secret_box.encrypt("baseline"),
                admin_chat_id=777,
                current_state=LockerState.RUNNING,
                default_duration_seconds=14400,
                onboarded_at=utc_now() - timedelta(days=2),
                baseline_password_verified_at=utc_now() - timedelta(days=2),
                updated_at=utc_now(),
            )
        )
        session.add(
            DetoxRun(
                state=LockerState.RUNNING,
                requested_by_chat_id=777,
                requested_duration_seconds=3600,
                planned_end_at=utc_now() + timedelta(hours=1),
                encrypted_current_detox_password=secret_box.encrypt("detox-current"),
                start_reason="user_request",
            )
        )
        await session.commit()

    notifier = FakeNotifier()
    gateway = FakeGateway()
    runtime = LockerRuntime(
        session_factory=session_factory,
        app_settings=app_settings,
        secret_box=secret_box,
        gateway_factory=lambda: gateway,
        notifier=notifier,
        password_generator=lambda length=64: "detox-next",
    )
    await runtime.tick()
    await runtime._queue_new_authorization(  # noqa: SLF001 - unit test
        NewAuthorizationEvent(
            authorization_hash=99,
            device="iPhone",
            location="RU",
            created_at=utc_now(),
            unconfirmed=False,
        )
    )
    await runtime.tick()

    async with session_factory() as session:
        run = await session.scalar(select(DetoxRun).order_by(DetoxRun.created_at.desc()))
        auth_seen = await session.scalar(select(AuthorizationSeen))
        assert run is not None
        assert auth_seen is not None
        assert run.attempt_count == 1
        assert auth_seen.authorization_hash == 99
        assert auth_seen.revoked_at is not None
    assert gateway.revoked == [99]
    assert gateway.change_calls == [("detox-current", "detox-next")]

    await runtime.close()
    await engine.dispose()
