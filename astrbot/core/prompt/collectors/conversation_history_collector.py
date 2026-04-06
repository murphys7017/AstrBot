"""
Conversation history collector for prompt context packing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from astrbot.core import logger
from astrbot.core.memory.history_source import (
    extract_turn_payloads,
    parse_conversation_history,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.star.context import Context

from ..context_types import ContextSlot
from ..interfaces.context_collector_inferface import ContextCollectorInterface

if TYPE_CHECKING:
    from astrbot.core.astr_main_agent import MainAgentBuildConfig


class ConversationHistoryCollector(ContextCollectorInterface):
    """Collect the current conversation history as normalized turn pairs."""

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[ContextSlot]:
        del event, plugin_context, config

        history_payload = self._resolve_history_source(provider_request)
        if history_payload is None:
            return []

        return [self._build_history_slot(provider_request, history_payload)]

    def _resolve_history_source(
        self,
        provider_request: ProviderRequest | None,
    ) -> dict[str, Any] | None:
        if provider_request is None:
            return None

        conversation = getattr(provider_request, "conversation", None)
        if conversation is not None:
            history_payload = self._load_conversation_history(
                raw_history=getattr(conversation, "history", None),
                source_name="provider_request.conversation.history",
            )
            if history_payload is not None:
                return history_payload

        return self._load_conversation_history(
            raw_history=getattr(provider_request, "contexts", None),
            source_name="provider_request.contexts",
        )

    def _load_conversation_history(
        self,
        *,
        raw_history: str | list[dict[str, Any]] | None,
        source_name: str,
    ) -> dict[str, Any] | None:
        try:
            messages = parse_conversation_history(raw_history)
            turns = extract_turn_payloads(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to collect conversation history from %s: %s",
                source_name,
                exc,
                exc_info=True,
            )
            return None

        if not turns:
            return None

        return {
            "source": source_name,
            "turns": turns,
        }

    def _build_history_slot(
        self,
        provider_request: ProviderRequest | None,
        history_payload: dict[str, Any],
    ) -> ContextSlot:
        conversation_id = None
        if provider_request is not None and provider_request.conversation is not None:
            raw_conversation_id = getattr(provider_request.conversation, "cid", None)
            if isinstance(raw_conversation_id, str) and raw_conversation_id.strip():
                conversation_id = raw_conversation_id

        turns = history_payload["turns"]
        source_name = history_payload["source"]
        return ContextSlot(
            name="conversation.history",
            value={
                "format": "turn_pairs",
                "source": source_name,
                "conversation_id": conversation_id,
                "turn_count": len(turns),
                "turns": turns,
            },
            category="memory",
            source=source_name,
            meta={
                "format": "turn_pairs",
                "turn_count": len(turns),
            },
        )
