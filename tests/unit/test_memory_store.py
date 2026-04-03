from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import select

from astrbot.core.memory import (
    LongTermMemoryIndex,
    MemoryStore,
    PersonaEvolutionLog,
    PersonaState,
    ScopeType,
    SessionInsight,
    ShortTermMemory,
    TopicState,
    TurnRecord,
    load_memory_config,
)
from astrbot.core.memory.po import (
    MemoryExperience,
    MemoryLongTermMemoryIndex,
    MemoryPersonaEvolutionLog,
    MemoryPersonaState,
    MemorySessionInsight,
    MemoryShortTermMemory,
    MemoryTopicState,
    MemoryTurnRecord,
)
from astrbot.core.memory.types import Experience


@pytest.mark.asyncio
async def test_memory_store_initializes_tables_and_runtime_dirs(temp_dir: Path):
    config_path = temp_dir / "memory-config.yaml"
    sqlite_path = (temp_dir / "data" / "memory" / "test-memory.db").as_posix()
    docs_root = (temp_dir / "data" / "memory" / "long_term").as_posix()
    projections_root = (temp_dir / "data" / "memory" / "projections").as_posix()
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

    try:
        await store.initialize()
        assert config.storage.sqlite_path.parent.exists()
        assert config.storage.docs_root.exists()
        assert config.storage.projections_root.exists()
        assert await store.ping() is True

        async with store.get_db() as session:
            for model in (
                MemoryTurnRecord,
                MemoryTopicState,
                MemoryShortTermMemory,
                MemorySessionInsight,
                MemoryExperience,
                MemoryLongTermMemoryIndex,
                MemoryPersonaState,
                MemoryPersonaEvolutionLog,
            ):
                result = await session.execute(select(model))
                assert result.scalars().all() == []
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_memory_store_round_trip_for_short_term_objects(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    now = datetime.now(UTC)

    try:
        saved_turn = await store.save_turn_record(
            TurnRecord(
                turn_id="turn-1",
                umo="test:private:user",
                conversation_id="conv-1",
                platform_id="test",
                session_id="session-1",
                user_message={"role": "user", "content": "hello"},
                assistant_message={"role": "assistant", "content": "hi"},
                message_timestamp=now,
                source_refs=["msg:test:1"],
                created_at=now,
            )
        )
        saved_topic = await store.upsert_topic_state(
            TopicState(
                umo="test:private:user",
                conversation_id="conv-1",
                current_topic="memory design",
                topic_summary="Discussing memory MVP",
                topic_confidence=1.2,
                last_active_at=now,
            )
        )
        saved_short_term = await store.upsert_short_term_memory(
            ShortTermMemory(
                umo="test:private:user",
                conversation_id="conv-1",
                short_summary="User wants memory types and store first",
                active_focus="Implement data layer",
                updated_at=now,
            )
        )

        recent_turns = await store.get_recent_turn_records("test:private:user", 10)
        loaded_topic = await store.get_topic_state("test:private:user", "conv-1")
        loaded_short_term = await store.get_short_term_memory(
            "test:private:user",
            "conv-1",
        )

        assert saved_turn.turn_id == "turn-1"
        assert recent_turns[0].assistant_message["content"] == "hi"
        assert saved_topic.topic_confidence == 1.0
        assert loaded_topic is not None
        assert loaded_topic.current_topic == "memory design"
        assert saved_short_term.active_focus == "Implement data layer"
        assert loaded_short_term is not None
        assert loaded_short_term.short_summary.startswith("User wants memory")
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_memory_store_round_trip_for_mid_and_long_term_objects(temp_dir: Path):
    store = MemoryStore(db_path=temp_dir / "memory.db")
    now = datetime.now(UTC)

    try:
        saved_insight = await store.save_session_insight(
            SessionInsight(
                insight_id="insight-1",
                umo="test:private:user",
                conversation_id="conv-1",
                window_start_at=now - timedelta(hours=1),
                window_end_at=now,
                topic_summary="Memory planning",
                progress_summary="Settled on store-first approach",
                summary_text="The user wants to implement types and store before services.",
                created_at=now,
            )
        )
        saved_experience = await store.save_experience(
            Experience(
                experience_id="exp-1",
                umo="test:private:user",
                conversation_id="conv-1",
                scope_type=ScopeType.USER,
                scope_id="test:private:user",
                event_time=now,
                category="project_progress",
                summary="Implemented memory store foundation",
                detail_summary="Types and SQLModel tables landed first.",
                importance=0.8,
                confidence=0.9,
                source_refs=["insight:insight-1"],
                created_at=now,
                updated_at=now,
            )
        )
        saved_memory = await store.upsert_long_term_memory_index(
            LongTermMemoryIndex(
                memory_id="ltm-1",
                umo="test:private:user",
                scope_type=ScopeType.USER,
                scope_id="test:private:user",
                summary="User prefers infrastructure-first sequencing",
                doc_path="user/ltm-1.md",
                importance=0.7,
                confidence=0.8,
                tags=["architecture", "planning"],
                source_refs=["exp:exp-1"],
                created_at=now,
                updated_at=now,
            )
        )
        saved_state = await store.upsert_persona_state(
            PersonaState(
                state_id="state-1",
                scope_type=ScopeType.USER,
                scope_id="test:private:user",
                persona_id=None,
                familiarity=0.6,
                trust=0.7,
                warmth=0.8,
                formality_preference=0.4,
                directness_preference=0.9,
                updated_at=now,
            )
        )
        saved_log = await store.save_persona_evolution_log(
            PersonaEvolutionLog(
                log_id="log-1",
                scope_type=ScopeType.USER,
                scope_id="test:private:user",
                before_state={"trust": 0.5},
                after_state={"trust": 0.7},
                reason="Repeated productive collaboration",
                source_refs=["exp:exp-1"],
                created_at=now,
            )
        )

        recent_experiences = await store.list_recent_experiences("test:private:user", 5)
        ranged_experiences = await store.list_experiences_by_time_range(
            "test:private:user",
            now - timedelta(minutes=1),
            now + timedelta(minutes=1),
        )
        long_term_memories = await store.list_long_term_memory_indexes(
            "test:private:user",
            5,
        )
        loaded_state = await store.get_persona_state(
            ScopeType.USER,
            "test:private:user",
        )

        assert saved_insight.insight_id == "insight-1"
        assert saved_experience.experience_id == "exp-1"
        assert recent_experiences[0].summary == "Implemented memory store foundation"
        assert len(ranged_experiences) == 1
        assert saved_memory.memory_id == "ltm-1"
        assert long_term_memories[0].tags == ["architecture", "planning"]
        assert saved_state.trust == 0.7
        assert loaded_state is not None
        assert loaded_state.directness_preference == 0.9
        assert saved_log.reason == "Repeated productive collaboration"
    finally:
        await store.close()
