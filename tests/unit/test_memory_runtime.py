from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.core.db.po import Conversation
from astrbot.core.memory.history_source import RecentConversationSource
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
from astrbot.core.provider.entities import ProviderRequest


def _make_history() -> list[dict]:
    return [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "We should build memory first."},
        {"role": "assistant", "content": "Let's start from data types and store."},
        {"role": "user", "content": "Then wire postprocess and snapshot."},
        {"role": "assistant", "content": "That gives us a minimal closed loop."},
    ]


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
