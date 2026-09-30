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


_CURRENT_CONVERSATION_HISTORY_CACHE_EXTRA_KEY = (
    "_prompt_current_conversation_history_cache"
)


class ConversationHistoryCollector(ContextCollectorInterface):
    """Collect the current conversation history as normalized turn pairs."""

    async def collect(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        config: MainAgentBuildConfig,
        provider_request: ProviderRequest | None = None,
    ) -> list[ContextSlot]:
        history_payload = await self._resolve_history_source(
            event,
            plugin_context,
            provider_request,
        )
        if history_payload is None:
            return []

        return [self._build_history_slot(provider_request, history_payload)]

    async def _resolve_history_source(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        provider_request: ProviderRequest | None,
    ) -> dict[str, Any] | None:
        conversation_payload = await self._load_current_conversation_history(
            event,
            plugin_context,
            provider_request,
        )
        if conversation_payload is not None:
            return conversation_payload

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

    async def _load_current_conversation_history(
        self,
        event: AstrMessageEvent,
        plugin_context: Context,
        provider_request: ProviderRequest | None,
    ) -> dict[str, Any] | None:
        conversation_manager = getattr(plugin_context, "conversation_manager", None)
        if conversation_manager is None:
            return None

        try:
            conversation_id = await conversation_manager.get_curr_conversation_id(
                event.unified_msg_origin
            )
            if not conversation_id:
                return None
            cache = event.get_extra(
                _CURRENT_CONVERSATION_HISTORY_CACHE_EXTRA_KEY,
                {},
            )
            if isinstance(cache, dict):
                cached_conversation_id = cache.get("conversation_id")
                cached_payload = cache.get("payload")
                if (
                    cached_conversation_id == conversation_id
                    and isinstance(cached_payload, dict)
                    and cache.get("provider_request") is provider_request
                ):
                    return cached_payload

            # The request normally carries the same conversation object that
            # was used to resolve the current ID. Reuse its already-loaded
            # history while keeping the manager's ID as the authority.
            request_conversation = getattr(provider_request, "conversation", None)
            if (
                request_conversation is not None
                and getattr(request_conversation, "cid", None) == conversation_id
            ):
                payload = self._load_conversation_history(
                    raw_history=getattr(request_conversation, "history", None),
                    source_name="conversation_manager.current_conversation.history",
                )
                if payload is not None:
                    payload["conversation_id"] = conversation_id
                    event.set_extra(
                        _CURRENT_CONVERSATION_HISTORY_CACHE_EXTRA_KEY,
                        {
                            "conversation_id": conversation_id,
                            "provider_request": provider_request,
                            "payload": payload,
                        },
                    )
                    return payload

            conversation = await conversation_manager.get_conversation(
                event.unified_msg_origin,
                conversation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to collect current official conversation history: umo=%s error=%s",
                event.unified_msg_origin,
                exc,
                exc_info=True,
            )
            return None

        if conversation is None:
            return None
        payload = self._load_conversation_history(
            raw_history=getattr(conversation, "history", None),
            source_name="conversation_manager.current_conversation.history",
        )
        if payload is not None:
            payload["conversation_id"] = getattr(conversation, "cid", conversation_id)
            event.set_extra(
                _CURRENT_CONVERSATION_HISTORY_CACHE_EXTRA_KEY,
                {
                    "conversation_id": conversation_id,
                    "provider_request": provider_request,
                    "payload": payload,
                },
            )
        return payload

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

    @staticmethod
    def _resolve_conversation_id(
        provider_request: ProviderRequest | None,
    ) -> str | None:
        if provider_request is None or provider_request.conversation is None:
            return None
        raw_conversation_id = getattr(provider_request.conversation, "cid", None)
        if isinstance(raw_conversation_id, str) and raw_conversation_id.strip():
            return raw_conversation_id
        return None

    def _build_history_slot(
        self,
        provider_request: ProviderRequest | None,
        history_payload: dict[str, Any],
    ) -> ContextSlot:
        conversation_id = history_payload.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            conversation_id = self._resolve_conversation_id(provider_request)

        turns = history_payload["turns"]
        source_name = history_payload["source"]
        meta = {
            "format": "turn_pairs",
            "turn_count": len(turns),
        }

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
            meta=meta,
        )
