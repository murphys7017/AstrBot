from __future__ import annotations

import json
from typing import Any

from .analyzer_manager import MemoryAnalyzerManager
from .config import MemoryAnalysisConfig
from .history_source import RecentConversationSource, extract_message_text
from .store import MemoryStore
from .types import ShortTermMemory, TopicState, TurnRecord


class ShortTermMemoryService:
    def __init__(
        self,
        store: MemoryStore,
        history_source: RecentConversationSource,
        analyzer_manager: MemoryAnalyzerManager | None = None,
        analysis_config: MemoryAnalysisConfig | None = None,
    ) -> None:
        self.store = store
        self.history_source = history_source
        self.analyzer_manager = analyzer_manager
        self.analysis_config = analysis_config

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

        if self._should_use_analysis():
            analysis_result = await self._run_short_term_analysis(
                turn,
                recent_payloads,
            )
            state = TopicState(
                umo=turn.umo,
                conversation_id=turn.conversation_id,
                current_topic=analysis_result.get("current_topic") or None,
                topic_summary=analysis_result.get("topic_summary") or None,
                topic_confidence=_coerce_confidence(
                    analysis_result.get("topic_confidence"),
                    default=0.0,
                ),
                last_active_at=turn.message_timestamp,
            )
            return await self.store.upsert_topic_state(state)

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

        if self._should_use_analysis():
            analysis_result = await self._run_short_term_analysis(
                turn,
                recent_payloads,
            )
            memory = ShortTermMemory(
                umo=turn.umo,
                conversation_id=turn.conversation_id,
                short_summary=analysis_result.get("short_summary") or None,
                active_focus=analysis_result.get("active_focus") or None,
                updated_at=turn.message_timestamp,
            )
            return await self.store.upsert_short_term_memory(memory)

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

    def _should_use_analysis(self) -> bool:
        return bool(
            self.analysis_config is not None
            and self.analysis_config.enabled
            and self.analyzer_manager is not None
        )

    async def _run_short_term_analysis(
        self,
        turn: TurnRecord,
        recent_payloads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.analyzer_manager is None:
            raise RuntimeError("short term analysis requested without analyzer manager")

        payload = self._build_short_term_analysis_payload(turn, recent_payloads)
        results = await self.analyzer_manager.dispatch_stage(
            "short_term_update",
            payload=payload,
            umo=turn.umo,
            conversation_id=turn.conversation_id,
        )
        merged: dict[str, Any] = {}
        for result in results.values():
            merged.update(result.data)
        return merged

    def _build_short_term_analysis_payload(
        self,
        turn: TurnRecord,
        recent_payloads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        latest_user_text = extract_message_text(turn.user_message)
        latest_assistant_text = extract_message_text(turn.assistant_message)
        recent_turns = [
            {
                "user": extract_message_text(payload.get("user_message")),
                "assistant": extract_message_text(payload.get("assistant_message")),
            }
            for payload in recent_payloads
        ]
        recent_dialogue_text = "\n".join(_build_dialogue_lines(recent_turns)).strip()
        return {
            "umo": turn.umo,
            "conversation_id": turn.conversation_id or "",
            "latest_user_text": latest_user_text,
            "latest_assistant_text": latest_assistant_text,
            "recent_turns_json": json.dumps(recent_turns, ensure_ascii=False),
            "recent_dialogue_text": recent_dialogue_text,
            "recent_turns_window": str(len(recent_turns)),
        }


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


def _build_dialogue_lines(recent_turns: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for turn in recent_turns:
        if turn.get("user"):
            lines.append(f"User: {turn['user']}")
        if turn.get("assistant"):
            lines.append(f"Assistant: {turn['assistant']}")
    return lines


def _coerce_confidence(value: Any, default: float) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    return default
