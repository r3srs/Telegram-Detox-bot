from __future__ import annotations

import asyncio
import logging
import secrets
import string
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tg_detox_locker.access import ensure_admin_chat
from tg_detox_locker.config import AppSettings
from tg_detox_locker.crypto import SecretBox
from tg_detox_locker.duration import parse_duration
from tg_detox_locker.enums import LockerState, PendingCommand
from tg_detox_locker.errors import ConfigurationError, PreflightError, StateConflictError
from tg_detox_locker.models import AuthorizationSeen, DetoxRun, Settings
from tg_detox_locker.notifications import Notifier
from tg_detox_locker.presenters import format_completion_report
from tg_detox_locker.repositories import add_audit_event, get_active_run, get_authorization_seen, get_settings, list_recent_runs
from tg_detox_locker.states import DetoxStateMachine
from tg_detox_locker.telethon_gateway import AuthorizationSnapshot, NewAuthorizationEvent, TelegramGateway
from tg_detox_locker.time_utils import coerce_utc, utc_now

LOGGER = logging.getLogger(__name__)
DEFAULT_RECENT_RUNS = 5
RUNNING_STATES = {LockerState.RUNNING, LockerState.DEGRADED_LOCKED}
MONITORED_STATES = {LockerState.RUNNING, LockerState.DEGRADED_LOCKED, LockerState.RESTORE_FAILED_LOCKED}
_KEEP = object()


def generate_password(length: int = 64) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}<>?"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ControlService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def queue_start(self, chat_id: int, duration_token: str | None) -> timedelta:
        async with self._session_factory() as session:
            settings = await get_settings(session, for_update=True)
            if settings is None:
                raise ConfigurationError("Service is not onboarded yet. Run the onboarding CLI on the server.")
            ensure_admin_chat(settings.admin_chat_id, chat_id)
            if settings.pending_command_kind is not None:
                raise StateConflictError("A command is already pending. Wait for the worker to pick it up.")
            active_run = await get_active_run(session)
            if active_run is not None or settings.current_state != LockerState.IDLE:
                raise StateConflictError(f"Detox locker is busy in state {settings.current_state.value}.")
            duration = parse_duration(duration_token) if duration_token else timedelta(seconds=settings.default_duration_seconds)
            settings.pending_command_kind = PendingCommand.START_DETOX.value
            settings.pending_command_payload = {"duration_seconds": int(duration.total_seconds()), "requested_by_chat_id": chat_id}
            settings.pending_command_requested_at = utc_now()
            settings.updated_at = utc_now()
            add_audit_event(
                session,
                event_type="start_command_queued",
                payload={"duration_seconds": int(duration.total_seconds()), "chat_id": chat_id},
            )
            await session.commit()
            return duration

    async def get_settings_and_run(self, chat_id: int) -> tuple[Settings, DetoxRun | None]:
        async with self._session_factory() as session:
            settings = await get_settings(session)
            if settings is None:
                raise ConfigurationError("Service is not onboarded yet. Run the onboarding CLI on the server.")
            ensure_admin_chat(settings.admin_chat_id, chat_id)
            active_run = await get_active_run(session)
            return settings, active_run

    async def get_history(self, chat_id: int) -> list[DetoxRun]:
        async with self._session_factory() as session:
            settings = await get_settings(session)
            if settings is None:
                raise ConfigurationError("Service is not onboarded yet. Run the onboarding CLI on the server.")
            ensure_admin_chat(settings.admin_chat_id, chat_id)
            runs = await list_recent_runs(session, DEFAULT_RECENT_RUNS)
            return list(runs)


