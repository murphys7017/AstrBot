from __future__ import annotations

from typing import Any

from .history_source import RecentConversationSource, extract_message_text
from .store import MemoryStore
from .types import ShortTermMemory, TopicState, TurnRecord


class ShortTermMemoryService:
    def __init__(
        self,
        store: MemoryStore,
        history_source: RecentConversationSource,
    ) -> None:
        self.store = store
        self.history_source = history_source

    async def update_topic_state(
        self,
        turn: TurnRecord,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> TopicState:
        recent_payloads = await self.history_source.get_recent_turn_payloads(
            conversation_history=conversation_history,
            umo=turn.umo,
            conversation_id=turn.conversation_id,
        )
        latest_user_text = _truncate_text(extract_message_text(turn.user_message), 80)
        latest_assistant_text = _truncate_text(
            extract_message_text(turn.assistant_message),
            100,
        )

        topic_summary_parts: list[str] = []
        if latest_user_text:
            topic_summary_parts.append(f"U: {latest_user_text}")
        if latest_assistant_text:
            topic_summary_parts.append(f"A: {latest_assistant_text}")

        if not topic_summary_parts and recent_payloads:
            topic_summary_parts.extend(
                _build_turn_summary_parts(
                    recent_payloads[-1], user_limit=80, assistant_limit=80
                )
            )

        state = TopicState(
            umo=turn.umo,
            conversation_id=turn.conversation_id,
            current_topic=latest_user_text or None,
            topic_summary=_truncate_text(" | ".join(topic_summary_parts), 220) or None,
            topic_confidence=0.85 if latest_user_text else 0.0,
            last_active_at=turn.message_timestamp,
        )
        return await self.store.upsert_topic_state(state)

    async def update_short_term_memory(
        self,
        turn: TurnRecord,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> ShortTermMemory:
        recent_payloads = await self.history_source.get_recent_turn_payloads(
            conversation_history=conversation_history,
            umo=turn.umo,
            conversation_id=turn.conversation_id,
        )
        if not recent_payloads:
            recent_payloads = [
                {
                    "user_message": turn.user_message,
                    "assistant_message": turn.assistant_message,
                }
            ]

        summary_lines: list[str] = []
        for payload in recent_payloads[-4:]:
            summary_lines.extend(
                _build_turn_summary_parts(payload, user_limit=60, assistant_limit=60)
            )

        memory = ShortTermMemory(
            umo=turn.umo,
            conversation_id=turn.conversation_id,
            short_summary=_truncate_text(" | ".join(summary_lines), 360) or None,
            active_focus=_truncate_text(extract_message_text(turn.user_message), 120)
            or None,
            updated_at=turn.message_timestamp,
        )
        return await self.store.upsert_short_term_memory(memory)

    async def update_after_turn(
        self,
        turn: TurnRecord,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> tuple[TopicState, ShortTermMemory]:
        topic_state = await self.update_topic_state(turn, conversation_history)
        short_term_memory = await self.update_short_term_memory(
            turn,
            conversation_history,
        )
        return topic_state, short_term_memory


def _build_turn_summary_parts(
    payload: dict[str, Any],
    *,
    user_limit: int,
    assistant_limit: int,
) -> list[str]:
    user_text = _truncate_text(
        extract_message_text(payload.get("user_message")),
        user_limit,
    )
    assistant_text = _truncate_text(
        extract_message_text(payload.get("assistant_message")),
        assistant_limit,
    )
    parts: list[str] = []
    if user_text:
        parts.append(f"U: {user_text}")
    if assistant_text:
        parts.append(f"A: {assistant_text}")
    return parts


def _truncate_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
