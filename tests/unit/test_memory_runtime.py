from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.core.db.po import Conversation
from astrbot.core.memory.analyzer import MemoryAnalyzerResult
from astrbot.core.memory.analyzers.base import MemoryAnalyzerExecutionError
from astrbot.core.memory.config import (
    MemoryAnalysisConfig,
    MemoryConsolidationConfig,
    MemoryLongTermConfig,
    load_memory_config,
)
from astrbot.core.memory.consolidation_service import ConsolidationService
from astrbot.core.memory.document_loader import DocumentLoader
from astrbot.core.memory.document_search import DocumentSearchService
from astrbot.core.memory.experience_service import ExperienceService
from astrbot.core.memory.history_source import (
    RecentConversationSource,
    extract_turn_payloads,
)
from astrbot.core.memory.identity import (
    MemoryIdentityMappingService,
    MemoryIdentityResolver,
)
from astrbot.core.memory.long_term_service import LongTermMemoryService
from astrbot.core.memory.manual_service import LongTermMemoryManualService
from astrbot.core.memory.postprocessor import (
    MemoryPostProcessor,
    register_memory_postprocessor,
    reset_memory_postprocessor,
)
from astrbot.core.memory.projection import ExperienceProjectionService
from astrbot.core.memory.service import MemoryService
from astrbot.core.memory.short_term_service import ShortTermMemoryService
from astrbot.core.memory.snapshot_builder import MemorySnapshotBuilder
from astrbot.core.memory.store import MemoryStore
from astrbot.core.memory.turn_record_service import TurnRecordService
from astrbot.core.memory.types import (
    DocumentSearchRequest,
    Experience,
    LongTermMemoryDocument,
    LongTermMemoryIndex,
    LongTermMemoryStatus,
    MemoryIdentity,
    MemoryUpdateRequest,
    SessionInsight,
    ShortTermMemory,
    TopicState,
)
from astrbot.core.memory.vector_index import MemoryVectorIndex
from astrbot.core.postprocess import get_postprocess_manager
from astrbot.core.provider.entities import LLMResponse, ProviderRequest

TEST_UMO = "test:private:user"
TEST_PLATFORM_ID = "test"
TEST_PLATFORM_USER_KEY = "test:user-1"
TEST_CANONICAL_USER_ID = "canonical-user-1"


def _make_history() -> list[dict]:
    return [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "We should build memory first."},
        {"role": "assistant", "content": "Let's start from data types and store."},
        {"role": "user", "content": "Then wire postprocess and snapshot."},
        {"role": "assistant", "content": "That gives us a minimal closed loop."},
    ]


def _memory_update_request(
    *,
    user_message: dict[str, object],
    assistant_message: dict[str, object],
    message_timestamp: datetime,
    conversation_id: str | None = "conv-1",
    provider_request: dict | None = None,
    source_refs: list[str] | None = None,
    canonical_user_id: str | None = TEST_CANONICAL_USER_ID,
) -> MemoryUpdateRequest:
    return MemoryUpdateRequest(
        umo=TEST_UMO,
        conversation_id=conversation_id,
        platform_id=TEST_PLATFORM_ID,
        platform_user_key=TEST_PLATFORM_USER_KEY,
        canonical_user_id=canonical_user_id,
        session_id="session-1",
        provider_request=provider_request,
        user_message=user_message,
        assistant_message=assistant_message,
        message_timestamp=message_timestamp,
        source_refs=list(source_refs or []),
    )


def _session_insight(
    *,
    insight_id: str,
    window_start_at: datetime | None,
    window_end_at: datetime | None,
    topic_summary: str,
    progress_summary: str,
    summary_text: str,
    created_at: datetime,
    conversation_id: str | None = "conv-1",
) -> SessionInsight:
    return SessionInsight(
        insight_id=insight_id,
        umo=TEST_UMO,
        conversation_id=conversation_id,
        platform_user_key=TEST_PLATFORM_USER_KEY,
        canonical_user_id=TEST_CANONICAL_USER_ID,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        topic_summary=topic_summary,
        progress_summary=progress_summary,
        summary_text=summary_text,
        created_at=created_at,
    )


def _experience(
    *,
    experience_id: str,
    scope_type: str,
    scope_id: str,
    event_time: datetime,
    category: str,
    summary: str,
    detail_summary: str | None = None,
    conversation_id: str | None = "conv-1",
    importance: float = 0.0,
    confidence: float = 0.0,
    source_refs: list[str] | None = None,
    created_at: datetime,
    updated_at: datetime,
    canonical_user_id: str = TEST_CANONICAL_USER_ID,
    platform_user_key: str = TEST_PLATFORM_USER_KEY,
    umo: str = TEST_UMO,
) -> Experience:
    return Experience(
        experience_id=experience_id,
        umo=umo,
        conversation_id=conversation_id,
        platform_user_key=platform_user_key,
        canonical_user_id=canonical_user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        event_time=event_time,
        category=category,
        summary=summary,
        detail_summary=detail_summary,
        importance=importance,
        confidence=confidence,
        source_refs=list(source_refs or []),
        created_at=created_at,
        updated_at=updated_at,
    )


def _long_term_memory_index(
    *,
    memory_id: str,
    scope_type: str,
    scope_id: str,
    category: str,
    title: str,
    summary: str,
    status: LongTermMemoryStatus | str,
    doc_path: str,
    importance: float,
    confidence: float,
    tags: list[str],
    source_refs: list[str],
    first_event_at: datetime | None = None,
    last_event_at: datetime | None = None,
    created_at: datetime,
    updated_at: datetime,
    canonical_user_id: str = TEST_CANONICAL_USER_ID,
    umo: str = TEST_UMO,
) -> LongTermMemoryIndex:
    return LongTermMemoryIndex(
        memory_id=memory_id,
        umo=umo,
        canonical_user_id=canonical_user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        category=category,
        title=title,
        summary=summary,
        status=status,
        doc_path=doc_path,
        importance=importance,
        confidence=confidence,
        tags=tags,
        source_refs=source_refs,
        first_event_at=first_event_at,
        last_event_at=last_event_at,
        created_at=created_at,
        updated_at=updated_at,
    )


def _document_search_request(
    *,
    query: str,
    top_k: int = 5,
    include_body: bool = False,
    conversation_id: str | None = "conv-1",
    scope_type: str | None = None,
    scope_id: str | None = None,
    category: str | None = None,
) -> DocumentSearchRequest:
    return DocumentSearchRequest(
        canonical_user_id=TEST_CANONICAL_USER_ID,
        query=query,
        umo=TEST_UMO,
        conversation_id=conversation_id,
        scope_type=scope_type,
        scope_id=scope_id,
        category=category,
        top_k=top_k,
        include_body=include_body,
    )


def _memory_identity(
    *,
    canonical_user_id: str | None = TEST_CANONICAL_USER_ID,
) -> MemoryIdentity:
    return MemoryIdentity(
        umo=TEST_UMO,
        platform_id=TEST_PLATFORM_ID,
        sender_user_id="user-1",
        sender_nickname="tester",
        platform_user_key=TEST_PLATFORM_USER_KEY,
        canonical_user_id=canonical_user_id,
    )


def test_extract_turn_payloads_handles_tool_use_final_assistant():
    payloads = extract_turn_payloads(
        [
            {"role": "user", "content": "Search the docs."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-1", "type": "function"}],
            },
            {"role": "tool", "content": "Found relevant files."},
            {"role": "assistant", "content": "I found the matching docs."},
        ]
    )

    assert len(payloads) == 1
    assert payloads[0]["assistant_message"]["content"] == "I found the matching docs."


def test_extract_turn_payloads_handles_multiple_tool_rounds():
    payloads = extract_turn_payloads(
        [
            {"role": "user", "content": "Run the workflow."},
            {
                "role": "assistant",
                "content": "Let me inspect first.",
                "tool_calls": [{"id": "call-1", "type": "function"}],
            },
            {"role": "tool", "content": "Step one complete."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-2", "type": "function"}],
            },
            {"role": "tool", "content": "Step two complete."},
            {"role": "assistant", "content": "Everything is done now."},
        ]
    )

    assert len(payloads) == 1
    assert payloads[0]["assistant_message"]["content"] == "Everything is done now."


def test_extract_turn_payloads_falls_back_to_tool_call_placeholder_when_no_final_reply():
    payloads = extract_turn_payloads(
        [
            {"role": "user", "content": "Call the tool only."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-1", "type": "function"}],
            },
            {"role": "tool", "content": "Tool finished."},
        ]
    )

    assert len(payloads) == 1
    assert payloads[0]["assistant_message"]["content"] == "[tool_call]"


def test_extract_turn_payloads_ignores_malformed_messages_without_crashing():
    payloads = extract_turn_payloads(
        [
            {"role": "system", "content": "init"},
            "not-a-dict",
            {"role": "user", "content": "Need a summary."},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "Here is the summary."},
            {"role": "user", "content": "Second turn."},
            {"role": "tool", "content": "orphan tool"},
        ]
    )

    assert len(payloads) == 1
    assert payloads[0]["assistant_message"]["content"] == "Here is the summary."