class LockerRuntime:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        app_settings: AppSettings,
        secret_box: SecretBox,
        gateway_factory: Callable[[], TelegramGateway],
        notifier: Notifier,
        *,
        password_generator: Callable[[int], str] = generate_password,
    ) -> None:
        self._session_factory = session_factory
        self._app_settings = app_settings
        self._secret_box = secret_box
        self._gateway_factory = gateway_factory
        self._notifier = notifier
        self._password_generator = password_generator
        self._gateway: TelegramGateway | None = None
        self._auth_updates: asyncio.Queue[NewAuthorizationEvent] = asyncio.Queue()
        self._last_reconcile_tick = utc_now() - timedelta(seconds=app_settings.reconcile_interval_seconds)

    async def tick(self) -> None:
        try:
            await self._process_pending_start()
            await self._ensure_gateway_matches_state()
            await self._drain_authorization_updates()
            await self._maybe_reconcile()
            await self._maybe_finish_run()
            await self._maybe_retry_restore()
            await self._update_health(telegram_ok=self._gateway is not None)
        except Exception as exc:
            LOGGER.exception("Worker tick failed")
            await self._update_health(telegram_ok=self._gateway is not None, last_error=str(exc))

    async def close(self) -> None:
        if self._gateway is not None:
            await self._gateway.disconnect()
            self._gateway = None
        await self._notifier.close()

    async def _process_pending_start(self) -> None:
        async with self._session_factory() as session:
            settings = await get_settings(session, for_update=True)
            if settings is None or settings.pending_command_kind != PendingCommand.START_DETOX.value:
                return
            if settings.current_state != LockerState.IDLE:
                settings.pending_command_kind = None
                settings.pending_command_payload = None
                settings.pending_command_requested_at = None
                settings.last_error = f"Invalid state for start: {settings.current_state.value}"
                add_audit_event(session, event_type="start_command_rejected", payload={"reason": settings.last_error})
                await session.commit()
                return
            payload = settings.pending_command_payload or {}
            duration_seconds = int(payload.get("duration_seconds", 0))
            requested_by_chat_id = int(payload.get("requested_by_chat_id", settings.admin_chat_id))
            run = DetoxRun(
                state=LockerState.ARMING,
                requested_by_chat_id=requested_by_chat_id,
                requested_duration_seconds=duration_seconds,
                planned_end_at=utc_now() + timedelta(seconds=duration_seconds),
                start_reason="user_request",
            )
            session.add(run)
            await session.flush()
            settings.current_state = LockerState.ARMING
            settings.pending_command_kind = None
            settings.pending_command_payload = None
            settings.pending_command_requested_at = None
            add_audit_event(
                session,
                run_id=run.id,
                event_type="detox_arming",
                payload={"duration_seconds": duration_seconds, "requested_by_chat_id": requested_by_chat_id},
            )
            await session.commit()

        await self._start_run()

    async def _start_run(self) -> None:
        async with self._session_factory() as session:
            settings = await get_settings(session)
            run = await get_active_run(session)
            if settings is None or run is None:
                return
            session_string = self._secret_box.decrypt(settings.encrypted_string_session)
            baseline_password = self._secret_box.decrypt(settings.encrypted_baseline_password)

        gateway = await self._ensure_gateway_connected(session_string)

        try:
            authorizations = await gateway.list_authorizations()
            self._assert_preflight(settings, authorizations)
            detox_password = self._password_generator(64)
            await gateway.change_2fa(current_password=baseline_password, new_password=detox_password)
            await self._store_current_detox_secret(run.id, detox_password)
            await gateway.reset_other_authorizations()
        except Exception as exc:
            await self._handle_start_failure(run.id, str(exc), baseline_password)
            return

        async with self._session_factory() as session:
            settings = await get_settings(session, for_update=True)
            run = await get_active_run(session, for_update=True)
            if settings is None or run is None:
                return
            DetoxStateMachine(LockerState.ARMING).transition(LockerState.RUNNING)
            run.state = LockerState.RUNNING
            settings.current_state = LockerState.RUNNING
            settings.last_error = None
            add_audit_event(session, run_id=run.id, event_type="detox_running", payload={"planned_end_at": run.planned_end_at.isoformat()})
            admin_chat_id = settings.admin_chat_id
            planned_end_at = run.planned_end_at
            await session.commit()
        await self._notifier.send(admin_chat_id, f"Detox started.\nplanned_end_at: {planned_end_at.isoformat()}")

    async def _handle_start_failure(self, run_id: Any, reason: str, baseline_password: str) -> None:
        current_detox_password = await self._get_detox_password(run_id)
        rollback_error: str | None = None
        if current_detox_password and self._gateway is not None:
            try:
                await self._gateway.change_2fa(current_password=current_detox_password, new_password=baseline_password)
            except Exception as exc:
                rollback_error = str(exc)
        async with self._session_factory() as session:
            settings = await get_settings(session, for_update=True)
            run = await get_active_run(session, for_update=True)
            if settings is None or run is None:
                return
            if rollback_error is None:
                DetoxStateMachine(LockerState.ARMING).transition(LockerState.START_FAILED)
                run.state = LockerState.START_FAILED
                run.actual_end_at = utc_now()
                run.end_reason = "start_failed"
                run.failure_reason = reason
                run.encrypted_current_detox_password = None
                settings.current_state = LockerState.IDLE
            else:
                run.state = LockerState.DEGRADED_LOCKED
                run.failure_reason = f"{reason}; rollback_failed={rollback_error}"
                settings.current_state = LockerState.DEGRADED_LOCKED
            settings.last_error = run.failure_reason or reason
            add_audit_event(
                session,
                run_id=run.id,
                event_type="detox_start_failed",
                payload={"reason": reason, "rollback_error": rollback_error},
            )
            admin_chat_id = settings.admin_chat_id
            await session.commit()
        await self._notifier.send(admin_chat_id, f"Detox start failed.\nreason: {reason}\nrollback_error: {rollback_error or 'none'}")

    async def _maybe_reconcile(self) -> None:
        if self._gateway is None:
            return
        now = utc_now()
        if (now - self._last_reconcile_tick).total_seconds() < self._app_settings.reconcile_interval_seconds:
            return
        async with self._session_factory() as session:
            run = await get_active_run(session)
            settings = await get_settings(session)
            if run is None or settings is None or run.state not in MONITORED_STATES:
                self._last_reconcile_tick = now
                return
        snapshots = await self._gateway.list_authorizations()
        for snapshot in snapshots:
            if snapshot.current:
                continue
            await self._process_authorization_attempt(snapshot.authorization_hash, snapshot.device, snapshot.location, "reconcile")
        await self._update_health(telegram_ok=True, last_reconcile_at=now)
        self._last_reconcile_tick = now

    async def _maybe_finish_run(self) -> None:
        async with self._session_factory() as session:
            run = await get_active_run(session)
            settings = await get_settings(session)
            if run is None or settings is None or run.state not in RUNNING_STATES:
                return
            if coerce_utc(run.planned_end_at) > utc_now():
                return
            run.state = LockerState.ENDING
            settings.current_state = LockerState.ENDING
            add_audit_event(session, run_id=run.id, event_type="detox_ending", payload={})
            await session.commit()
        await self._restore_baseline()

    async def _maybe_retry_restore(self) -> None:
        async with self._session_factory() as session:
            run = await get_active_run(session)
            settings = await get_settings(session)
            if run is None or settings is None or run.state != LockerState.RESTORE_FAILED_LOCKED:
                return
            if run.last_restore_retry_at is not None:
                delta = utc_now() - coerce_utc(run.last_restore_retry_at)
                if delta.total_seconds() < self._app_settings.restore_retry_seconds:
                    return
        await self._restore_baseline()

    async def _restore_baseline(self) -> None:
        async with self._session_factory() as session:
            settings = await get_settings(session)
            run = await get_active_run(session)
            if settings is None or run is None:
                return
            baseline_password = self._secret_box.decrypt(settings.encrypted_baseline_password)
            detox_password = run.encrypted_current_detox_password
            session_string = self._secret_box.decrypt(settings.encrypted_string_session)
            admin_chat_id = settings.admin_chat_id
        if detox_password is None:
            raise RuntimeError("Active run is missing the detox password.")
        if self._gateway is None:
            await self._ensure_gateway_connected(session_string)
        try:
            await self._gateway.change_2fa(
                current_password=self._secret_box.decrypt(detox_password),
                new_password=baseline_password,
            )
        except Exception as exc:
            async with self._session_factory() as session:
                settings = await get_settings(session, for_update=True)
                run = await get_active_run(session, for_update=True)
                if settings is None or run is None:
                    return
                run.state = LockerState.RESTORE_FAILED_LOCKED
                run.failure_reason = str(exc)
                run.last_restore_retry_at = utc_now()
                settings.current_state = LockerState.RESTORE_FAILED_LOCKED
                settings.last_error = str(exc)
                add_audit_event(session, run_id=run.id, event_type="baseline_restore_failed", payload={"reason": str(exc)})
                await session.commit()
            await self._notifier.send(admin_chat_id, f"Baseline password restore failed. Worker will retry.\nreason: {exc}")
            return

        async with self._session_factory() as session:
            settings = await get_settings(session, for_update=True)
            run = await get_active_run(session, for_update=True)
            if settings is None or run is None:
                return
            if run.state == LockerState.ENDING:
                DetoxStateMachine(LockerState.ENDING).transition(LockerState.COMPLETED)
            else:
                DetoxStateMachine(LockerState.RESTORE_FAILED_LOCKED).transition(LockerState.COMPLETED)
            run.state = LockerState.COMPLETED
            run.actual_end_at = utc_now()
            run.end_reason = "timer_elapsed"
            run.encrypted_current_detox_password = None
            settings.current_state = LockerState.IDLE
            settings.last_error = None
            add_audit_event(session, run_id=run.id, event_type="baseline_restored", payload={})
            await session.commit()
            report = format_completion_report(run)
        await self._notifier.send(admin_chat_id, report)

    async def _ensure_gateway_matches_state(self) -> None:
        async with self._session_factory() as session:
            settings = await get_settings(session)
            run = await get_active_run(session)
            if settings is None:
                return
            if run is None:
                if self._gateway is not None:
                    await self._gateway.disconnect()
                    self._gateway = None
                return
            if self._gateway is None:
                session_string = self._secret_box.decrypt(settings.encrypted_string_session)
                await self._ensure_gateway_connected(session_string)

    async def _ensure_gateway_connected(self, session_string: str) -> TelegramGateway:
        if self._gateway is not None:
            return self._gateway
        gateway = self._gateway_factory()
        await gateway.connect(session_string, self._queue_new_authorization)
        self._gateway = gateway
        return gateway

    async def _queue_new_authorization(self, event: NewAuthorizationEvent) -> None:
        await self._auth_updates.put(event)

    async def _drain_authorization_updates(self) -> None:
        while not self._auth_updates.empty():
            event = await self._auth_updates.get()
            await self._process_authorization_attempt(
                event.authorization_hash,
                event.device,
                event.location,
                "update",
                created_at=event.created_at,
            )
            await self._update_health(telegram_ok=True, last_update_at=utc_now())

    async def _process_authorization_attempt(
        self,
        authorization_hash: int,
        device: str,
        location: str,
        source: str,
        *,
        created_at=None,
    ) -> None:
        if self._gateway is None:
            return
        async with self._session_factory() as session:
            run = await get_active_run(session, for_update=True)
            settings = await get_settings(session, for_update=True)
            if run is None or settings is None or run.state not in MONITORED_STATES:
                return
            seen = await get_authorization_seen(session, run.id, authorization_hash)
            if seen is None:
                seen = AuthorizationSeen(
                    run_id=run.id,
                    authorization_hash=authorization_hash,
                    device=device,
                    location=location,
                    source=source,
                    first_seen_at=created_at or utc_now(),
                )
                session.add(seen)
                run.attempt_count += 1
                add_audit_event(
                    session,
                    run_id=run.id,
                    event_type="authorization_seen",
                    payload={"authorization_hash": authorization_hash, "device": device, "location": location, "source": source},
                )
            elif seen.revoked_at is not None:
                await session.commit()
                return
            admin_chat_id = settings.admin_chat_id
            await session.commit()

        revoke_error: str | None = None
        try:
            await self._gateway.revoke_authorization(authorization_hash)
        except Exception as exc:
            revoke_error = str(exc)

        async with self._session_factory() as session:
            run = await get_active_run(session, for_update=True)
            settings = await get_settings(session, for_update=True)
            if run is None or settings is None:
                return
            seen = await get_authorization_seen(session, run.id, authorization_hash)
            if seen is not None and revoke_error is None:
                seen.revoked_at = utc_now()
            if revoke_error is not None:
                run.state = LockerState.DEGRADED_LOCKED
                run.failure_reason = revoke_error
                settings.current_state = LockerState.DEGRADED_LOCKED
                settings.last_error = revoke_error
                add_audit_event(
                    session,
                    run_id=run.id,
                    event_type="authorization_revoke_failed",
                    payload={"authorization_hash": authorization_hash, "reason": revoke_error},
                )
            await session.commit()
            current_state = run.state

        if revoke_error is not None:
            await self._notifier.send(admin_chat_id, f"Authorization revoke failed.\nhash: {authorization_hash}\nreason: {revoke_error}")
            return

        if current_state in MONITORED_STATES:
            await self._rotate_detox_password(admin_chat_id)

    async def _rotate_detox_password(self, admin_chat_id: int) -> None:
        async with self._session_factory() as session:
            run = await get_active_run(session)
            if run is None or run.encrypted_current_detox_password is None:
                return
            current_password = self._secret_box.decrypt(run.encrypted_current_detox_password)
        new_password = self._password_generator(64)
        try:
            await self._gateway.change_2fa(current_password=current_password, new_password=new_password)
        except Exception as exc:
            async with self._session_factory() as session:
                run = await get_active_run(session, for_update=True)
                settings = await get_settings(session, for_update=True)
                if run is None or settings is None:
                    return
                run.state = LockerState.DEGRADED_LOCKED
                run.failure_reason = str(exc)
                settings.current_state = LockerState.DEGRADED_LOCKED
                settings.last_error = str(exc)
                add_audit_event(session, run_id=run.id, event_type="detox_password_rotation_failed", payload={"reason": str(exc)})
                await session.commit()
            await self._notifier.send(admin_chat_id, f"Detox password rotation failed.\nreason: {exc}")
            return

        async with self._session_factory() as session:
            run = await get_active_run(session, for_update=True)
            if run is None:
                return
            run.encrypted_current_detox_password = self._secret_box.encrypt(new_password)
            add_audit_event(session, run_id=run.id, event_type="detox_password_rotated", payload={})
            await session.commit()

    async def _get_detox_password(self, run_id: Any) -> str | None:
        async with self._session_factory() as session:
            run = await session.get(DetoxRun, run_id)
            if run is None or run.encrypted_current_detox_password is None:
                return None
            return self._secret_box.decrypt(run.encrypted_current_detox_password)

    async def _store_current_detox_secret(self, run_id: Any, password: str) -> None:
        async with self._session_factory() as session:
            run = await session.get(DetoxRun, run_id)
            if run is None:
                return
            run.encrypted_current_detox_password = self._secret_box.encrypt(password)
            await session.commit()

    async def _update_health(
        self,
        *,
        telegram_ok: bool,
        last_error: str | None | object = _KEEP,
        last_reconcile_at=None,
        last_update_at=None,
    ) -> None:
        async with self._session_factory() as session:
            settings = await get_settings(session, for_update=True)
            if settings is None:
                return
            settings.telegram_ok = telegram_ok
            if last_error is not _KEEP:
                settings.last_error = last_error
            settings.last_heartbeat_at = utc_now()
            if last_reconcile_at is not None:
                settings.last_reconcile_at = last_reconcile_at
            if last_update_at is not None:
                settings.last_update_at = last_update_at
            await session.commit()

    def _assert_preflight(self, settings: Settings, authorizations: list[AuthorizationSnapshot]) -> None:
        baseline_age = utc_now() - coerce_utc(settings.baseline_password_verified_at)
        if baseline_age < timedelta(hours=24):
            raise PreflightError("Stored baseline 2FA password is too fresh. Wait until 24 hours have passed since onboarding.")
        current_authorizations = [item for item in authorizations if item.current]
        if not current_authorizations:
            raise PreflightError("Current locker authorization was not found in Telegram authorizations list.")
        current = current_authorizations[0]
        if current.created_at is None:
            raise PreflightError("Current locker session creation time is unavailable. Cannot verify Telegram 24-hour constraint.")
        if utc_now() - coerce_utc(current.created_at) < timedelta(hours=24):
            raise PreflightError("Current locker session is too fresh. Wait until it is at least 24 hours old.")
