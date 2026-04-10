from __future__ import annotations

import uuid
from datetime import UTC, datetime

from astrbot.core.platform.astr_message_event import AstrMessageEvent

from .store import MemoryStore
from .types import MemoryIdentity, MemoryIdentityBinding


def build_platform_user_key(platform_id: str, sender_user_id: str) -> str:
    return f"{platform_id}:{sender_user_id}"


class MemoryIdentityMappingService:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def resolve_canonical_user_id(self, platform_user_key: str) -> str | None:
        binding = await self.store.get_identity_mapping(platform_user_key)
        if binding is None:
            return None
        return binding.canonical_user_id

    async def bind_platform_user(
        self,
        platform_id: str,
        sender_user_id: str,
        canonical_user_id: str,
        nickname_hint: str | None = None,
    ) -> MemoryIdentityBinding:
        return await self.store.save_identity_mapping(
            MemoryIdentityBinding(
                mapping_id=str(uuid.uuid4()),
                platform_id=platform_id,
                sender_user_id=sender_user_id,
                platform_user_key=build_platform_user_key(platform_id, sender_user_id),
                canonical_user_id=canonical_user_id,
                nickname_hint=nickname_hint,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

    async def unbind_platform_user(self, platform_user_key: str) -> bool:
        return await self.store.delete_identity_mapping(platform_user_key)

    async def list_bindings_for_canonical_user(
        self,
        canonical_user_id: str,
    ) -> list[MemoryIdentityBinding]:
        return await self.store.list_identity_mappings_for_canonical_user(
            canonical_user_id
        )


class MemoryIdentityResolver:
    def __init__(self, mapping_service: MemoryIdentityMappingService) -> None:
        self.mapping_service = mapping_service

    async def resolve_from_event(self, event: AstrMessageEvent) -> MemoryIdentity:
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        platform_id = str(event.get_platform_id() or "").strip()
        sender_user_id = str(event.get_sender_id() or "").strip()
        sender_nickname = event.get_sender_name() or None

        if not umo:
            raise ValueError(
                "memory identity resolver requires event.unified_msg_origin"
            )
        if not platform_id:
            raise ValueError(
                "memory identity resolver requires event.get_platform_id()"
            )
        if not sender_user_id:
            raise ValueError("memory identity resolver requires event.get_sender_id()")

        platform_user_key = build_platform_user_key(platform_id, sender_user_id)
        canonical_user_id = await self.mapping_service.resolve_canonical_user_id(
            platform_user_key
        )
        return MemoryIdentity(
            umo=umo,
            platform_id=platform_id,
            sender_user_id=sender_user_id,
            sender_nickname=sender_nickname,
            platform_user_key=platform_user_key,
            canonical_user_id=canonical_user_id,
        )