@pytest.mark.asyncio
async def test_turn_record_service_builds_and_persists_turn(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    service = TurnRecordService(store)
    req = _memory_update_request(
        user_message={"role": "user", "content": "hello"},
        assistant_message={"role": "assistant", "content": "hi"},
        message_timestamp=datetime.now(UTC),
        source_refs=["conversation:conv-1"],
    )

    try:
        turn = await service.ingest_turn(req)
        loaded = await store.get_turn_record(turn.turn_id)
    finally:
        await store.close()

    assert turn.turn_id
    assert loaded is not None
    assert loaded.user_message["content"] == "hello"
    assert loaded.assistant_message["content"] == "hi"


@pytest.mark.asyncio
async def test_short_term_memory_service_updates_from_history(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    history_source = RecentConversationSource(store, recent_turns_window=8)
    turn_record_service = TurnRecordService(store)
    short_term_service = ShortTermMemoryService(store, history_source)
    history = _make_history()
    req = _memory_update_request(
        provider_request={"conversation_history": history},
        user_message=history[-2],
        assistant_message=history[-1],
        message_timestamp=datetime.now(UTC),
        source_refs=["conversation:conv-1"],
    )

    try:
        turn = await turn_record_service.ingest_turn(req)
        topic_state, short_term_memory = await short_term_service.update_after_turn(
            turn,
            conversation_history=history,
        )
    finally:
        await store.close()

    assert topic_state.current_topic == "Then wire postprocess and snapshot."
    assert topic_state.topic_summary is not None
    assert short_term_memory.active_focus == "Then wire postprocess and snapshot."
    assert short_term_memory.short_summary is not None
    assert "minimal closed loop" in short_term_memory.short_summary


class StubShortTermAnalyzerManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        self.calls.append(
            {
                "stage": stage,
                "payload": payload,
                "umo": umo,
                "conversation_id": conversation_id,
            }
        )
        return {
            "topic_v1": MemoryAnalyzerResult(
                analyzer_name="topic_v1",
                stage=stage,
                data={
                    "current_topic": "Analyzer topic",
                    "topic_summary": "Analyzer topic summary",
                    "topic_confidence": 0.92,
                },
                raw_text="{}",
                provider_id="memory-lite",
                model="dummy-model",
            ),
            "focus_v1": MemoryAnalyzerResult(
                analyzer_name="focus_v1",
                stage=stage,
                data={
                    "active_focus": "Analyzer focus",
                },
                raw_text="{}",
                provider_id="memory-lite",
                model="dummy-model",
            ),
            "summary_v1": MemoryAnalyzerResult(
                analyzer_name="summary_v1",
                stage=stage,
                data={
                    "short_summary": "Analyzer short summary",
                },
                raw_text="{}",
                provider_id="memory-lite",
                model="dummy-model",
            ),
        }


class InvalidShortTermAnalyzerManager:
    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del payload, umo, conversation_id
        return {
            "topic_v1": MemoryAnalyzerResult(
                analyzer_name="topic_v1",
                stage=stage,
                data={
                    "current_topic": "Analyzer topic",
                    "topic_summary": "Analyzer topic summary",
                    "topic_confidence": "high",
                },
                raw_text="{}",
                provider_id="memory-lite",
                model="dummy-model",
            ),
            "focus_v1": MemoryAnalyzerResult(
                analyzer_name="focus_v1",
                stage=stage,
                data={},
                raw_text="{}",
                provider_id="memory-lite",
                model="dummy-model",
            ),
            "summary_v1": MemoryAnalyzerResult(
                analyzer_name="summary_v1",
                stage=stage,
                data={
                    "short_summary": "Analyzer short summary",
                },
                raw_text="{}",
                provider_id="memory-lite",
                model="dummy-model",
            ),
        }


class StubConsolidationAnalyzerManager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del payload, umo, conversation_id
        self.calls.append(stage)
        if stage == "session_insight_update":
            return {
                "session_insight_v1": MemoryAnalyzerResult(
                    analyzer_name="session_insight_v1",
                    stage=stage,
                    data={
                        "topic_summary": "Session topic summary",
                        "progress_summary": "Session progress summary",
                        "summary_text": "Session insight overall summary",
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        if stage == "experience_extract":
            return {
                "experience_extract_v1": MemoryAnalyzerResult(
                    analyzer_name="experience_extract_v1",
                    stage=stage,
                    data={
                        "experiences": [
                            {
                                "category": "project_progress",
                                "summary": "Progress moved forward",
                                "detail_summary": "The implementation advanced after discussion.",
                                "importance": 0.82,
                                "confidence": 0.91,
                            },
                            {
                                "category": "episodic_event",
                                "summary": "A memory milestone was reached",
                                "detail_summary": "The team completed the short-term memory phase.",
                                "importance": 0.75,
                                "confidence": 0.88,
                            },
                        ]
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class InvalidConsolidationAnalyzerManager:
    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del payload, umo, conversation_id
        if stage == "session_insight_update":
            return {
                "session_insight_v1": MemoryAnalyzerResult(
                    analyzer_name="session_insight_v1",
                    stage=stage,
                    data={
                        "topic_summary": "Session topic summary",
                        "progress_summary": "Session progress summary",
                        "summary_text": "Session insight overall summary",
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        if stage == "experience_extract":
            return {
                "experience_extract_v1": MemoryAnalyzerResult(
                    analyzer_name="experience_extract_v1",
                    stage=stage,
                    data={
                        "experiences": [
                            {
                                "category": "unknown_type",
                                "summary": "Bad category",
                                "importance": 0.5,
                                "confidence": 0.5,
                            }
                        ]
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class StubLongTermAnalyzerManager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del umo, conversation_id
        self.calls.append(stage)
        if stage == "long_term_promote":
            pending_raw = payload.get("pending_experiences_json")
            pending_experiences = (
                json.loads(pending_raw) if isinstance(pending_raw, str) else []
            )
            experience_ids = [
                str(item.get("experience_id"))
                for item in pending_experiences
                if isinstance(item, dict) and str(item.get("experience_id"))
            ]
            return {
                "long_term_promote_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_promote_v1",
                    stage=stage,
                    data={
                        "actions": [
                            {
                                "action": "create",
                                "target_memory_id": "",
                                "category": "project_progress",
                                "reason": "A stable project preference emerged.",
                                "experience_ids": experience_ids,
                            }
                        ]
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        if stage == "long_term_compose":
            return {
                "long_term_compose_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_compose_v1",
                    stage=stage,
                    data={
                        "title": "Memory-first implementation preference",
                        "summary": "The user prefers landing memory infrastructure early.",
                        "detail_summary": "The recent experiences show repeated preference for memory-first sequencing and infrastructure work.",
                        "tags": ["memory", "planning"],
                        "importance": 0.87,
                        "confidence": 0.9,
                        "status": "active",
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class InvalidLongTermAnalyzerManager:
    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del payload, umo, conversation_id
        if stage == "long_term_promote":
            return {
                "long_term_promote_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_promote_v1",
                    stage=stage,
                    data={"actions": [{"action": "create"}]},
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class OutOfRangeLongTermAnalyzerManager:
    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del payload, umo, conversation_id
        if stage == "long_term_promote":
            return {
                "long_term_promote_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_promote_v1",
                    stage=stage,
                    data={
                        "actions": [
                            {
                                "action": "create",
                                "target_memory_id": "",
                                "category": "project_progress",
                                "reason": "Create a memory for the new experience.",
                                "experience_ids": ["exp-1"],
                            }
                        ]
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        if stage == "long_term_compose":
            return {
                "long_term_compose_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_compose_v1",
                    stage=stage,
                    data={
                        "title": "Out of range memory",
                        "summary": "The score is invalid.",
                        "detail_summary": "The analyzer returned a score above one.",
                        "tags": ["invalid"],
                        "importance": 1.2,
                        "confidence": 0.9,
                        "status": "active",
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class MissingCoverageLongTermAnalyzerManager:
    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del umo, conversation_id
        if stage == "long_term_promote":
            pending_raw = payload.get("pending_experiences_json")
            pending_experiences = (
                json.loads(pending_raw) if isinstance(pending_raw, str) else []
            )
            first_experience_id = ""
            if pending_experiences and isinstance(pending_experiences[0], dict):
                first_experience_id = str(
                    pending_experiences[0].get("experience_id", "")
                ).strip()
            return {
                "long_term_promote_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_promote_v1",
                    stage=stage,
                    data={
                        "actions": [
                            {
                                "action": "ignore",
                                "target_memory_id": "",
                                "category": "project_progress",
                                "reason": "Ignore only the first experience.",
                                "experience_ids": [first_experience_id],
                            }
                        ]
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class DuplicateCoverageLongTermAnalyzerManager:
    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del umo, conversation_id
        if stage == "long_term_promote":
            pending_raw = payload.get("pending_experiences_json")
            pending_experiences = (
                json.loads(pending_raw) if isinstance(pending_raw, str) else []
            )
            experience_ids = [
                str(item.get("experience_id"))
                for item in pending_experiences
                if isinstance(item, dict) and str(item.get("experience_id"))
            ]
            return {
                "long_term_promote_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_promote_v1",
                    stage=stage,
                    data={
                        "actions": [
                            {
                                "action": "ignore",
                                "target_memory_id": "",
                                "category": "project_progress",
                                "reason": "Ignore the experiences once.",
                                "experience_ids": experience_ids,
                            },
                            {
                                "action": "create",
                                "target_memory_id": "",
                                "category": "project_progress",
                                "reason": "Create with the same experiences again.",
                                "experience_ids": experience_ids,
                            },
                        ]
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class DuplicateUpdateTargetLongTermAnalyzerManager:
    def __init__(self, memory_id: str) -> None:
        self.memory_id = memory_id

    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del umo, conversation_id
        if stage == "long_term_promote":
            pending_raw = payload.get("pending_experiences_json")
            pending_experiences = (
                json.loads(pending_raw) if isinstance(pending_raw, str) else []
            )
            experience_ids = [
                str(item.get("experience_id"))
                for item in pending_experiences
                if isinstance(item, dict) and str(item.get("experience_id"))
            ]
            return {
                "long_term_promote_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_promote_v1",
                    stage=stage,
                    data={
                        "actions": [
                            {
                                "action": "update",
                                "target_memory_id": self.memory_id,
                                "category": "project_progress",
                                "reason": "Apply first update.",
                                "experience_ids": [experience_ids[0]],
                            },
                            {
                                "action": "update",
                                "target_memory_id": self.memory_id,
                                "category": "project_progress",
                                "reason": "Apply second update to same memory.",
                                "experience_ids": [experience_ids[1]],
                            },
                        ]
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class StubLongTermUpdateAnalyzerManager:
    def __init__(self, memory_id: str) -> None:
        self.memory_id = memory_id
        self.calls: list[str] = []

    async def dispatch_stage(
        self,
        stage: str,
        *,
        payload: dict[str, object],
        umo: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, MemoryAnalyzerResult]:
        del umo, conversation_id
        self.calls.append(stage)
        if stage == "long_term_promote":
            pending_raw = payload.get("pending_experiences_json")
            pending_experiences = (
                json.loads(pending_raw) if isinstance(pending_raw, str) else []
            )
            experience_ids = [
                str(item.get("experience_id"))
                for item in pending_experiences
                if isinstance(item, dict) and str(item.get("experience_id"))
            ]
            return {
                "long_term_promote_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_promote_v1",
                    stage=stage,
                    data={
                        "actions": [
                            {
                                "action": "update",
                                "target_memory_id": self.memory_id,
                                "category": "project_progress",
                                "reason": "The existing long-term memory received new support.",
                                "experience_ids": experience_ids,
                            }
                        ]
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        if stage == "long_term_compose":
            return {
                "long_term_compose_v1": MemoryAnalyzerResult(
                    analyzer_name="long_term_compose_v1",
                    stage=stage,
                    data={
                        "title": "Updated memory-first implementation preference",
                        "summary": "The user still prefers memory-first implementation, now reinforced by new experiences.",
                        "detail_summary": "New experiences reinforced the existing memory and updated the detail summary.",
                        "tags": ["memory", "planning", "update"],
                        "importance": 0.9,
                        "confidence": 0.94,
                        "status": "active",
                    },
                    raw_text="{}",
                    provider_id="memory-lite",
                    model="dummy-model",
                )
            }
        raise AssertionError(f"Unexpected stage: {stage}")


class StubVectorIndex:
    def __init__(self, hits: list[tuple[str, float]]) -> None:
        self.hits = hits
        self.calls: list[dict[str, object]] = []
        self.config = MagicMock()

    async def search_long_term_memories(
        self,
        umo: str,
        query: str,
        top_k: int,
        metadata_filters: dict | None = None,
    ):
        self.calls.append(
            {
                "umo": umo,
                "query": query,
                "top_k": top_k,
                "metadata_filters": metadata_filters,
            }
        )
        return [
            MagicMock(memory_id=memory_id, score=score, metadata={})
            for memory_id, score in self.hits
        ]


class StubManualVectorIndex:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ensure_ready(self) -> None:
        return None

    async def upsert_long_term_memory(self, memory_id: str) -> None:
        self.calls.append(memory_id)


class FailingManualVectorIndex:
    async def ensure_ready(self) -> None:
        return None

    async def upsert_long_term_memory(self, memory_id: str) -> None:
        del memory_id
        raise RuntimeError("manual vector refresh failed")


class FailingDocumentLoader(DocumentLoader):
    def prepare_long_term_document_write(
        self,
        document: LongTermMemoryDocument,
        doc_path: Path | str | None = None,
    ):
        del document, doc_path
        raise RuntimeError("long-term markdown write failed")


class FailingProjectionService:
    async def refresh_for_experiences(self, experiences):  # noqa: ANN001
        del experiences
        raise RuntimeError("projection write failed")

    async def refresh_scope_projection(
        self,
        umo: str,
        scope_type: str,
        scope_id: str,
    ):
        del umo, scope_type, scope_id
        raise RuntimeError("projection write failed")


@pytest.mark.asyncio
async def test_short_term_memory_service_uses_analyzer_when_enabled(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    history_source = RecentConversationSource(store, recent_turns_window=8)
    analyzer_manager = StubShortTermAnalyzerManager()
    short_term_service = ShortTermMemoryService(
        store,
        history_source,
        analyzer_manager=analyzer_manager,  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True),
    )
    turn_record_service = TurnRecordService(store)
    history = _make_history()
    req = _memory_update_request(
        provider_request={"conversation_history": history},
        user_message=history[-2],
        assistant_message=history[-1],
        message_timestamp=datetime.now(UTC),
        source_refs=["conversation:conv-1"],
    )

    try:
        turn = await turn_record_service.ingest_turn(req)
        topic_state, short_term_memory = await short_term_service.update_after_turn(
            turn,
            conversation_history=history,
        )
    finally:
        await store.close()

    assert analyzer_manager.calls
    assert analyzer_manager.calls[0]["stage"] == "short_term_update"
    assert topic_state.current_topic == "Analyzer topic"
    assert topic_state.topic_summary == "Analyzer topic summary"
    assert topic_state.topic_confidence == 0.92
    assert short_term_memory.short_summary == "Analyzer short summary"
    assert short_term_memory.active_focus == "Analyzer focus"


@pytest.mark.asyncio
async def test_short_term_memory_service_raises_on_invalid_analyzer_payload(
    temp_dir: Path,
):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    history_source = RecentConversationSource(store, recent_turns_window=8)
    short_term_service = ShortTermMemoryService(
        store,
        history_source,
        analyzer_manager=InvalidShortTermAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
    )
    turn_record_service = TurnRecordService(store)
    history = _make_history()
    req = _memory_update_request(
        provider_request={"conversation_history": history},
        user_message=history[-2],
        assistant_message=history[-1],
        message_timestamp=datetime.now(UTC),
        source_refs=["conversation:conv-1"],
    )

    try:
        turn = await turn_record_service.ingest_turn(req)
        with pytest.raises(MemoryAnalyzerExecutionError):
            await short_term_service.update_after_turn(
                turn,
                conversation_history=history,
            )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_memory_service_update_and_snapshot_form_closed_loop(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    history_source = RecentConversationSource(store, recent_turns_window=8)
    turn_record_service = TurnRecordService(store)
    short_term_service = ShortTermMemoryService(store, history_source)
    snapshot_builder = MemorySnapshotBuilder(store)
    memory_service = MemoryService(
        store,
        turn_record_service,
        short_term_service,
        snapshot_builder,
    )
    history = _make_history()
    req = _memory_update_request(
        provider_request={"conversation_history": history},
        user_message=history[-2],
        assistant_message=history[-1],
        message_timestamp=datetime.now(UTC),
        source_refs=["conversation:conv-1"],
    )

    try:
        snapshot_before = await memory_service.get_snapshot(
            "test:private:user", "conv-1"
        )
        await memory_service.update_from_postprocess(req)
        snapshot_after = await memory_service.get_snapshot(
            "test:private:user", "conv-1"
        )
    finally:
        await store.close()

    assert snapshot_before.topic_state is None
    assert snapshot_before.short_term_memory is None
    assert snapshot_after.topic_state is not None
    assert snapshot_after.short_term_memory is not None
    assert snapshot_after.experiences == []
    assert snapshot_after.long_term_memories == []
    assert snapshot_after.persona_state is None
    assert snapshot_after.debug_meta == {}


@pytest.mark.asyncio
async def test_memory_service_snapshot_keeps_query_as_debug_meta(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    snapshot_builder = MemorySnapshotBuilder(store)
    memory_service = MemoryService(
        store,
        TurnRecordService(store),
        ShortTermMemoryService(store, RecentConversationSource(store)),
        snapshot_builder,
    )

    try:
        snapshot = await memory_service.get_snapshot(
            "test:private:user",
            "conv-1",
            query="memory lookup query",
        )
    finally:
        await store.close()

    assert snapshot.debug_meta == {"query": "memory lookup query"}


@pytest.mark.asyncio
async def test_memory_identity_resolver_uses_event_and_mapping(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    mapping_service = MemoryIdentityMappingService(store)
    resolver = MemoryIdentityResolver(mapping_service)
    event = MagicMock()
    event.unified_msg_origin = TEST_UMO
    event.get_platform_id.return_value = TEST_PLATFORM_ID
    event.get_sender_id.return_value = "user-1"
    event.get_sender_name.return_value = "tester"

    try:
        await mapping_service.bind_platform_user(
            TEST_PLATFORM_ID,
            "user-1",
            TEST_CANONICAL_USER_ID,
            nickname_hint="tester",
        )
        identity = await resolver.resolve_from_event(event)
    finally:
        await store.close()

    assert identity.umo == TEST_UMO
    assert identity.platform_user_key == TEST_PLATFORM_USER_KEY
    assert identity.canonical_user_id == TEST_CANONICAL_USER_ID
    assert identity.sender_nickname == "tester"


@pytest.mark.asyncio
async def test_memory_service_update_skips_mid_long_when_canonical_user_missing(
    temp_dir: Path,
):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    history_source = RecentConversationSource(store, recent_turns_window=8)
    turn_record_service = TurnRecordService(store)
    short_term_service = ShortTermMemoryService(store, history_source)
    consolidation_service = ConsolidationService(
        store,
        analyzer_manager=StubConsolidationAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        consolidation_config=MemoryConsolidationConfig(
            enabled=True,
            min_short_term_updates=1,
        ),
    )
    memory_service = MemoryService(
        store,
        turn_record_service,
        short_term_service,
        MemorySnapshotBuilder(store),
        consolidation_service=consolidation_service,
        experience_service=ExperienceService(store),
    )
    history = _make_history()

    try:
        turn = await memory_service.update_from_postprocess(
            _memory_update_request(
                provider_request={"conversation_history": history},
                user_message=history[-2],
                assistant_message=history[-1],
                message_timestamp=datetime.now(UTC),
                source_refs=["conversation:conv-1"],
                canonical_user_id=None,
            )
        )
        snapshot = await memory_service.get_snapshot(TEST_UMO, "conv-1")
        latest_insight = await store.get_latest_session_insight(
            TEST_CANONICAL_USER_ID,
            "conv-1",
        )
        experiences = await store.list_recent_experiences(TEST_CANONICAL_USER_ID, 10)
    finally:
        await store.close()

    assert turn.canonical_user_id is None
    assert snapshot.short_term_memory is not None
    assert snapshot.canonical_user_id is None
    assert latest_insight is None
    assert experiences == []


@pytest.mark.asyncio
async def test_consolidation_service_runs_when_pending_turns_reach_threshold(
    temp_dir: Path,
):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    analyzer_manager = StubConsolidationAnalyzerManager()
    consolidation_service = ConsolidationService(
        store,
        analyzer_manager=analyzer_manager,  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        consolidation_config=MemoryConsolidationConfig(
            enabled=True,
            min_short_term_updates=2,
        ),
    )
    turn_record_service = TurnRecordService(store)
    now = datetime.now(UTC)

    try:
        first_turn = await turn_record_service.ingest_turn(
            _memory_update_request(
                user_message={"role": "user", "content": "First turn"},
                assistant_message={"role": "assistant", "content": "First reply"},
                message_timestamp=now,
                source_refs=[],
            )
        )
        second_turn = await turn_record_service.ingest_turn(
            _memory_update_request(
                user_message={"role": "user", "content": "Second turn"},
                assistant_message={"role": "assistant", "content": "Second reply"},
                message_timestamp=now + timedelta(microseconds=1),
                source_refs=[],
            )
        )
        await store.upsert_topic_state(
            TopicState(
                umo="test:private:user",
                conversation_id="conv-1",
                current_topic="Memory work",
                topic_summary="Working on memory consolidation",
                topic_confidence=0.9,
                last_active_at=second_turn.message_timestamp,
            )
        )
        await store.upsert_short_term_memory(
            ShortTermMemory(
                umo="test:private:user",
                conversation_id="conv-1",
                short_summary="Two turns happened",
                active_focus="Consolidate them",
                updated_at=second_turn.message_timestamp,
            )
        )

        should_run = await consolidation_service.should_run_consolidation(
            TEST_CANONICAL_USER_ID,
            "conv-1",
        )
        insight, experiences = await consolidation_service.run_for_scope(
            TEST_CANONICAL_USER_ID,
            "conv-1",
        )
    finally:
        await store.close()

    assert first_turn.turn_id
    assert should_run is True
    assert analyzer_manager.calls == ["session_insight_update", "experience_extract"]
    assert insight is not None
    assert insight.topic_summary == "Session topic summary"
    assert len(experiences) == 2
    assert experiences[0].scope_id == TEST_CANONICAL_USER_ID
    assert experiences[0].source_refs[-1].startswith("insight:")


@pytest.mark.asyncio
async def test_consolidation_service_only_counts_turns_after_latest_insight(
    temp_dir: Path,
):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    consolidation_service = ConsolidationService(
        store,
        analyzer_manager=StubConsolidationAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        consolidation_config=MemoryConsolidationConfig(
            enabled=True,
            min_short_term_updates=2,
        ),
    )
    turn_record_service = TurnRecordService(store)
    now = datetime.now(UTC)

    try:
        await turn_record_service.ingest_turn(
            _memory_update_request(
                user_message={"role": "user", "content": "Old turn"},
                assistant_message={"role": "assistant", "content": "Old reply"},
                message_timestamp=now,
                source_refs=[],
            )
        )
        await store.save_session_insight(
            _session_insight(
                insight_id="insight-1",
                window_start_at=now,
                window_end_at=now,
                topic_summary="Old insight",
                progress_summary="Old progress",
                summary_text="Old summary",
                created_at=now,
            )
        )
        await turn_record_service.ingest_turn(
            _memory_update_request(
                user_message={"role": "user", "content": "New turn 1"},
                assistant_message={"role": "assistant", "content": "New reply 1"},
                message_timestamp=now + timedelta(microseconds=1),
                source_refs=[],
            )
        )
        await turn_record_service.ingest_turn(
            _memory_update_request(
                user_message={"role": "user", "content": "New turn 2"},
                assistant_message={"role": "assistant", "content": "New reply 2"},
                message_timestamp=now + timedelta(microseconds=2),
                source_refs=[],
            )
        )

        should_run = await consolidation_service.should_run_consolidation(
            TEST_CANONICAL_USER_ID,
            "conv-1",
        )
    finally:
        await store.close()

    assert should_run is True


@pytest.mark.asyncio
async def test_memory_service_update_triggers_and_persists_consolidation(
    temp_dir: Path,
):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    history_source = RecentConversationSource(store, recent_turns_window=8)
    turn_record_service = TurnRecordService(store)
    short_term_service = ShortTermMemoryService(store, history_source)
    analyzer_manager = StubConsolidationAnalyzerManager()
    consolidation_service = ConsolidationService(
        store,
        analyzer_manager=analyzer_manager,  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        consolidation_config=MemoryConsolidationConfig(
            enabled=True,
            min_short_term_updates=2,
        ),
    )
    experience_service = ExperienceService(store)
    memory_service = MemoryService(
        store,
        turn_record_service,
        short_term_service,
        MemorySnapshotBuilder(store),
        consolidation_service=consolidation_service,
        experience_service=experience_service,
    )
    now = datetime.now(UTC)

    try:
        for index in range(2):
            await memory_service.update_from_postprocess(
                _memory_update_request(
                    user_message={"role": "user", "content": f"Turn {index}"},
                    assistant_message={
                        "role": "assistant",
                        "content": f"Reply {index}",
                    },
                    message_timestamp=now + timedelta(microseconds=index),
                    source_refs=[],
                )
            )

        latest_insight = await store.get_latest_session_insight(
            TEST_CANONICAL_USER_ID,
            "conv-1",
        )
        experiences = await store.list_recent_experiences(TEST_CANONICAL_USER_ID, 10)
        snapshot = await memory_service.get_snapshot(TEST_UMO, "conv-1")
    finally:
        await store.close()

    assert analyzer_manager.calls == ["session_insight_update", "experience_extract"]
    assert latest_insight is not None
    assert len(experiences) == 2
    assert snapshot.experiences == []


@pytest.mark.asyncio
async def test_memory_service_update_triggers_long_term_promotion_after_consolidation(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    history_source = RecentConversationSource(store, recent_turns_window=8)
    turn_record_service = TurnRecordService(store)
    short_term_service = ShortTermMemoryService(store, history_source)
    consolidation_service = ConsolidationService(
        store,
        analyzer_manager=StubConsolidationAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        consolidation_config=MemoryConsolidationConfig(
            enabled=True,
            min_short_term_updates=2,
        ),
    )
    long_term_analyzer = StubLongTermAnalyzerManager()
    long_term_service = LongTermMemoryService(
        store,
        analyzer_manager=long_term_analyzer,  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        long_term_config=MemoryLongTermConfig(
            enabled=True,
            docs_dir=config.storage.docs_root,
            min_experience_importance=0.7,
            min_pending_experiences=2,
        ),
    )
    memory_service = MemoryService(
        store,
        turn_record_service,
        short_term_service,
        MemorySnapshotBuilder(store),
        consolidation_service=consolidation_service,
        experience_service=ExperienceService(store),
        long_term_service=long_term_service,
    )
    now = datetime.now(UTC)

    try:
        for index in range(2):
            await memory_service.update_from_postprocess(
                _memory_update_request(
                    user_message={"role": "user", "content": f"Turn {index}"},
                    assistant_message={
                        "role": "assistant",
                        "content": f"Reply {index}",
                    },
                    message_timestamp=now + timedelta(microseconds=index),
                    source_refs=[],
                )
            )
        memories = await store.list_long_term_memory_indexes(
            TEST_CANONICAL_USER_ID,
            10,
            scope_type="user",
            scope_id=TEST_CANONICAL_USER_ID,
        )
    finally:
        await store.close()

    assert long_term_analyzer.calls == ["long_term_promote", "long_term_compose"]
    assert len(memories) == 1


@pytest.mark.asyncio
async def test_memory_service_keeps_database_results_when_projection_refresh_fails(
    temp_dir: Path,
):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    history_source = RecentConversationSource(store, recent_turns_window=8)
    turn_record_service = TurnRecordService(store)
    short_term_service = ShortTermMemoryService(store, history_source)
    analyzer_manager = StubConsolidationAnalyzerManager()
    consolidation_service = ConsolidationService(
        store,
        analyzer_manager=analyzer_manager,  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        consolidation_config=MemoryConsolidationConfig(
            enabled=True,
            min_short_term_updates=2,
        ),
    )
    experience_service = ExperienceService(
        store,
        projection_service=FailingProjectionService(),  # type: ignore[arg-type]
    )
    memory_service = MemoryService(
        store,
        turn_record_service,
        short_term_service,
        MemorySnapshotBuilder(store),
        consolidation_service=consolidation_service,
        experience_service=experience_service,
    )
    now = datetime.now(UTC)

    try:
        for index in range(2):
            await memory_service.update_from_postprocess(
                _memory_update_request(
                    user_message={"role": "user", "content": f"Turn {index}"},
                    assistant_message={
                        "role": "assistant",
                        "content": f"Reply {index}",
                    },
                    message_timestamp=now + timedelta(microseconds=index),
                    source_refs=[],
                )
            )

        latest_insight = await store.get_latest_session_insight(
            TEST_CANONICAL_USER_ID,
            "conv-1",
        )
        experiences = await store.list_recent_experiences(
            TEST_CANONICAL_USER_ID,
            10,
            conversation_id="conv-1",
        )
        snapshot = await memory_service.get_snapshot(TEST_UMO, "conv-1")
    finally:
        await store.close()

    assert latest_insight is not None
    assert len(experiences) == 2
    assert snapshot.experiences == []


@pytest.mark.asyncio
async def test_memory_service_keeps_short_term_when_consolidation_fails(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    history_source = RecentConversationSource(store, recent_turns_window=8)
    turn_record_service = TurnRecordService(store)
    short_term_service = ShortTermMemoryService(store, history_source)
    consolidation_service = ConsolidationService(
        store,
        analyzer_manager=InvalidConsolidationAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        consolidation_config=MemoryConsolidationConfig(
            enabled=True,
            min_short_term_updates=1,
        ),
    )
    memory_service = MemoryService(
        store,
        turn_record_service,
        short_term_service,
        MemorySnapshotBuilder(store),
        consolidation_service=consolidation_service,
        experience_service=ExperienceService(store),
    )
    now = datetime.now(UTC)

    try:
        with pytest.raises(MemoryAnalyzerExecutionError):
            await memory_service.update_from_postprocess(
                _memory_update_request(
                    user_message={"role": "user", "content": "Trigger consolidation"},
                    assistant_message={"role": "assistant", "content": "Reply"},
                    message_timestamp=now,
                    source_refs=[],
                )
            )
        snapshot = await memory_service.get_snapshot(TEST_UMO, "conv-1")
        experiences = await store.list_recent_experiences(TEST_CANONICAL_USER_ID, 10)
    finally:
        await store.close()

    assert snapshot.topic_state is not None
    assert snapshot.short_term_memory is not None
    assert experiences == []


@pytest.mark.asyncio
async def test_long_term_service_creates_memory_document_links_and_cursor(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    vector_root = (temp_dir / "vector_index").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
                f'  root_dir: "{vector_root}"',
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    analyzer_manager = StubLongTermAnalyzerManager()
    long_term_service = LongTermMemoryService(
        store,
        analyzer_manager=analyzer_manager,  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        long_term_config=MemoryLongTermConfig(
            enabled=True,
            docs_dir=config.storage.docs_root,
            min_experience_importance=0.7,
            min_pending_experiences=2,
        ),
    )
    now = datetime.now(UTC)

    try:
        await store.save_experience(
            _experience(
                experience_id="exp-1",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                event_time=now,
                category="project_progress",
                summary="Implemented memory postprocess integration",
                detail_summary="The memory pipeline was integrated after message send.",
                importance=0.82,
                confidence=0.91,
                source_refs=["turn:1"],
                created_at=now,
                updated_at=now,
            )
        )
        await store.save_experience(
            _experience(
                experience_id="exp-2",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                event_time=now + timedelta(seconds=1),
                category="project_progress",
                summary="Settled on memory-first roadmap",
                detail_summary="The team aligned around shipping memory before prompt integration.",
                importance=0.88,
                confidence=0.93,
                source_refs=["turn:2"],
                created_at=now + timedelta(microseconds=1),
                updated_at=now + timedelta(microseconds=1),
            )
        )

        should_run = await long_term_service.should_run_promotion(
            TEST_CANONICAL_USER_ID,
        )
        persisted = await long_term_service.run_promotion(
            TEST_CANONICAL_USER_ID,
        )
        links = await store.list_long_term_memory_links(persisted[0].memory_id)
        cursor = await store.get_long_term_promotion_cursor(
            TEST_CANONICAL_USER_ID,
            "user",
            TEST_CANONICAL_USER_ID,
        )
    finally:
        await store.close()

    assert should_run is True
    assert analyzer_manager.calls == ["long_term_promote", "long_term_compose"]
    assert len(persisted) == 1
    assert persisted[0].title == "Memory-first implementation preference"
    assert persisted[0].status == LongTermMemoryStatus.ACTIVE.value
    assert Path(persisted[0].doc_path).exists()
    content = Path(persisted[0].doc_path).read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "# Memory-first implementation preference" in content
    assert "## Supporting Experiences" in content
    assert len(links) == 2
    assert cursor is not None
    assert cursor.last_processed_experience_id == "exp-2"


@pytest.mark.asyncio
async def test_long_term_service_rolls_back_markdown_when_db_commit_fails(
    temp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    analyzer_manager = StubLongTermAnalyzerManager()
    service = LongTermMemoryService(
        store,
        analyzer_manager=analyzer_manager,  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        long_term_config=MemoryLongTermConfig(
            enabled=True,
            docs_dir=config.storage.docs_root,
            min_experience_importance=0.7,
            min_pending_experiences=1,
        ),
    )
    now = datetime.now(UTC)

    async def failing_persist_batch(memories, links, cursor):  # noqa: ANN001
        del memories, links, cursor
        raise RuntimeError("db batch failed")

    monkeypatch.setattr(
        store, "persist_long_term_promotion_batch", failing_persist_batch
    )

    try:
        await store.save_experience(
            _experience(
                experience_id="exp-1",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                event_time=now,
                category="project_progress",
                summary="Implemented memory postprocess integration",
                detail_summary="The memory pipeline was integrated after message send.",
                importance=0.82,
                confidence=0.91,
                source_refs=["turn:1"],
                created_at=now,
                updated_at=now,
            )
        )

        with pytest.raises(RuntimeError, match="db batch failed"):
            await service.run_promotion(TEST_CANONICAL_USER_ID)
    finally:
        await store.close()

    assert list((temp_dir / "long_term").rglob("*.md")) == []


@pytest.mark.asyncio
async def test_long_term_service_updates_existing_memory(temp_dir: Path):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    loader = DocumentLoader(config)
    now = datetime.now(UTC)

    try:
        existing_path = loader.save_long_term_document(
            LongTermMemoryDocument(
                memory_id="ltm-1",
                umo=TEST_UMO,
                canonical_user_id=TEST_CANONICAL_USER_ID,
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                status="active",
                title="Existing memory-first preference",
                summary="The user prefers memory-first sequencing.",
                detail_summary="Original detail summary.",
                supporting_experiences=["exp-old"],
                updates=[{"timestamp": now.isoformat(), "summary": "created"}],
                source_refs=["exp:old"],
                tags=["memory"],
                first_event_at=now - timedelta(days=1),
                last_event_at=now - timedelta(days=1),
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            )
        )
        await store.upsert_long_term_memory_index(
            _long_term_memory_index(
                memory_id="ltm-1",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                title="Existing memory-first preference",
                summary="The user prefers memory-first sequencing.",
                status="active",
                doc_path=str(existing_path),
                importance=0.8,
                confidence=0.85,
                tags=["memory"],
                source_refs=["exp:old"],
                first_event_at=now - timedelta(days=1),
                last_event_at=now - timedelta(days=1),
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            )
        )
        await store.save_experience(
            _experience(
                experience_id="exp-new",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                event_time=now,
                category="project_progress",
                summary="A new experience reinforced the roadmap preference",
                detail_summary="The roadmap preference was reinforced again.",
                importance=0.9,
                confidence=0.95,
                source_refs=["turn:new"],
                created_at=now,
                updated_at=now,
            )
        )
        service = LongTermMemoryService(
            store,
            analyzer_manager=StubLongTermUpdateAnalyzerManager("ltm-1"),  # type: ignore[arg-type]
            analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
            long_term_config=MemoryLongTermConfig(
                enabled=True,
                docs_dir=config.storage.docs_root,
                min_experience_importance=0.7,
                min_pending_experiences=1,
            ),
            document_loader=loader,
        )

        persisted = await service.run_promotion(TEST_CANONICAL_USER_ID)
        links = await store.list_long_term_memory_links("ltm-1")
        updated_doc = loader.load_long_term_document(existing_path)
    finally:
        await store.close()

    assert len(persisted) == 1
    assert persisted[0].memory_id == "ltm-1"
    assert persisted[0].title == "Updated memory-first implementation preference"
    assert len(links) == 1
    assert updated_doc.title == "Updated memory-first implementation preference"
    assert "exp-new" in updated_doc.supporting_experiences


@pytest.mark.asyncio
async def test_long_term_service_stops_before_db_when_markdown_prepare_fails(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    analyzer_manager = StubLongTermAnalyzerManager()
    service = LongTermMemoryService(
        store,
        analyzer_manager=analyzer_manager,  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        long_term_config=MemoryLongTermConfig(
            enabled=True,
            docs_dir=config.storage.docs_root,
            min_experience_importance=0.7,
            min_pending_experiences=1,
        ),
        document_loader=FailingDocumentLoader(config),
    )
    now = datetime.now(UTC)

    try:
        await store.save_experience(
            _experience(
                experience_id="exp-1",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                event_time=now,
                category="project_progress",
                summary="Implemented memory postprocess integration",
                detail_summary="The memory pipeline was integrated after message send.",
                importance=0.82,
                confidence=0.91,
                source_refs=["turn:1"],
                created_at=now,
                updated_at=now,
            )
        )

        with pytest.raises(RuntimeError, match="long-term markdown write failed"):
            await service.run_promotion(TEST_CANONICAL_USER_ID)
        stored_memory = await store.list_long_term_memory_indexes(
            TEST_CANONICAL_USER_ID,
            limit=0,
            scope_type="user",
            scope_id=TEST_CANONICAL_USER_ID,
        )
        cursor = await store.get_long_term_promotion_cursor(
            TEST_CANONICAL_USER_ID,
            "user",
            TEST_CANONICAL_USER_ID,
        )
    finally:
        await store.close()

    assert stored_memory == []
    assert cursor is None
    assert list((temp_dir / "long_term").rglob("*.md")) == []


@pytest.mark.asyncio
async def test_long_term_service_raises_when_promote_does_not_cover_all_candidates(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    service = LongTermMemoryService(
        store,
        analyzer_manager=MissingCoverageLongTermAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        long_term_config=MemoryLongTermConfig(
            enabled=True,
            docs_dir=config.storage.docs_root,
            min_experience_importance=0.7,
            min_pending_experiences=2,
        ),
    )
    now = datetime.now(UTC)

    try:
        for offset, exp_id in enumerate(("exp-1", "exp-2")):
            await store.save_experience(
                _experience(
                    experience_id=exp_id,
                    scope_type="user",
                    scope_id=TEST_CANONICAL_USER_ID,
                    event_time=now + timedelta(seconds=offset),
                    category="project_progress",
                    summary=f"Experience {exp_id}",
                    detail_summary="Promotion coverage should fail.",
                    importance=0.82,
                    confidence=0.91,
                    source_refs=[f"turn:{exp_id}"],
                    created_at=now + timedelta(microseconds=offset),
                    updated_at=now + timedelta(microseconds=offset),
                )
            )

        with pytest.raises(
            MemoryAnalyzerExecutionError,
            match="did not cover all candidate experiences",
        ):
            await service.run_promotion(TEST_CANONICAL_USER_ID)

        cursor = await store.get_long_term_promotion_cursor(
            TEST_CANONICAL_USER_ID,
            "user",
            TEST_CANONICAL_USER_ID,
        )
        memories = await store.list_long_term_memory_indexes(
            TEST_CANONICAL_USER_ID,
            limit=0,
            scope_type="user",
            scope_id=TEST_CANONICAL_USER_ID,
        )
    finally:
        await store.close()

    assert cursor is None
    assert memories == []


@pytest.mark.asyncio
async def test_long_term_service_raises_when_promote_duplicates_experience_coverage(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    service = LongTermMemoryService(
        store,
        analyzer_manager=DuplicateCoverageLongTermAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        long_term_config=MemoryLongTermConfig(
            enabled=True,
            docs_dir=config.storage.docs_root,
            min_experience_importance=0.7,
            min_pending_experiences=2,
        ),
    )
    now = datetime.now(UTC)

    try:
        for offset, exp_id in enumerate(("exp-1", "exp-2")):
            await store.save_experience(
                _experience(
                    experience_id=exp_id,
                    scope_type="user",
                    scope_id=TEST_CANONICAL_USER_ID,
                    event_time=now + timedelta(seconds=offset),
                    category="project_progress",
                    summary=f"Experience {exp_id}",
                    detail_summary="Promotion duplicate coverage should fail.",
                    importance=0.82,
                    confidence=0.91,
                    source_refs=[f"turn:{exp_id}"],
                    created_at=now + timedelta(microseconds=offset),
                    updated_at=now + timedelta(microseconds=offset),
                )
            )

        with pytest.raises(
            MemoryAnalyzerExecutionError,
            match="duplicate experience coverage",
        ):
            await service.run_promotion(TEST_CANONICAL_USER_ID)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_long_term_service_raises_on_duplicate_update_target_in_same_batch(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    loader = DocumentLoader(config)
    now = datetime.now(UTC)

    try:
        existing_path = loader.save_long_term_document(
            LongTermMemoryDocument(
                memory_id="ltm-1",
                umo=TEST_UMO,
                canonical_user_id=TEST_CANONICAL_USER_ID,
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                status="active",
                title="Existing memory-first preference",
                summary="The user prefers memory-first sequencing.",
                detail_summary="Original detail summary.",
                supporting_experiences=["exp-old"],
                updates=[{"timestamp": now.isoformat(), "summary": "created"}],
                source_refs=["exp:old"],
                tags=["memory"],
                first_event_at=now - timedelta(days=1),
                last_event_at=now - timedelta(days=1),
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            )
        )
        await store.upsert_long_term_memory_index(
            _long_term_memory_index(
                memory_id="ltm-1",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                title="Existing memory-first preference",
                summary="The user prefers memory-first sequencing.",
                status="active",
                doc_path=str(existing_path),
                importance=0.8,
                confidence=0.85,
                tags=["memory"],
                source_refs=["exp:old"],
                first_event_at=now - timedelta(days=1),
                last_event_at=now - timedelta(days=1),
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            )
        )
        for offset, exp_id in enumerate(("exp-1", "exp-2")):
            await store.save_experience(
                _experience(
                    experience_id=exp_id,
                    scope_type="user",
                    scope_id=TEST_CANONICAL_USER_ID,
                    event_time=now + timedelta(seconds=offset),
                    category="project_progress",
                    summary=f"Experience {exp_id}",
                    detail_summary="Duplicate update target should fail.",
                    importance=0.9,
                    confidence=0.95,
                    source_refs=[f"turn:{exp_id}"],
                    created_at=now + timedelta(microseconds=offset),
                    updated_at=now + timedelta(microseconds=offset),
                )
            )
        service = LongTermMemoryService(
            store,
            analyzer_manager=DuplicateUpdateTargetLongTermAnalyzerManager("ltm-1"),  # type: ignore[arg-type]
            analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
            long_term_config=MemoryLongTermConfig(
                enabled=True,
                docs_dir=config.storage.docs_root,
                min_experience_importance=0.7,
                min_pending_experiences=2,
            ),
            document_loader=loader,
        )

        with pytest.raises(
            MemoryAnalyzerExecutionError,
            match="duplicate update target",
        ):
            await service.run_promotion(TEST_CANONICAL_USER_ID)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_long_term_service_raises_on_invalid_analyzer_payload(temp_dir: Path):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    service = LongTermMemoryService(
        store,
        analyzer_manager=InvalidLongTermAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        long_term_config=MemoryLongTermConfig(
            enabled=True,
            docs_dir=config.storage.docs_root,
            min_experience_importance=0.7,
            min_pending_experiences=1,
        ),
    )
    now = datetime.now(UTC)

    try:
        await store.save_experience(
            _experience(
                experience_id="exp-1",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                event_time=now,
                category="project_progress",
                summary="Trigger invalid promotion",
                detail_summary="Invalid analyzer payload should raise.",
                importance=0.9,
                confidence=0.95,
                source_refs=["turn:1"],
                created_at=now,
                updated_at=now,
            )
        )
        with pytest.raises(MemoryAnalyzerExecutionError):
            await service.run_promotion(TEST_CANONICAL_USER_ID)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_long_term_service_raises_on_out_of_range_compose_score(temp_dir: Path):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    service = LongTermMemoryService(
        store,
        analyzer_manager=OutOfRangeLongTermAnalyzerManager(),  # type: ignore[arg-type]
        analysis_config=MemoryAnalysisConfig(enabled=True, strict=True),
        long_term_config=MemoryLongTermConfig(
            enabled=True,
            docs_dir=config.storage.docs_root,
            min_experience_importance=0.7,
            min_pending_experiences=1,
        ),
    )
    now = datetime.now(UTC)

    try:
        await store.save_experience(
            _experience(
                experience_id="exp-1",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                event_time=now,
                category="project_progress",
                summary="Trigger out-of-range compose score",
                detail_summary="The analyzer score should be rejected.",
                importance=0.9,
                confidence=0.95,
                source_refs=["turn:1"],
                created_at=now,
                updated_at=now,
            )
        )
        with pytest.raises(
            MemoryAnalyzerExecutionError,
            match="must be between 0 and 1",
        ):
            await service.run_promotion(TEST_CANONICAL_USER_ID)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_document_search_service_hydrates_results_and_loads_body(temp_dir: Path):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    loader = DocumentLoader(config)
    now = datetime.now(UTC)

    try:
        doc_path = loader.save_long_term_document(
            LongTermMemoryDocument(
                memory_id="ltm-1",
                umo=TEST_UMO,
                canonical_user_id=TEST_CANONICAL_USER_ID,
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                status="active",
                title="Searchable long-term memory",
                summary="This memory should be returned by document search.",
                detail_summary="The body contains the long-term detail text.",
                supporting_experiences=["exp-1"],
                updates=[{"timestamp": now.isoformat(), "summary": "created"}],
                source_refs=["exp:exp-1"],
                tags=["memory", "search"],
                first_event_at=now,
                last_event_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await store.upsert_long_term_memory_index(
            _long_term_memory_index(
                memory_id="ltm-1",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                title="Searchable long-term memory",
                summary="This memory should be returned by document search.",
                status="active",
                doc_path=str(doc_path),
                importance=0.85,
                confidence=0.9,
                tags=["memory", "search"],
                source_refs=["exp:exp-1"],
                first_event_at=now,
                last_event_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        vector_index = StubVectorIndex([("ltm-1", 0.93)])
        service = DocumentSearchService(
            store,
            vector_index=vector_index,  # type: ignore[arg-type]
            document_loader=loader,
        )

        results = await service.search_long_term_memories(
            _document_search_request(
                query="memory roadmap",
                include_body=True,
                conversation_id=None,
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
            )
        )
    finally:
        await store.close()

    assert len(results) == 1
    assert results[0].memory_id == "ltm-1"
    assert results[0].body_text is not None
    assert results[0].body_text.startswith("# Searchable long-term memory")
    assert "## Summary" in results[0].body_text
    assert "memory_id:" not in results[0].body_text
    assert "---" not in results[0].body_text
    assert vector_index.calls[0]["metadata_filters"] == {
        "scope_type": "user",
        "scope_id": TEST_CANONICAL_USER_ID,
    }


@pytest.mark.asyncio
async def test_long_term_manual_service_imports_new_document_and_normalizes_path(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: true",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    loader = DocumentLoader(config)
    vector_index = StubManualVectorIndex()
    service = LongTermMemoryManualService(
        store,
        document_loader=loader,
        vector_index=vector_index,  # type: ignore[arg-type]
    )
    now = datetime.now(UTC)
    source_path = temp_dir / "manual-source.md"

    try:
        loader.save_long_term_document(
            LongTermMemoryDocument(
                memory_id="manual-1",
                umo=TEST_UMO,
                canonical_user_id=TEST_CANONICAL_USER_ID,
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="user_preference",
                status="active",
                title="Manual imported memory",
                summary="The user wants manual long-term imports.",
                detail_summary="This document was created manually before import.",
                importance=0.88,
                confidence=0.91,
                supporting_experiences=["exp-manual"],
                updates=[{"timestamp": now.isoformat(), "summary": "created"}],
                source_refs=["manual:1"],
                tags=["manual", "import"],
                first_event_at=now,
                last_event_at=now,
                created_at=now,
                updated_at=now,
            ),
            doc_path=source_path,
        )
        persisted = await service.upsert_memory_from_document(source_path)
        loaded = await store.get_long_term_memory_index("manual-1")
    finally:
        await store.close()

    expected_path = loader.build_long_term_doc_path(
        LongTermMemoryDocument(
            memory_id="manual-1",
            umo=TEST_UMO,
            canonical_user_id=TEST_CANONICAL_USER_ID,
            scope_type="user",
            scope_id=TEST_CANONICAL_USER_ID,
            category="user_preference",
            status="active",
            title="Manual imported memory",
            summary="The user wants manual long-term imports.",
            detail_summary="This document was created manually before import.",
        )
    )
    assert persisted.memory_id == "manual-1"
    assert loaded is not None
    assert loaded.doc_path == str(expected_path)
    assert expected_path.exists()
    assert source_path.exists()
    assert vector_index.calls == ["manual-1"]


@pytest.mark.asyncio
async def test_long_term_manual_service_updates_existing_memory_from_document(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: false",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    loader = DocumentLoader(config)
    service = LongTermMemoryManualService(
        store,
        document_loader=loader,
    )
    now = datetime.now(UTC)
    normalized_path = loader.build_long_term_doc_path(
        LongTermMemoryDocument(
            memory_id="manual-2",
            umo=TEST_UMO,
            canonical_user_id=TEST_CANONICAL_USER_ID,
            scope_type="user",
            scope_id=TEST_CANONICAL_USER_ID,
            category="project_progress",
            status="active",
            title="Original manual memory",
            summary="Original summary.",
            detail_summary="Original detail.",
        )
    )
    update_source_path = temp_dir / "manual-update.md"

    try:
        original_doc = LongTermMemoryDocument(
            memory_id="manual-2",
            umo=TEST_UMO,
            canonical_user_id=TEST_CANONICAL_USER_ID,
            scope_type="user",
            scope_id=TEST_CANONICAL_USER_ID,
            category="project_progress",
            status="active",
            title="Original manual memory",
            summary="Original summary.",
            detail_summary="Original detail.",
            importance=0.7,
            confidence=0.8,
            source_refs=["manual:original"],
            tags=["original"],
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
        )
        loader.save_long_term_document(original_doc, doc_path=normalized_path)
        await store.upsert_long_term_memory_index(
            _long_term_memory_index(
                memory_id="manual-2",
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                title="Original manual memory",
                summary="Original summary.",
                status="active",
                doc_path=str(normalized_path),
                importance=0.7,
                confidence=0.8,
                tags=["original"],
                source_refs=["manual:original"],
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            )
        )
        loader.save_long_term_document(
            LongTermMemoryDocument(
                memory_id="manual-2",
                umo=TEST_UMO,
                canonical_user_id=TEST_CANONICAL_USER_ID,
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                status="archived",
                title="Updated manual memory",
                summary="Updated summary.",
                detail_summary="Updated detail.",
                importance=0.92,
                confidence=0.96,
                source_refs=["manual:updated"],
                tags=["updated"],
                created_at=now - timedelta(days=1),
                updated_at=now,
            ),
            doc_path=update_source_path,
        )

        persisted = await service.upsert_memory_from_document(update_source_path)
        loaded_doc = loader.load_long_term_document(normalized_path)
    finally:
        await store.close()

    assert persisted.memory_id == "manual-2"
    assert persisted.title == "Updated manual memory"
    assert persisted.status == LongTermMemoryStatus.ARCHIVED.value
    assert persisted.doc_path == str(normalized_path)
    assert loaded_doc.title == "Updated manual memory"
    assert loaded_doc.importance == pytest.approx(0.92)
    assert loaded_doc.confidence == pytest.approx(0.96)


@pytest.mark.asyncio
async def test_long_term_manual_service_rejects_invalid_document_fields(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    loader = DocumentLoader(config)
    service = LongTermMemoryManualService(store, document_loader=loader)
    source_path = temp_dir / "invalid-manual.md"

    try:
        source_path.write_text(
            "\n".join(
                [
                    "---",
                    "memory_id: invalid-1",
                    "umo: test:private:user",
                    "canonical_user_id: canonical-user-1",
                    "scope_type: user",
                    "scope_id: canonical-user-1",
                    "category: invalid_category",
                    "status: active",
                    "title: Invalid manual memory",
                    "importance: 0.5",
                    "confidence: 0.7",
                    "---",
                    "",
                    "# Invalid manual memory",
                    "",
                    "## Summary",
                    "```text",
                    "Summary exists.",
                    "```",
                    "",
                ],
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="invalid category"):
            await service.upsert_memory_from_document(source_path)
        loaded = await store.get_long_term_memory_index("invalid-1")
    finally:
        await store.close()

    assert loaded is None


@pytest.mark.asyncio
async def test_long_term_manual_service_raises_when_vector_enabled_without_binding(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: true",
                "  provider_id: embedding-test",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    loader = DocumentLoader(config)
    service = LongTermMemoryManualService(
        store,
        document_loader=loader,
        vector_index=MemoryVectorIndex(store, config=config),
    )
    source_path = temp_dir / "manual-no-binding.md"
    now = datetime.now(UTC)

    try:
        loader.save_long_term_document(
            LongTermMemoryDocument(
                memory_id="manual-unbound",
                umo=TEST_UMO,
                canonical_user_id=TEST_CANONICAL_USER_ID,
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                status="active",
                title="Unbound vector import",
                summary="This import should fail before any write.",
                detail_summary="The vector index is enabled but not bound.",
                importance=0.8,
                confidence=0.9,
                created_at=now,
                updated_at=now,
            ),
            doc_path=source_path,
        )
        with pytest.raises(
            RuntimeError,
            match="not bound to ProviderManager",
        ):
            await service.upsert_memory_from_document(source_path)
        loaded = await store.get_long_term_memory_index("manual-unbound")
    finally:
        await store.close()

    assert loaded is None


@pytest.mark.asyncio
async def test_long_term_manual_service_raises_when_vector_refresh_fails(
    temp_dir: Path,
):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "memory.db").as_posix()
    docs_root = (temp_dir / "long_term").as_posix()
    projections_root = (temp_dir / "projections").as_posix()
    config_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "storage:",
                f'  sqlite_path: "{sqlite_path}"',
                f'  docs_root: "{docs_root}"',
                f'  projections_root: "{projections_root}"',
                "vector_index:",
                "  enabled: true",
            ]
        ),
        encoding="utf-8",
    )
    config = load_memory_config(config_path)
    store = MemoryStore(config=config)
    loader = DocumentLoader(config)
    service = LongTermMemoryManualService(
        store,
        document_loader=loader,
        vector_index=FailingManualVectorIndex(),  # type: ignore[arg-type]
    )
    source_path = temp_dir / "manual-vector-failure.md"
    now = datetime.now(UTC)

    try:
        loader.save_long_term_document(
            LongTermMemoryDocument(
                memory_id="manual-3",
                umo=TEST_UMO,
                canonical_user_id=TEST_CANONICAL_USER_ID,
                scope_type="user",
                scope_id=TEST_CANONICAL_USER_ID,
                category="project_progress",
                status="active",
                title="Vector failure manual memory",
                summary="Vector refresh should not roll back import.",
                detail_summary="The vector index fails after the import succeeds.",
                importance=0.82,
                confidence=0.9,
                created_at=now,
                updated_at=now,
            ),
            doc_path=source_path,
        )
        with pytest.raises(RuntimeError, match="manual vector refresh failed"):
            await service.upsert_memory_from_document(source_path)
        loaded = await store.get_long_term_memory_index("manual-3")
    finally:
        await store.close()

    assert loaded is not None
    assert Path(loaded.doc_path).exists()


@pytest.mark.asyncio
async def test_memory_service_import_long_term_memory_document_delegates_to_manual_service(
    temp_dir: Path,
):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    memory_service = MemoryService(
        store,
        TurnRecordService(store),
        ShortTermMemoryService(
            store, RecentConversationSource(store, recent_turns_window=8)
        ),
        MemorySnapshotBuilder(store),
        manual_long_term_service=MagicMock(),
    )
    expected = LongTermMemoryIndex(
        memory_id="manual-service-1",
        umo=TEST_UMO,
        canonical_user_id=TEST_CANONICAL_USER_ID,
        scope_type="user",
        scope_id=TEST_CANONICAL_USER_ID,
        category="user_preference",
        title="Delegated import",
        summary="Delegated summary",
        status="active",
        doc_path="ignored.md",
    )
    memory_service.manual_long_term_service.upsert_memory_from_document = AsyncMock(  # type: ignore[method-assign]
        return_value=expected
    )

    try:
        result = await memory_service.import_long_term_memory_document(
            temp_dir / "manual.md"
        )
    finally:
        await store.close()

    assert result.memory_id == "manual-service-1"


@pytest.mark.asyncio
async def test_experience_service_writes_markdown_projection(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    projection_service = ExperienceProjectionService(
        store,
        projections_root=temp_dir / "projections",
    )
    experience_service = ExperienceService(
        store,
        projection_service=projection_service,
    )
    now = datetime.now(UTC)

    try:
        persisted = await experience_service.persist_experiences(
            [
                _experience(
                    experience_id="exp-1",
                    scope_type="user",
                    scope_id=TEST_CANONICAL_USER_ID,
                    event_time=now,
                    category="project_progress",
                    summary="Implemented snapshot exposure",
                    detail_summary="Snapshot now includes recent conversation experiences.",
                    importance=0.81,
                    confidence=0.93,
                    source_refs=["turn:turn-1"],
                    created_at=now,
                    updated_at=now,
                ),
                _experience(
                    experience_id="exp-2",
                    scope_type="user",
                    scope_id=TEST_CANONICAL_USER_ID,
                    event_time=now + timedelta(seconds=1),
                    category="episodic_event",
                    summary="Wrote the experience projection",
                    detail_summary="A markdown timeline projection was generated.",
                    importance=0.78,
                    confidence=0.9,
                    source_refs=["turn:turn-2"],
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await experience_service.refresh_projections_for_experiences(persisted)
        projection_path = projection_service._build_projection_path(
            TEST_CANONICAL_USER_ID,
            "user",
            TEST_CANONICAL_USER_ID,
        )
    finally:
        await store.close()

    assert len(persisted) == 2
    assert projection_path.exists()
    content = projection_path.read_text(encoding="utf-8")
    assert "projection_type: experience_timeline" in content
    assert "generated_at:" in content
    assert "## Experience exp-1" in content
    assert "### Summary" in content
    assert "```text" in content
    assert "Implemented snapshot exposure" in content
    assert "Wrote the experience projection" in content


@pytest.mark.asyncio
async def test_experience_projection_handles_multiline_markdown_like_content(
    temp_dir: Path,
):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    projection_service = ExperienceProjectionService(
        store,
        projections_root=temp_dir / "projections",
    )
    experience_service = ExperienceService(
        store,
        projection_service=projection_service,
    )
    now = datetime.now(UTC)

    try:
        persisted = await experience_service.persist_experiences(
            [
                _experience(
                    experience_id="exp-special",
                    scope_type="user",
                    scope_id=TEST_CANONICAL_USER_ID,
                    event_time=now,
                    category="episodic_event",
                    summary="Line 1\n- bullet\n---\n# heading",
                    detail_summary="code fence ``` inside\nvalue: test",
                    importance=0.8,
                    confidence=0.9,
                    source_refs=["turn:1", "weird:ref:#-value"],
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        await experience_service.refresh_projections_for_experiences(persisted)
        projection_path = projection_service._build_projection_path(
            TEST_CANONICAL_USER_ID,
            "user",
            TEST_CANONICAL_USER_ID,
        )
    finally:
        await store.close()

    content = projection_path.read_text(encoding="utf-8")
    assert content.startswith("---\nprojection_type: experience_timeline\n")
    assert "## Experience exp-special" in content
    assert "### Summary" in content
    assert "### Detail Summary" in content
    assert "### Source Refs" in content
    assert "Line 1\n- bullet\n---\n# heading" in content
    assert "code fence ``` inside\nvalue: test" in content


@pytest.mark.asyncio
async def test_memory_postprocessor_builds_request_from_conversation_history():
    history = _make_history()
    conversation = Conversation(
        platform_id="test",
        user_id="test:private:user",
        cid="conv-1",
        history=json.dumps(history),
    )
    event = MagicMock()
    event.unified_msg_origin = TEST_UMO
    event.get_platform_id.return_value = TEST_PLATFORM_ID
    event.get_sender_id.return_value = "user-1"
    event.get_sender_name.return_value = "tester"
    event.session_id = "session-1"
    memory_service = MagicMock()
    memory_service.update_from_postprocess = AsyncMock()
    memory_service.identity_resolver = MagicMock()
    memory_service.identity_resolver.resolve_from_event = AsyncMock(
        return_value=_memory_identity()
    )
    processor = MemoryPostProcessor(memory_service)
    ctx = MagicMock()
    ctx.event = event
    ctx.conversation = conversation
    ctx.provider_request = ProviderRequest(prompt="hello", session_id="session-1")
    ctx.timestamp = datetime.now(UTC)

    req = await processor.build_update_request(ctx)

    assert req is not None
    assert req.conversation_id == "conv-1"
    assert req.platform_user_key == TEST_PLATFORM_USER_KEY
    assert req.canonical_user_id == TEST_CANONICAL_USER_ID
    assert req.user_message["content"] == "Then wire postprocess and snapshot."
    assert req.assistant_message["content"] == "That gives us a minimal closed loop."
    assert req.provider_request is not None
    assert isinstance(req.provider_request.get("conversation_history"), list)


@pytest.mark.asyncio
async def test_memory_postprocessor_skips_invalid_conversation_history():
    event = MagicMock()
    event.unified_msg_origin = TEST_UMO
    event.get_platform_id.return_value = TEST_PLATFORM_ID
    event.get_sender_id.return_value = "user-1"
    event.get_sender_name.return_value = "tester"
    event.session_id = "session-1"
    memory_service = MagicMock()
    memory_service.update_from_postprocess = AsyncMock()
    memory_service.identity_resolver = MagicMock()
    memory_service.identity_resolver.resolve_from_event = AsyncMock(
        return_value=_memory_identity()
    )
    processor = MemoryPostProcessor(memory_service)
    ctx = MagicMock()
    ctx.event = event
    ctx.conversation = Conversation(
        platform_id="test",
        user_id="test:private:user",
        cid="conv-1",
        history=json.dumps([{"role": "user", "content": "only user"}]),
    )
    ctx.provider_request = None
    ctx.timestamp = datetime.now(UTC)

    req = await processor.build_update_request(ctx)
    await processor.run(ctx)

    assert req is None
    memory_service.update_from_postprocess.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_postprocessor_falls_back_to_provider_request_conversation():
    history = [
        {"role": "user", "content": "Previous turn."},
        {"role": "assistant", "content": "Previous answer."},
    ]
    provider_conversation = Conversation(
        platform_id="test",
        user_id="test:private:user",
        cid="conv-1",
        history=json.dumps(history),
    )
    event = MagicMock()
    event.unified_msg_origin = TEST_UMO
    event.get_platform_id.return_value = TEST_PLATFORM_ID
    event.get_sender_id.return_value = "user-1"
    event.get_sender_name.return_value = "tester"
    event.session_id = "session-1"
    memory_service = MagicMock()
    memory_service.update_from_postprocess = AsyncMock()
    memory_service.identity_resolver = MagicMock()
    memory_service.identity_resolver.resolve_from_event = AsyncMock(
        return_value=_memory_identity()
    )
    processor = MemoryPostProcessor(memory_service)
    ctx = MagicMock()
    ctx.event = event
    ctx.conversation = None
    ctx.provider_request = ProviderRequest(
        prompt="Current user turn.",
        session_id="session-1",
        conversation=provider_conversation,
    )
    ctx.llm_response = LLMResponse(
        role="assistant",
        completion_text="Current assistant reply.",
    )
    ctx.timestamp = datetime.now(UTC)

    req = await processor.build_update_request(ctx)

    assert req is not None
    assert req.conversation_id == "conv-1"
    assert req.platform_user_key == TEST_PLATFORM_USER_KEY
    assert req.canonical_user_id == TEST_CANONICAL_USER_ID
    assert req.user_message["content"] == "Current user turn."
    assert req.assistant_message["content"] == "Current assistant reply."
    assert req.provider_request is not None
    assert (
        req.provider_request["history_source"]
        == "provider_request.conversation.history"
    )


@pytest.mark.asyncio
async def test_memory_postprocessor_falls_back_to_provider_request_contexts():
    event = MagicMock()
    event.unified_msg_origin = TEST_UMO
    event.get_platform_id.return_value = TEST_PLATFORM_ID
    event.get_sender_id.return_value = "user-1"
    event.get_sender_name.return_value = "tester"
    event.session_id = "session-1"
    memory_service = MagicMock()
    memory_service.update_from_postprocess = AsyncMock()
    memory_service.identity_resolver = MagicMock()
    memory_service.identity_resolver.resolve_from_event = AsyncMock(
        return_value=_memory_identity()
    )
    processor = MemoryPostProcessor(memory_service)
    ctx = MagicMock()
    ctx.event = event
    ctx.conversation = None
    ctx.provider_request = ProviderRequest(
        prompt="Please continue the task.",
        session_id="session-1",
        contexts=[
            {"role": "user", "content": "Earlier request."},
            {"role": "assistant", "content": "Earlier answer."},
        ],
    )
    ctx.llm_response = LLMResponse(
        role="assistant",
        completion_text="Current task completed.",
    )
    ctx.timestamp = datetime.now(UTC)

    req = await processor.build_update_request(ctx)

    assert req is not None
    assert req.conversation_id is None
    assert req.user_message["content"] == "Please continue the task."
    assert req.assistant_message["content"] == "Current task completed."
    assert req.provider_request is not None
    assert req.provider_request["history_source"] == "provider_request.contexts"


def test_register_memory_postprocessor_reuses_singleton_and_updates_service(
    monkeypatch: pytest.MonkeyPatch,
):
    manager = get_postprocess_manager()
    manager.clear()
    reset_memory_postprocessor()

    try:
        monkeypatch.setattr(
            "astrbot.core.memory.postprocessor.get_memory_config",
            lambda: MagicMock(enabled=True),
        )

        first_service = MagicMock()
        second_service = MagicMock()

        first_processor = register_memory_postprocessor(first_service)
        second_processor = register_memory_postprocessor(second_service)

        assert first_processor is not None
        assert second_processor is first_processor
        assert first_processor.memory_service is second_service
        assert manager.get_processors(first_processor.triggers[0]) == [first_processor]
    finally:
        reset_memory_postprocessor()
        manager.clear()
