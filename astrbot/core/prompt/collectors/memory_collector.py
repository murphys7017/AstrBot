"""
Memory context collector for prompt context packing.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from astrbot.core import logger
from astrbot.core.memory.service import get_memory_service
from astrbot.core.memory.types import MemorySnapshot
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..context_types import ContextSlot
from ..interfaces.context_collector_inferface import ContextCollectorInterface

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig


class MemoryCollector(ContextCollectorInterface):
    """Collect prompt memory context from the current memory snapshot."""

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[ContextSlot]:
        del plugin_context, config

        umo = getattr(event, "unified_msg_origin", None)
        if not isinstance(umo, str) or not umo.strip():
            return []

        conversation_id = self._resolve_conversation_id(provider_request)
        query = self._resolve_query(event, provider_request)

        try:
            snapshot = await get_memory_service().get_snapshot(
                umo=umo,
                conversation_id=conversation_id,
                query=query,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to collect memory snapshot: umo=%s conversation_id=%s error=%s",
                umo,
                conversation_id,
                exc,
                exc_info=True,
            )
            return []

        slots: list[ContextSlot] = []

        topic_state_slot = self._build_topic_state_slot(snapshot)
        if topic_state_slot is not None:
            slots.append(topic_state_slot)

        short_term_slot = self._build_short_term_slot(snapshot)
        if short_term_slot is not None:
            slots.append(short_term_slot)

        return slots

    def _build_topic_state_slot(
        self,
        snapshot: MemorySnapshot,
    ) -> ContextSlot | None:
        topic_state = snapshot.topic_state
        if topic_state is None:
            return None

        return ContextSlot(
            name="memory.topic_state",
            value={
                "umo": topic_state.umo,
                "conversation_id": topic_state.conversation_id,
                "current_topic": topic_state.current_topic,
                "topic_summary": topic_state.topic_summary,
                "topic_confidence": topic_state.topic_confidence,
                "last_active_at": self._serialize_datetime(topic_state.last_active_at),
            },
            category="memory",
            source="memory_snapshot",
            meta={
                "snapshot_field": "topic_state",
                "has_value": True,
            },
        )

    def _build_short_term_slot(
        self,
        snapshot: MemorySnapshot,
    ) -> ContextSlot | None:
        short_term_memory = snapshot.short_term_memory
        if short_term_memory is None:
            return None

        return ContextSlot(
            name="memory.short_term",
            value={
                "umo": short_term_memory.umo,
                "conversation_id": short_term_memory.conversation_id,
                "short_summary": short_term_memory.short_summary,
                "active_focus": short_term_memory.active_focus,
                "updated_at": self._serialize_datetime(short_term_memory.updated_at),
            },
            category="memory",
            source="memory_snapshot",
            meta={
                "snapshot_field": "short_term_memory",
                "has_value": True,
            },
        )

    def _resolve_conversation_id(
        self,
        provider_request: ProviderRequest | None,
    ) -> str | None:
        if provider_request is None or provider_request.conversation is None:
            return None

        conversation_id = getattr(provider_request.conversation, "cid", None)
        if isinstance(conversation_id, str) and conversation_id.strip():
            return conversation_id
        return None

    def _resolve_query(
        self,
        event: AstrMessageEvent,
        provider_request: ProviderRequest | None,
    ) -> str | None:
        if provider_request and isinstance(provider_request.prompt, str):
            prompt = provider_request.prompt.strip()
            if prompt:
                return prompt

        message_str = getattr(event, "message_str", None)
        if isinstance(message_str, str):
            message_str = message_str.strip()
            if message_str:
                return message_str

        return None

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat(timespec="seconds")
