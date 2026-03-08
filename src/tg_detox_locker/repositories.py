from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_detox_locker.enums import LockerState
from tg_detox_locker.models import AuditEvent, AuthorizationSeen, DetoxRun, Settings
from tg_detox_locker.time_utils import utc_now

ACTIVE_STATES = {
    LockerState.ARMING,
    LockerState.RUNNING,
    LockerState.ENDING,
    LockerState.DEGRADED_LOCKED,
    LockerState.RESTORE_FAILED_LOCKED,
}


async def get_settings(session: AsyncSession, *, for_update: bool = False) -> Settings | None:
    stmt: Select[tuple[Settings]] = select(Settings).where(Settings.id == 1)
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def get_active_run(session: AsyncSession, *, for_update: bool = False) -> DetoxRun | None:
    stmt: Select[tuple[DetoxRun]] = (
        select(DetoxRun)
        .where(DetoxRun.state.in_(ACTIVE_STATES))
        .order_by(desc(DetoxRun.created_at))
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def list_recent_runs(session: AsyncSession, limit: int = 5) -> Sequence[DetoxRun]:
    stmt = select(DetoxRun).order_by(desc(DetoxRun.created_at)).limit(limit)
    result = await session.scalars(stmt)
    return result.all()


async def get_authorization_seen(session: AsyncSession, run_id: Any, authorization_hash: int) -> AuthorizationSeen | None:
    stmt = select(AuthorizationSeen).where(
        AuthorizationSeen.run_id == run_id,
        AuthorizationSeen.authorization_hash == authorization_hash,
    )
    return await session.scalar(stmt)


def add_audit_event(
    session: AsyncSession,
    *,
    event_type: str,
    payload: dict[str, Any],
    run_id: Any | None = None,
) -> AuditEvent:
    event = AuditEvent(run_id=run_id, event_type=event_type, payload=payload, created_at=utc_now())
    session.add(event)
    return event
