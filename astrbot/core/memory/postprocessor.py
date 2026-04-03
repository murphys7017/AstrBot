from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from astrbot.core import logger
from astrbot.core.postprocess import register_postprocessor, unregister_postprocessor
from astrbot.core.postprocess.types import PostProcessContext, PostProcessTrigger
from astrbot.core.provider.entities import ProviderRequest

from .config import get_memory_config
from .history_source import RecentConversationSource, parse_conversation_history
from .service import MemoryService, get_memory_service
from .types import MemoryUpdateRequest


class MemoryPostProcessor:
    name = "memory_postprocessor"
    triggers = (PostProcessTrigger.AFTER_MESSAGE_SENT,)

    def __init__(self, memory_service: MemoryService) -> None:
        self.memory_service = memory_service

    async def build_update_request(
        self,
        ctx: PostProcessContext,
    ) -> MemoryUpdateRequest | None:
        conversation_history = parse_conversation_history(
            ctx.conversation.history if ctx.conversation else None
        )
        latest_turn = RecentConversationSource.get_latest_turn_payload(
            conversation_history
        )
        if latest_turn is None:
            return None

        event = ctx.event
        provider_payload = _serialize_provider_request(ctx.provider_request)
        provider_payload["conversation_history"] = conversation_history
        if ctx.conversation is not None:
            provider_payload["conversation_id"] = ctx.conversation.cid

        source_refs: list[str] = []
        if ctx.conversation is not None:
            source_refs.append(f"conversation:{ctx.conversation.cid}")

        return MemoryUpdateRequest(
            umo=event.unified_msg_origin,
            conversation_id=ctx.conversation.cid if ctx.conversation else None,
            platform_id=event.get_platform_id(),
            session_id=(
                ctx.provider_request.session_id if ctx.provider_request else None
            )
            or getattr(event, "session_id", None),
            provider_request=provider_payload,
            user_message=latest_turn["user_message"],
            assistant_message=latest_turn["assistant_message"],
            message_timestamp=ctx.timestamp or datetime.now(UTC),
            source_refs=source_refs,
        )

    async def run(self, ctx: PostProcessContext) -> None:
        req = await self.build_update_request(ctx)
        if req is None:
            logger.debug("memory postprocess: skip because no valid turn pair found")
            return
        await self.memory_service.update_from_postprocess(req)


_MEMORY_POSTPROCESSOR: MemoryPostProcessor | None = None


def register_memory_postprocessor(
    memory_service: MemoryService | None = None,
) -> MemoryPostProcessor | None:
    global _MEMORY_POSTPROCESSOR

    if not get_memory_config().enabled:
        return None

    resolved_memory_service = memory_service or get_memory_service()
    processor = _MEMORY_POSTPROCESSOR
    if processor is None:
        processor = MemoryPostProcessor(resolved_memory_service)
        _MEMORY_POSTPROCESSOR = processor
    else:
        processor.memory_service = resolved_memory_service

    register_postprocessor(processor)
    return processor


def unregister_memory_postprocessor() -> bool:
    if _MEMORY_POSTPROCESSOR is None:
        return False
    return unregister_postprocessor(_MEMORY_POSTPROCESSOR)


def reset_memory_postprocessor() -> bool:
    global _MEMORY_POSTPROCESSOR

    removed = unregister_memory_postprocessor()
    _MEMORY_POSTPROCESSOR = None
    return removed


def _serialize_provider_request(
    provider_request: ProviderRequest | None,
) -> dict[str, Any]:
    if provider_request is None:
        return {}

    return {
        "prompt": provider_request.prompt,
        "session_id": provider_request.session_id,
        "model": provider_request.model,
        "system_prompt": provider_request.system_prompt,
    }
