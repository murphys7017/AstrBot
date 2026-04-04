from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from astrbot.core import logger
from astrbot.core.postprocess import register_postprocessor, unregister_postprocessor
from astrbot.core.postprocess.types import PostProcessContext, PostProcessTrigger
from astrbot.core.provider.entities import LLMResponse, ProviderRequest

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
        material = _resolve_turn_material(ctx)
        if material is None:
            logger.debug(
                "memory postprocess: skip because no update material found reason=%s",
                _describe_skip_reason(ctx),
            )
            return None

        latest_turn = RecentConversationSource.get_latest_turn_payload(
            material["conversation_history"]
        )
        if latest_turn is None:
            logger.debug(
                "memory postprocess: skip because no turn pair found reason=no_turn_pair"
            )
            return None

        event = ctx.event
        provider_payload = _serialize_provider_request(ctx.provider_request)
        provider_payload["conversation_history"] = material["conversation_history"]
        if material["conversation_id"] is not None:
            provider_payload["conversation_id"] = material["conversation_id"]
        provider_payload["history_source"] = material["history_source"]

        source_refs: list[str] = []
        if material["conversation_id"] is not None:
            source_refs.append(f"conversation:{material['conversation_id']}")

        return MemoryUpdateRequest(
            umo=event.unified_msg_origin,
            conversation_id=material["conversation_id"],
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


def _resolve_turn_material(
    ctx: PostProcessContext,
) -> dict[str, Any] | None:
    current_user_message = _build_user_message_from_prompt(ctx.provider_request)
    current_assistant_message = _build_assistant_message_from_response(ctx.llm_response)

    if ctx.conversation is not None:
        conversation_history = parse_conversation_history(ctx.conversation.history)
        if (
            RecentConversationSource.get_latest_turn_payload(conversation_history)
            is not None
        ):
            return {
                "conversation_history": conversation_history,
                "conversation_id": ctx.conversation.cid,
                "history_source": "conversation.history",
            }

    provider_request = ctx.provider_request
    if provider_request is not None:
        provider_conversation = provider_request.conversation
        if provider_conversation is not None and (
            current_user_message is not None or current_assistant_message is not None
        ):
            conversation_history = _materialize_current_turn_history(
                parse_conversation_history(provider_conversation.history),
                current_user_message,
                current_assistant_message,
            )
            latest_turn = RecentConversationSource.get_latest_turn_payload(
                conversation_history
            )
            if latest_turn is not None and _is_current_turn_match(
                latest_turn,
                current_user_message,
                current_assistant_message,
            ):
                return {
                    "conversation_history": conversation_history,
                    "conversation_id": provider_conversation.cid,
                    "history_source": "provider_request.conversation.history",
                }

        provider_contexts = _extract_provider_contexts(provider_request)
        if provider_contexts and (
            current_user_message is not None or current_assistant_message is not None
        ):
            conversation_history = _materialize_current_turn_history(
                provider_contexts,
                current_user_message,
                current_assistant_message,
            )
            latest_turn = RecentConversationSource.get_latest_turn_payload(
                conversation_history
            )
            if latest_turn is not None and _is_current_turn_match(
                latest_turn,
                current_user_message,
                current_assistant_message,
            ):
                return {
                    "conversation_history": conversation_history,
                    "conversation_id": (
                        provider_conversation.cid if provider_conversation else None
                    ),
                    "history_source": "provider_request.contexts",
                }

    if current_user_message is not None and current_assistant_message is not None:
        conversation_history = [current_user_message, current_assistant_message]
        return {
            "conversation_history": conversation_history,
            "conversation_id": None,
            "history_source": "prompt_response_fallback",
        }

    return None


def _build_user_message_from_prompt(
    provider_request: ProviderRequest | None,
) -> dict[str, Any] | None:
    if provider_request is None:
        return None

    prompt = _normalize_text(provider_request.prompt)
    if not prompt:
        return None
    return {"role": "user", "content": prompt}


def _build_assistant_message_from_response(
    llm_response: LLMResponse | None,
) -> dict[str, Any] | None:
    if llm_response is None:
        return None

    completion_text = _normalize_text(llm_response.completion_text)
    if not completion_text:
        return None
    return {"role": "assistant", "content": completion_text}


def _extract_provider_contexts(
    provider_request: ProviderRequest,
) -> list[dict[str, Any]]:
    return [item for item in provider_request.contexts if isinstance(item, dict)]


def _materialize_current_turn_history(
    base_history: list[dict[str, Any]],
    current_user_message: dict[str, Any] | None,
    current_assistant_message: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    conversation_history = [
        dict(item) for item in base_history if isinstance(item, dict)
    ]

    if current_user_message is not None and not _last_message_matches(
        conversation_history,
        current_user_message,
    ):
        conversation_history.append(dict(current_user_message))

    if current_assistant_message is not None and not _last_message_matches(
        conversation_history,
        current_assistant_message,
    ):
        conversation_history.append(dict(current_assistant_message))

    return conversation_history


def _last_message_matches(
    conversation_history: list[dict[str, Any]],
    message: dict[str, Any],
) -> bool:
    if not conversation_history:
        return False

    last_message = conversation_history[-1]
    return str(last_message.get("role", "") or "") == str(
        message.get("role", "") or ""
    ) and _normalize_text(last_message.get("content")) == _normalize_text(
        message.get("content")
    )


def _is_current_turn_match(
    latest_turn: dict[str, Any],
    current_user_message: dict[str, Any] | None,
    current_assistant_message: dict[str, Any] | None,
) -> bool:
    if current_user_message is not None and _normalize_text(
        latest_turn["user_message"].get("content")
    ) != _normalize_text(current_user_message.get("content")):
        return False

    if current_assistant_message is not None and _normalize_text(
        latest_turn["assistant_message"].get("content")
    ) != _normalize_text(current_assistant_message.get("content")):
        return False

    return True


def _describe_skip_reason(ctx: PostProcessContext) -> str:
    if ctx.conversation is not None:
        return "no_turn_pair"

    if ctx.provider_request is None:
        return "conversation_unavailable_fallback_failed"

    if not _extract_provider_contexts(ctx.provider_request) and (
        ctx.provider_request.conversation is None
    ):
        if _build_assistant_message_from_response(ctx.llm_response) is None:
            return "missing_final_assistant"
        if _build_user_message_from_prompt(ctx.provider_request) is None:
            return "no_history"

    return "conversation_unavailable_fallback_failed"


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    return ""
