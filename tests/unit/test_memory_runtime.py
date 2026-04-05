from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.core.db.po import Conversation
from astrbot.core.memory.analyzer import MemoryAnalyzerResult
from astrbot.core.memory.analyzers.base import MemoryAnalyzerExecutionError
from astrbot.core.memory.config import MemoryAnalysisConfig
from astrbot.core.memory.history_source import (
    RecentConversationSource,
    extract_turn_payloads,
)
from astrbot.core.memory.postprocessor import (
    MemoryPostProcessor,
    register_memory_postprocessor,
    reset_memory_postprocessor,
)
from astrbot.core.memory.service import MemoryService
from astrbot.core.memory.short_term_service import ShortTermMemoryService
from astrbot.core.memory.snapshot_builder import MemorySnapshotBuilder
from astrbot.core.memory.store import MemoryStore
from astrbot.core.memory.turn_record_service import TurnRecordService
from astrbot.core.memory.types import MemoryUpdateRequest
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
