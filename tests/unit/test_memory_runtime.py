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
)
from astrbot.core.memory.consolidation_service import ConsolidationService
from astrbot.core.memory.experience_service import ExperienceService
from astrbot.core.memory.history_source import (
    RecentConversationSource,
    extract_turn_payloads,
)
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
    Experience,
    MemoryUpdateRequest,
    SessionInsight,
    ShortTermMemory,
    TopicState,
)
from astrbot.core.postprocess import get_postprocess_manager
from astrbot.core.provider.entities import LLMResponse, ProviderRequest


def _make_history() -> list[dict]:
    return [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "We should build memory first."},
        {"role": "assistant", "content": "Let's start from data types and store."},
        {"role": "user", "content": "Then wire postprocess and snapshot."},
        {"role": "assistant", "content": "That gives us a minimal closed loop."},
    ]


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
    req = MemoryUpdateRequest(
        umo="test:private:user",
        conversation_id="conv-1",
        platform_id="test",
        session_id="session-1",
        provider_request=None,
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
    req = MemoryUpdateRequest(
        umo="test:private:user",
        conversation_id="conv-1",
        platform_id="test",
        session_id="session-1",
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
    req = MemoryUpdateRequest(
        umo="test:private:user",
        conversation_id="conv-1",
        platform_id="test",
        session_id="session-1",
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
    req = MemoryUpdateRequest(
        umo="test:private:user",
        conversation_id="conv-1",
        platform_id="test",
        session_id="session-1",
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
    req = MemoryUpdateRequest(
        umo="test:private:user",
        conversation_id="conv-1",
        platform_id="test",
        session_id="session-1",
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
            MemoryUpdateRequest(
                umo="test:private:user",
                conversation_id="conv-1",
                platform_id="test",
                session_id="session-1",
                provider_request=None,
                user_message={"role": "user", "content": "First turn"},
                assistant_message={"role": "assistant", "content": "First reply"},
                message_timestamp=now,
                source_refs=[],
            )
        )
        second_turn = await turn_record_service.ingest_turn(
            MemoryUpdateRequest(
                umo="test:private:user",
                conversation_id="conv-1",
                platform_id="test",
                session_id="session-1",
                provider_request=None,
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
            "test:private:user",
            "conv-1",
        )
        insight, experiences = await consolidation_service.run_for_scope(
            "test:private:user",
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
    assert experiences[0].scope_id == "conv-1"
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
            MemoryUpdateRequest(
                umo="test:private:user",
                conversation_id="conv-1",
                platform_id="test",
                session_id="session-1",
                provider_request=None,
                user_message={"role": "user", "content": "Old turn"},
                assistant_message={"role": "assistant", "content": "Old reply"},
                message_timestamp=now,
                source_refs=[],
            )
        )
        await store.save_session_insight(
            SessionInsight(
                insight_id="insight-1",
                umo="test:private:user",
                conversation_id="conv-1",
                window_start_at=now,
                window_end_at=now,
                topic_summary="Old insight",
                progress_summary="Old progress",
                summary_text="Old summary",
                created_at=now,
            )
        )
        await turn_record_service.ingest_turn(
            MemoryUpdateRequest(
                umo="test:private:user",
                conversation_id="conv-1",
                platform_id="test",
                session_id="session-1",
                provider_request=None,
                user_message={"role": "user", "content": "New turn 1"},
                assistant_message={"role": "assistant", "content": "New reply 1"},
                message_timestamp=now + timedelta(microseconds=1),
                source_refs=[],
            )
        )
        await turn_record_service.ingest_turn(
            MemoryUpdateRequest(
                umo="test:private:user",
                conversation_id="conv-1",
                platform_id="test",
                session_id="session-1",
                provider_request=None,
                user_message={"role": "user", "content": "New turn 2"},
                assistant_message={"role": "assistant", "content": "New reply 2"},
                message_timestamp=now + timedelta(microseconds=2),
                source_refs=[],
            )
        )

        should_run = await consolidation_service.should_run_consolidation(
            "test:private:user",
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
                MemoryUpdateRequest(
                    umo="test:private:user",
                    conversation_id="conv-1",
                    platform_id="test",
                    session_id="session-1",
                    provider_request=None,
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
            "test:private:user",
            "conv-1",
        )
        experiences = await store.list_recent_experiences("test:private:user", 10)
        snapshot = await memory_service.get_snapshot("test:private:user", "conv-1")
    finally:
        await store.close()

    assert analyzer_manager.calls == ["session_insight_update", "experience_extract"]
    assert latest_insight is not None
    assert len(experiences) == 2
    assert snapshot.experiences == []


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
                MemoryUpdateRequest(
                    umo="test:private:user",
                    conversation_id="conv-1",
                    platform_id="test",
                    session_id="session-1",
                    provider_request=None,
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
            "test:private:user",
            "conv-1",
        )
        experiences = await store.list_recent_experiences(
            "test:private:user",
            10,
            conversation_id="conv-1",
        )
        snapshot = await memory_service.get_snapshot("test:private:user", "conv-1")
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
                MemoryUpdateRequest(
                    umo="test:private:user",
                    conversation_id="conv-1",
                    platform_id="test",
                    session_id="session-1",
                    provider_request=None,
                    user_message={"role": "user", "content": "Trigger consolidation"},
                    assistant_message={"role": "assistant", "content": "Reply"},
                    message_timestamp=now,
                    source_refs=[],
                )
            )
        snapshot = await memory_service.get_snapshot("test:private:user", "conv-1")
        experiences = await store.list_recent_experiences("test:private:user", 10)
    finally:
        await store.close()

    assert snapshot.topic_state is not None
    assert snapshot.short_term_memory is not None
    assert experiences == []


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
                Experience(
                    experience_id="exp-1",
                    umo="test:private:user",
                    conversation_id="conv-1",
                    scope_type="conversation",
                    scope_id="conv-1",
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
                Experience(
                    experience_id="exp-2",
                    umo="test:private:user",
                    conversation_id="conv-1",
                    scope_type="conversation",
                    scope_id="conv-1",
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
        projection_path = (
            temp_dir
            / "projections"
            / "experiences"
            / "test_private_user"
            / "conversation"
            / "conv-1.md"
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
                Experience(
                    experience_id="exp-special",
                    umo="test:private:user",
                    conversation_id="conv-1",
                    scope_type="conversation",
                    scope_id="conv-1",
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
        projection_path = (
            temp_dir
            / "projections"
            / "experiences"
            / "test_private_user"
            / "conversation"
            / "conv-1.md"
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
    event.unified_msg_origin = "test:private:user"
    event.get_platform_id.return_value = "test"
    event.session_id = "session-1"
    memory_service = MagicMock()
    memory_service.update_from_postprocess = AsyncMock()
    processor = MemoryPostProcessor(memory_service)
    ctx = MagicMock()
    ctx.event = event
    ctx.conversation = conversation
    ctx.provider_request = ProviderRequest(prompt="hello", session_id="session-1")
    ctx.timestamp = datetime.now(UTC)

    req = await processor.build_update_request(ctx)

    assert req is not None
    assert req.conversation_id == "conv-1"
    assert req.user_message["content"] == "Then wire postprocess and snapshot."
    assert req.assistant_message["content"] == "That gives us a minimal closed loop."
    assert req.provider_request is not None
    assert isinstance(req.provider_request.get("conversation_history"), list)


@pytest.mark.asyncio
async def test_memory_postprocessor_skips_invalid_conversation_history():
    event = MagicMock()
    event.unified_msg_origin = "test:private:user"
    event.get_platform_id.return_value = "test"
    event.session_id = "session-1"
    memory_service = MagicMock()
    memory_service.update_from_postprocess = AsyncMock()
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
    event.unified_msg_origin = "test:private:user"
    event.get_platform_id.return_value = "test"
    event.session_id = "session-1"
    memory_service = MagicMock()
    memory_service.update_from_postprocess = AsyncMock()
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
    event.unified_msg_origin = "test:private:user"
    event.get_platform_id.return_value = "test"
    event.session_id = "session-1"
    memory_service = MagicMock()
    memory_service.update_from_postprocess = AsyncMock()
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
