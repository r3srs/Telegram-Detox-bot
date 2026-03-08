from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.tl import types


@dataclass(slots=True)
class AuthorizationSnapshot:
    authorization_hash: int
    current: bool
    device: str
    location: str
    created_at: datetime | None


@dataclass(slots=True)
class NewAuthorizationEvent:
    authorization_hash: int
    device: str
    location: str
    created_at: datetime | None
    unconfirmed: bool


class TelegramGateway(Protocol):
    async def connect(
        self,
        session_string: str,
        on_new_authorization: Callable[[NewAuthorizationEvent], Awaitable[None]] | None = None,
    ) -> None: ...

    async def disconnect(self) -> None: ...

    async def list_authorizations(self) -> list[AuthorizationSnapshot]: ...

    async def change_2fa(self, current_password: str, new_password: str) -> None: ...

    async def reset_other_authorizations(self) -> None: ...

    async def revoke_authorization(self, authorization_hash: int) -> None: ...


class TelethonGateway:
    def __init__(self, api_id: int, api_hash: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._client: TelegramClient | None = None

    async def connect(
        self,
        session_string: str,
        on_new_authorization: Callable[[NewAuthorizationEvent], Awaitable[None]] | None = None,
    ) -> None:
        client = TelegramClient(
            StringSession(session_string),
            self._api_id,
            self._api_hash,
            receive_updates=True,
            sequential_updates=True,
        )

        if on_new_authorization is not None:

            @client.on(events.Raw())
            async def _raw_handler(event: events.Raw) -> None:
                raw = getattr(event, "_raw", None)
                if raw is None or not isinstance(raw, types.UpdateNewAuthorization):
                    return
                auth_hash = getattr(raw, "hash", None)
                if auth_hash is None:
                    auth_hash = getattr(raw, "auth_key_id")
                await on_new_authorization(
                    NewAuthorizationEvent(
                        authorization_hash=int(auth_hash),
                        device=getattr(raw, "device", "unknown"),
                        location=getattr(raw, "location", "unknown"),
                        created_at=getattr(raw, "date", None),
                        unconfirmed=bool(getattr(raw, "unconfirmed", False)),
                    )
                )

        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError("Stored Telethon session is no longer authorized.")
        self._client = client

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def list_authorizations(self) -> list[AuthorizationSnapshot]:
        client = self._require_client()
        result = await client(functions.account.GetAuthorizationsRequest())
        snapshots: list[AuthorizationSnapshot] = []
        for authorization in result.authorizations:
            device_parts = [getattr(authorization, "device_model", None), getattr(authorization, "platform", None)]
            location_parts = [getattr(authorization, "country", None), getattr(authorization, "region", None)]
            snapshots.append(
                AuthorizationSnapshot(
                    authorization_hash=int(getattr(authorization, "hash")),
                    current=bool(getattr(authorization, "current", False)),
                    device=" / ".join(part for part in device_parts if part) or "unknown",
                    location=" / ".join(part for part in location_parts if part) or "unknown",
                    created_at=getattr(authorization, "date_created", None),
                )
            )
        return snapshots

    async def change_2fa(self, current_password: str, new_password: str) -> None:
        client = self._require_client()
        await client.edit_2fa(current_password=current_password, new_password=new_password)

    async def reset_other_authorizations(self) -> None:
        client = self._require_client()
        await client(functions.auth.ResetAuthorizationsRequest())

    async def revoke_authorization(self, authorization_hash: int) -> None:
        client = self._require_client()
        await client(functions.account.ResetAuthorizationRequest(hash=authorization_hash))

    def _require_client(self) -> TelegramClient:
        if self._client is None:
            raise RuntimeError("Telethon client is not connected.")
        return self._client
