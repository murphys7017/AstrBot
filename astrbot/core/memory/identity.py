from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from astrbot.core.platform.astr_message_event import AstrMessageEvent

from .config import MemoryConfig, get_memory_config, load_memory_config
from .store import MemoryStore
from .types import MemoryIdentity, MemoryIdentityBinding


def build_platform_user_key(platform_id: str, sender_user_id: str) -> str:
    return f"{platform_id}:{sender_user_id}"


def resolve_configured_canonical_user_id(
    event: AstrMessageEvent,
    *,
    config: MemoryConfig | Mapping[str, object] | None = None,
) -> str | None:
    """Resolve a configured canonical user without touching the memory store.

    Prompt and external memory providers need the same identity binding as the
    built-in memory service, but they must not initialize or query its SQLite
    store. This pure lookup keeps the configuration contract in Core while
    allowing those providers to resolve identity on their own hot path.
    """

    if isinstance(config, MemoryConfig):
        memory_config = config
    elif isinstance(config, Mapping):
        payload = config.get("memory")
        if isinstance(payload, Mapping):
            memory_config = get_memory_config(config)
        else:
            memory_config = load_memory_config(payload=config)
    else:
        memory_config = get_memory_config()
    if not memory_config.identity.enabled:
        return None

    platform_id = _normalize_optional_string(
        _safe_event_call(event, "get_platform_id")
    ) or _normalize_optional_string(_safe_event_call(event, "get_platform_name"))
    sender_user_id = _normalize_optional_string(
        _safe_event_call(event, "get_sender_id")
    )
    if not platform_id or not sender_user_id:
        return None

    for raw_binding in memory_config.identity.bindings or ():
        if not isinstance(raw_binding, dict):
            continue
        binding_platform = _normalize_optional_string(raw_binding.get("platform_id"))
        binding_sender = _normalize_optional_string(raw_binding.get("sender_user_id"))
        canonical_user_id = _normalize_optional_string(
            raw_binding.get("canonical_user_id")
        )
        if (
            binding_platform == platform_id
            and binding_sender == sender_user_id
            and canonical_user_id
        ):
            return canonical_user_id
    return None


def _safe_event_call(event: AstrMessageEvent, method_name: str) -> Any:
    method = getattr(event, method_name, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:  # noqa: BLE001
        return None


def _normalize_optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


class MemoryIdentityMappingService:
    def __init__(
        self,
        store: MemoryStore,
        *,
        config: MemoryConfig | None = None,
    ) -> None:
        self.store = store
        self.config = config or store.config or get_memory_config()

    async def resolve_canonical_user_id(self, platform_user_key: str) -> str | None:
        binding = await self.store.get_identity_mapping(platform_user_key)
        if binding is None:
            return None
        return binding.canonical_user_id

    async def reload_from_config(self) -> int:
        if not self.config.identity.enabled:
            return await self.store.sync_identity_mappings([])
        bindings = self.load_bindings()
        return await self.store.sync_identity_mappings(bindings)

    def load_bindings(self) -> list[MemoryIdentityBinding]:
        return self._parse_bindings_payload(
            {"bindings": self._filter_empty_template_bindings(
                self.config.identity.bindings
            )}
        )

    def _parse_bindings_payload(
        self,
        payload: dict[str, Any],
    ) -> list[MemoryIdentityBinding]:
        raw_bindings = payload.get("bindings")
        if not isinstance(raw_bindings, list):
            raise ValueError("memory identity mappings field `bindings` must be a list")

        bindings: list[MemoryIdentityBinding] = []
        seen_keys: set[str] = set()
        for index, raw_binding in enumerate(raw_bindings):
            if not isinstance(raw_binding, dict):
                raise ValueError(
                    f"memory identity mapping entry #{index} must be an object"
                )
            platform_id = self._required_string(
                raw_binding.get("platform_id"),
                f"bindings[{index}].platform_id",
            )
            sender_user_id = self._required_string(
                raw_binding.get("sender_user_id"),
                f"bindings[{index}].sender_user_id",
            )
            canonical_user_id = self._required_string(
                raw_binding.get("canonical_user_id"),
                f"bindings[{index}].canonical_user_id",
            )
            nickname_hint = self._optional_string(raw_binding.get("nickname_hint"))
            binding = self._build_binding(
                platform_id=platform_id,
                sender_user_id=sender_user_id,
                canonical_user_id=canonical_user_id,
                nickname_hint=nickname_hint,
            )
            if binding.platform_user_key in seen_keys:
                raise ValueError(
                    "duplicate memory identity mapping for platform_user_key "
                    f"`{binding.platform_user_key}`"
                )
            seen_keys.add(binding.platform_user_key)
            bindings.append(binding)
        return bindings

    def _filter_empty_template_bindings(
        self,
        raw_bindings: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        if not raw_bindings:
            return []
        return [
            item for item in raw_bindings if not self._is_empty_template_binding(item)
        ]

    @staticmethod
    def _is_empty_template_binding(raw_binding: Any) -> bool:
        if not isinstance(raw_binding, dict):
            return False
        return (
            not MemoryIdentityMappingService._optional_string(
                raw_binding.get("platform_id")
            )
            and not MemoryIdentityMappingService._optional_string(
                raw_binding.get("sender_user_id")
            )
            and not MemoryIdentityMappingService._optional_string(
                raw_binding.get("canonical_user_id")
            )
            and not MemoryIdentityMappingService._optional_string(
                raw_binding.get("nickname_hint")
            )
        )

    @staticmethod
    def _required_string(value: Any, field_name: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError(
            f"memory identity mapping missing required field `{field_name}`"
        )

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _build_binding(
        *,
        platform_id: str,
        sender_user_id: str,
        canonical_user_id: str,
        nickname_hint: str | None,
    ) -> MemoryIdentityBinding:
        now = datetime.now(UTC)
        return MemoryIdentityBinding(
            mapping_id=str(uuid.uuid4()),
            platform_id=platform_id.strip(),
            sender_user_id=sender_user_id.strip(),
            platform_user_key=build_platform_user_key(
                platform_id.strip(),
                sender_user_id.strip(),
            ),
            canonical_user_id=canonical_user_id.strip(),
            nickname_hint=nickname_hint.strip() if nickname_hint else None,
            created_at=now,
            updated_at=now,
        )


class MemoryIdentityResolver:
    def __init__(self, mapping_service: MemoryIdentityMappingService) -> None:
        self.mapping_service = mapping_service

    async def resolve_from_event(self, event: AstrMessageEvent) -> MemoryIdentity:
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not umo:
            raise ValueError(
                "memory identity resolver requires event.unified_msg_origin"
            )

        platform_id = self._normalize_optional_string(
            self._safe_call(event, "get_platform_id")
        )
        sender_user_id = self._normalize_optional_string(
            self._safe_call(event, "get_sender_id")
        )
        sender_nickname = self._resolve_sender_nickname(event)

        platform_user_key: str | None = None
        canonical_user_id: str | None = None
        if platform_id and sender_user_id:
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

    @staticmethod
    def _safe_call(event: AstrMessageEvent, method_name: str) -> Any:
        method = getattr(event, method_name, None)
        if callable(method):
            return method()
        return None

    @staticmethod
    def _normalize_optional_string(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _resolve_sender_nickname(self, event: AstrMessageEvent) -> str | None:
        direct_name = self._normalize_optional_string(
            self._safe_call(event, "get_sender_name")
        )
        if direct_name:
            return direct_name

        message_obj = getattr(event, "message_obj", None)
        sender = getattr(message_obj, "sender", None)
        nickname = getattr(sender, "nickname", None)
        return self._normalize_optional_string(nickname)
