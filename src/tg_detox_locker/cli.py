from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from telethon import TelegramClient
from telethon.sessions import StringSession

from tg_detox_locker.config import load_settings
from tg_detox_locker.crypto import SecretBox
from tg_detox_locker.db import create_engine, create_session_factory
from tg_detox_locker.duration import parse_duration
from tg_detox_locker.enums import LockerState
from tg_detox_locker.logging_utils import configure_logging
from tg_detox_locker.models import Base, Settings
from tg_detox_locker.repositories import add_audit_event, get_active_run, get_settings
from tg_detox_locker.services import LockerRuntime
from tg_detox_locker.telethon_gateway import TelethonGateway
from tg_detox_locker.time_utils import utc_now


class _NoopNotifier:
    async def send(self, chat_id: int, text: str) -> None:
        return None

    async def close(self) -> None:
        return None


async def _init_db() -> None:
    settings = load_settings()
    engine = create_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _run_onboarding(phone: str, admin_chat_id: int, overwrite: bool) -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    secret_box = SecretBox(settings.master_key)
    default_duration_seconds = int(parse_duration(settings.default_detox_duration).total_seconds())
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    client = TelegramClient(StringSession(), settings.telegram_api_id, settings.telegram_api_hash)
    baseline_password = getpass("Baseline 2FA password: ")
    try:
        await client.start(phone=phone, password=lambda: baseline_password)
        string_session = client.session.save()
        async with session_factory() as session:
            existing = await get_settings(session, for_update=True)
            if existing is not None and not overwrite:
                raise RuntimeError("Settings already exist. Use --overwrite to replace the stored session and baseline password.")
            onboarded_at = utc_now()
            if existing is None:
                session.add(
                    Settings(
                        id=1,
                        encrypted_string_session=secret_box.encrypt(string_session),
                        encrypted_baseline_password=secret_box.encrypt(baseline_password),
                        admin_chat_id=admin_chat_id,
                        current_state=LockerState.IDLE,
                        default_duration_seconds=default_duration_seconds,
                        onboarded_at=onboarded_at,
                        baseline_password_verified_at=onboarded_at,
                        updated_at=onboarded_at,
                    )
                )
            else:
                existing.encrypted_string_session = secret_box.encrypt(string_session)
                existing.encrypted_baseline_password = secret_box.encrypt(baseline_password)
                existing.admin_chat_id = admin_chat_id
                existing.current_state = LockerState.IDLE
                existing.default_duration_seconds = default_duration_seconds
                existing.pending_command_kind = None
                existing.pending_command_payload = None
                existing.pending_command_requested_at = None
                existing.onboarded_at = onboarded_at
                existing.baseline_password_verified_at = onboarded_at
                existing.updated_at = onboarded_at
            add_audit_event(
                session,
                event_type="onboarding_completed",
                payload={"phone": phone, "admin_chat_id": admin_chat_id, "overwrite": overwrite},
            )
            await session.commit()
    finally:
        await client.disconnect()
        await engine.dispose()


async def _run_recover() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    secret_box = SecretBox(settings.master_key)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    gateway = TelethonGateway(settings.telegram_api_id, settings.telegram_api_hash)
    runtime = LockerRuntime(
        session_factory=session_factory,
        app_settings=settings,
        secret_box=secret_box,
        gateway_factory=lambda: gateway,
        notifier=_NoopNotifier(),
    )
    try:
        async with session_factory() as session:
            settings_row = await get_settings(session)
            active_run = await get_active_run(session)
            if settings_row is None or active_run is None:
                raise RuntimeError("No active detox run found.")
            session_string = secret_box.decrypt(settings_row.encrypted_string_session)
            await gateway.connect(session_string)
        await runtime._restore_baseline()  # noqa: SLF001 - operator-only CLI
        async with session_factory() as session:
            active_run = await get_active_run(session)
            add_audit_event(session, run_id=active_run.id if active_run else None, event_type="disaster_recovery_triggered", payload={})
            await session.commit()
    finally:
        await runtime.close()
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram Detox Locker CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Create the schema directly without Alembic")
    init_db.set_defaults(func=lambda args: _init_db())

    onboarding = subparsers.add_parser("onboarding", help="Onboard the protected account")
    onboarding.add_argument("--phone", required=True)
    onboarding.add_argument("--admin-chat-id", required=True, type=int)
    onboarding.add_argument("--overwrite", action="store_true")
    onboarding.set_defaults(func=lambda args: _run_onboarding(args.phone, args.admin_chat_id, args.overwrite))

    recover = subparsers.add_parser("recover", help="Restore the baseline password for the active run")
    recover.set_defaults(func=lambda args: _run_recover())
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
