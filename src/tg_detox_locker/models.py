from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SQLEnum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from tg_detox_locker.enums import LockerState
from tg_detox_locker.time_utils import utc_now


class Base(DeclarativeBase):
    pass


locker_state_enum = SQLEnum(LockerState, name="lockerstate")


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    encrypted_string_session: Mapped[str] = mapped_column(Text)
    encrypted_baseline_password: Mapped[str] = mapped_column(Text)
    admin_chat_id: Mapped[int] = mapped_column(BigInteger)
    current_state: Mapped[LockerState] = mapped_column(locker_state_enum, default=LockerState.IDLE)
    default_duration_seconds: Mapped[int] = mapped_column(Integer, default=14400)
    pending_command_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pending_command_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pending_command_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    baseline_password_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    telegram_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    last_reconcile_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class DetoxRun(Base):
    __tablename__ = "detox_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    state: Mapped[LockerState] = mapped_column(locker_state_enum)
    requested_by_chat_id: Mapped[int] = mapped_column(BigInteger)
    requested_duration_seconds: Mapped[int] = mapped_column(Integer)
    planned_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    encrypted_current_detox_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_reason: Mapped[str] = mapped_column(String(64))
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_restore_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    authorizations: Mapped[list["AuthorizationSeen"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="run")


class AuthorizationSeen(Base):
    __tablename__ = "authorizations_seen"
    __table_args__ = (UniqueConstraint("run_id", "authorization_hash", name="uq_run_authorization_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("detox_runs.id", ondelete="CASCADE"))
    authorization_hash: Mapped[int] = mapped_column(BigInteger)
    device: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[DetoxRun] = relationship(back_populates="authorizations")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("detox_runs.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[DetoxRun | None] = relationship(back_populates="audit_events")
