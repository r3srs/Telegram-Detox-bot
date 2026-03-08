from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_detox_locker.enums import LockerState, PendingCommand
from tg_detox_locker.errors import ForbiddenError, StateConflictError
from tg_detox_locker.models import AuditEvent, Base, Settings
from tg_detox_locker.services import ControlService
from tg_detox_locker.time_utils import utc_now


async def make_service_db(tmp_path) -> async_sessionmaker:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'control.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            Settings(
                id=1,
                encrypted_string_session="stub-session",
                encrypted_baseline_password="stub-password",
                admin_chat_id=777,
                current_state=LockerState.IDLE,
                default_duration_seconds=7200,
                onboarded_at=utc_now(),
                baseline_password_verified_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        await session.commit()
    return session_factory


@pytest.mark.asyncio
async def test_queue_start_uses_default_duration_when_not_provided(tmp_path) -> None:
    session_factory = await make_service_db(tmp_path)
    service = ControlService(session_factory)

    duration = await service.queue_start(777, None)

    assert duration == timedelta(hours=2)
    async with session_factory() as session:
        settings = await session.get(Settings, 1)
        audit_event = await session.scalar(select(AuditEvent).order_by(AuditEvent.created_at.desc()))
        assert settings is not None
        assert settings.pending_command_kind == PendingCommand.START_DETOX.value
        assert settings.pending_command_payload == {"duration_seconds": 7200, "requested_by_chat_id": 777}
        assert audit_event is not None
        assert audit_event.event_type == "start_command_queued"


@pytest.mark.asyncio
async def test_queue_start_rejects_non_admin_chat(tmp_path) -> None:
    session_factory = await make_service_db(tmp_path)
    service = ControlService(session_factory)

    with pytest.raises(ForbiddenError):
        await service.queue_start(999, "4h")


@pytest.mark.asyncio
async def test_queue_start_rejects_when_locker_is_busy(tmp_path) -> None:
    session_factory = await make_service_db(tmp_path)
    service = ControlService(session_factory)

    async with session_factory() as session:
        settings = await session.get(Settings, 1)
        assert settings is not None
        settings.current_state = LockerState.RUNNING
        await session.commit()

    with pytest.raises(StateConflictError):
        await service.queue_start(777, "4h")
