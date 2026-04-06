from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import col, desc, select, text

from astrbot.core import logger

from .config import MemoryConfig, get_memory_config
from .po import (
    BaseMemoryModel,
    MemoryExperience,
    MemoryLongTermMemoryIndex,
    MemoryPersonaEvolutionLog,
    MemoryPersonaState,
    MemorySessionInsight,
    MemoryShortTermMemory,
    MemoryTopicState,
    MemoryTurnRecord,
)
from .types import (
    Experience,
    LongTermMemoryIndex,
    PersonaEvolutionLog,
    PersonaState,
    ScopeType,
    SessionInsight,
    ShortTermMemory,
    TopicState,
    TurnRecord,
)


class MemoryStore:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        config: MemoryConfig | None = None,
    ) -> None:
        self.config = config or get_memory_config()
        self.db_path = (
            Path(db_path) if db_path is not None else self.config.storage.sqlite_path
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_url = f"sqlite+aiosqlite:///{self.db_path.as_posix()}"
        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            future=True,
            connect_args={"timeout": 30},
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.inited = False

    @asynccontextmanager
    async def get_db(self):
        if not self.inited:
            await self.initialize()
        async with self.async_session() as session:
            yield session

    async def initialize(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(BaseMemoryModel.metadata.create_all)
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA cache_size=20000"))
            await conn.execute(text("PRAGMA temp_store=MEMORY"))
            await conn.execute(text("PRAGMA mmap_size=134217728"))
            await conn.execute(text("PRAGMA optimize"))
            await conn.commit()
        self.inited = True

    async def close(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> bool:
        try:
            async with self.get_db() as session:
                result = await session.execute(text("SELECT 1"))
                return bool(result.scalar_one())
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory store ping failed: %s", exc)
            return False

    async def save_turn_record(self, record: TurnRecord) -> TurnRecord:
        async with self.get_db() as session:
            async with session.begin():
                result = await session.execute(
                    select(MemoryTurnRecord).where(
                        col(MemoryTurnRecord.turn_id) == record.turn_id
                    )
                )
                entity = result.scalar_one_or_none()
                if entity is None:
                    entity = MemoryTurnRecord(
                        turn_id=record.turn_id,
                        created_at=record.created_at or datetime.now(UTC),
                    )
                    session.add(entity)

                entity.umo = record.umo
                entity.conversation_id = record.conversation_id
                entity.platform_id = record.platform_id
                entity.session_id = record.session_id
                entity.user_message = record.user_message
                entity.assistant_message = record.assistant_message
                entity.message_timestamp = record.message_timestamp
                entity.source_refs = list(record.source_refs)

                await session.flush()
                await session.refresh(entity)
                return self._to_turn_record(entity)

    async def get_turn_record(self, turn_id: str) -> TurnRecord | None:
        async with self.get_db() as session:
            result = await session.execute(
                select(MemoryTurnRecord).where(col(MemoryTurnRecord.turn_id) == turn_id)
            )
            entity = result.scalar_one_or_none()
            return self._to_turn_record(entity) if entity else None

    async def get_recent_turn_records(
        self,
        umo: str,
        limit: int,
        conversation_id: str | None = None,
    ) -> list[TurnRecord]:
        async with self.get_db() as session:
            stmt = select(MemoryTurnRecord).where(col(MemoryTurnRecord.umo) == umo)
            if conversation_id is not None:
                stmt = stmt.where(
                    col(MemoryTurnRecord.conversation_id) == conversation_id
                )
            stmt = stmt.order_by(desc(MemoryTurnRecord.message_timestamp)).limit(limit)
            result = await session.execute(stmt)
            return [self._to_turn_record(item) for item in result.scalars().all()]

    async def upsert_topic_state(self, state: TopicState) -> TopicState:
        conversation_key = self._conversation_key(state.conversation_id)
        async with self.get_db() as session:
            async with session.begin():
                entity = await self._get_topic_state_entity(
                    session,
                    state.umo,
                    conversation_key,
                )
                if entity is None:
                    entity = MemoryTopicState(
                        umo=state.umo,
                        conversation_id=conversation_key,
                    )
                    session.add(entity)

                entity.current_topic = state.current_topic
                entity.topic_summary = state.topic_summary
                entity.topic_confidence = self._clamp_score(state.topic_confidence)
                entity.last_active_at = state.last_active_at

                await session.flush()
                await session.refresh(entity)
                return self._to_topic_state(entity)

    async def get_topic_state(
        self,
        umo: str,
        conversation_id: str | None,
    ) -> TopicState | None:
        async with self.get_db() as session:
            entity = await self._get_topic_state_entity(
                session,
                umo,
                self._conversation_key(conversation_id),
            )
            return self._to_topic_state(entity) if entity else None

    async def upsert_short_term_memory(
        self,
        memory: ShortTermMemory,
    ) -> ShortTermMemory:
        conversation_key = self._conversation_key(memory.conversation_id)
        async with self.get_db() as session:
            async with session.begin():
                entity = await self._get_short_term_memory_entity(
                    session,
                    memory.umo,
                    conversation_key,
                )
                if entity is None:
                    entity = MemoryShortTermMemory(
                        umo=memory.umo,
                        conversation_id=conversation_key,
                    )
                    session.add(entity)

                entity.short_summary = memory.short_summary
                entity.active_focus = memory.active_focus
                entity.updated_at = memory.updated_at

                await session.flush()
                await session.refresh(entity)
                return self._to_short_term_memory(entity)

    async def get_short_term_memory(
        self,
        umo: str,
        conversation_id: str | None,
    ) -> ShortTermMemory | None:
        async with self.get_db() as session:
            entity = await self._get_short_term_memory_entity(
                session,
                umo,
                self._conversation_key(conversation_id),
            )
            return self._to_short_term_memory(entity) if entity else None

    async def save_session_insight(self, insight: SessionInsight) -> SessionInsight:
        async with self.get_db() as session:
            async with session.begin():
                result = await session.execute(
                    select(MemorySessionInsight).where(
                        col(MemorySessionInsight.insight_id) == insight.insight_id
                    )
                )
                entity = result.scalar_one_or_none()
                if entity is None:
                    entity = MemorySessionInsight(
                        insight_id=insight.insight_id,
                        created_at=insight.created_at or datetime.now(UTC),
                    )
                    session.add(entity)

                entity.umo = insight.umo
                entity.conversation_id = insight.conversation_id
                entity.window_start_at = insight.window_start_at
                entity.window_end_at = insight.window_end_at
                entity.topic_summary = insight.topic_summary
                entity.progress_summary = insight.progress_summary
                entity.summary_text = insight.summary_text

                await session.flush()
                await session.refresh(entity)
                return self._to_session_insight(entity)

    async def get_latest_session_insight(
        self,
        umo: str,
        conversation_id: str | None,
    ) -> SessionInsight | None:
        async with self.get_db() as session:
            stmt = select(MemorySessionInsight).where(
                col(MemorySessionInsight.umo) == umo
            )
            if conversation_id is None:
                stmt = stmt.where(col(MemorySessionInsight.conversation_id).is_(None))
            else:
                stmt = stmt.where(
                    col(MemorySessionInsight.conversation_id) == conversation_id
                )
            stmt = stmt.order_by(desc(MemorySessionInsight.window_end_at)).limit(1)
            result = await session.execute(stmt)
            entity = result.scalar_one_or_none()
            return self._to_session_insight(entity) if entity else None

    async def save_experience(self, experience: Experience) -> Experience:
        async with self.get_db() as session:
            async with session.begin():
                result = await session.execute(
                    select(MemoryExperience).where(
                        col(MemoryExperience.experience_id) == experience.experience_id
                    )
                )
                entity = result.scalar_one_or_none()
                if entity is None:
                    entity = MemoryExperience(
                        experience_id=experience.experience_id,
                        created_at=experience.created_at or datetime.now(UTC),
                    )
                    session.add(entity)

                entity.umo = experience.umo
                entity.conversation_id = experience.conversation_id
                entity.scope_type = self._enum_value(experience.scope_type)
                entity.scope_id = experience.scope_id
                entity.event_time = experience.event_time
                entity.category = self._enum_value(experience.category)
                entity.summary = experience.summary
                entity.detail_summary = experience.detail_summary
                entity.importance = self._clamp_score(experience.importance)
                entity.confidence = self._clamp_score(experience.confidence)
                entity.source_refs = list(experience.source_refs)
                if experience.updated_at is not None:
                    entity.updated_at = experience.updated_at

                await session.flush()
                await session.refresh(entity)
                return self._to_experience(entity)

    async def list_recent_experiences(
        self,
        umo: str,
        limit: int,
        conversation_id: str | None = None,
    ) -> list[Experience]:
        async with self.get_db() as session:
            stmt = select(MemoryExperience).where(col(MemoryExperience.umo) == umo)
            if conversation_id is not None:
                stmt = stmt.where(
                    col(MemoryExperience.conversation_id) == conversation_id
                )
            stmt = stmt.order_by(desc(MemoryExperience.event_time)).limit(limit)
            result = await session.execute(stmt)
            return [self._to_experience(item) for item in result.scalars().all()]

    async def list_experiences_for_scope(
        self,
        umo: str,
        scope_type: ScopeType | str,
        scope_id: str,
        *,
        ascending: bool = True,
    ) -> list[Experience]:
        async with self.get_db() as session:
            stmt = select(MemoryExperience).where(
                and_(
                    col(MemoryExperience.umo) == umo,
                    col(MemoryExperience.scope_type) == self._enum_value(scope_type),
                    col(MemoryExperience.scope_id) == scope_id,
                )
            )
            order_by = (
                MemoryExperience.event_time
                if ascending
                else desc(MemoryExperience.event_time)
            )
            stmt = stmt.order_by(order_by)
            result = await session.execute(stmt)
            return [self._to_experience(item) for item in result.scalars().all()]

    async def list_experiences_by_time_range(
        self,
        umo: str,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> list[Experience]:
        async with self.get_db() as session:
            conditions = [col(MemoryExperience.umo) == umo]
            if start_at is not None:
                conditions.append(col(MemoryExperience.event_time) >= start_at)
            if end_at is not None:
                conditions.append(col(MemoryExperience.event_time) <= end_at)
            stmt = (
                select(MemoryExperience)
                .where(and_(*conditions))
                .order_by(desc(MemoryExperience.event_time))
            )
            result = await session.execute(stmt)
            return [self._to_experience(item) for item in result.scalars().all()]

    async def list_turn_records_by_time_range(
        self,
        umo: str,
        conversation_id: str | None,
        start_at: datetime | None,
        end_at: datetime | None = None,
    ) -> list[TurnRecord]:
        async with self.get_db() as session:
            conditions = [col(MemoryTurnRecord.umo) == umo]
            if conversation_id is None:
                conditions.append(col(MemoryTurnRecord.conversation_id).is_(None))
            else:
                conditions.append(
                    col(MemoryTurnRecord.conversation_id) == conversation_id
                )
            if start_at is not None:
                conditions.append(col(MemoryTurnRecord.message_timestamp) >= start_at)
            if end_at is not None:
                conditions.append(col(MemoryTurnRecord.message_timestamp) <= end_at)
            stmt = (
                select(MemoryTurnRecord)
                .where(and_(*conditions))
                .order_by(MemoryTurnRecord.message_timestamp)
            )
            result = await session.execute(stmt)
            return [self._to_turn_record(item) for item in result.scalars().all()]

    async def upsert_long_term_memory_index(
        self,
        memory: LongTermMemoryIndex,
    ) -> LongTermMemoryIndex:
        async with self.get_db() as session:
            async with session.begin():
                result = await session.execute(
                    select(MemoryLongTermMemoryIndex).where(
                        col(MemoryLongTermMemoryIndex.memory_id) == memory.memory_id
                    )
                )
                entity = result.scalar_one_or_none()
                if entity is None:
                    entity = MemoryLongTermMemoryIndex(
                        memory_id=memory.memory_id,
                        created_at=memory.created_at or datetime.now(UTC),
                    )
                    session.add(entity)

                entity.umo = memory.umo
                entity.scope_type = self._enum_value(memory.scope_type)
                entity.scope_id = memory.scope_id
                entity.summary = memory.summary
                entity.doc_path = memory.doc_path
                entity.importance = self._clamp_score(memory.importance)
                entity.confidence = self._clamp_score(memory.confidence)
                entity.tags = list(memory.tags)
                entity.source_refs = list(memory.source_refs)
                if memory.updated_at is not None:
                    entity.updated_at = memory.updated_at

                await session.flush()
                await session.refresh(entity)
                return self._to_long_term_memory_index(entity)

    async def list_long_term_memory_indexes(
        self,
        umo: str,
        limit: int,
    ) -> list[LongTermMemoryIndex]:
        async with self.get_db() as session:
            stmt = (
                select(MemoryLongTermMemoryIndex)
                .where(col(MemoryLongTermMemoryIndex.umo) == umo)
                .order_by(desc(MemoryLongTermMemoryIndex.updated_at))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [
                self._to_long_term_memory_index(item) for item in result.scalars().all()
            ]

    async def upsert_persona_state(self, state: PersonaState) -> PersonaState:
        async with self.get_db() as session:
            async with session.begin():
                result = await session.execute(
                    select(MemoryPersonaState).where(
                        and_(
                            col(MemoryPersonaState.scope_type)
                            == self._enum_value(state.scope_type),
                            col(MemoryPersonaState.scope_id) == state.scope_id,
                        )
                    )
                )
                entity = result.scalar_one_or_none()
                if entity is None:
                    entity = MemoryPersonaState(state_id=state.state_id)
                    session.add(entity)

                entity.scope_type = self._enum_value(state.scope_type)
                entity.scope_id = state.scope_id
                entity.persona_id = state.persona_id
                entity.familiarity = self._clamp_score(state.familiarity)
                entity.trust = self._clamp_score(state.trust)
                entity.warmth = self._clamp_score(state.warmth)
                entity.formality_preference = self._clamp_score(
                    state.formality_preference
                )
                entity.directness_preference = self._clamp_score(
                    state.directness_preference
                )
                entity.updated_at = state.updated_at or datetime.now(UTC)

                await session.flush()
                await session.refresh(entity)
                return self._to_persona_state(entity)

    async def get_persona_state(
        self,
        scope_type: ScopeType | str,
        scope_id: str,
    ) -> PersonaState | None:
        async with self.get_db() as session:
            result = await session.execute(
                select(MemoryPersonaState).where(
                    and_(
                        col(MemoryPersonaState.scope_type)
                        == self._enum_value(scope_type),
                        col(MemoryPersonaState.scope_id) == scope_id,
                    )
                )
            )
            entity = result.scalar_one_or_none()
            return self._to_persona_state(entity) if entity else None

    async def save_persona_evolution_log(
        self,
        log: PersonaEvolutionLog,
    ) -> PersonaEvolutionLog:
        async with self.get_db() as session:
            async with session.begin():
                result = await session.execute(
                    select(MemoryPersonaEvolutionLog).where(
                        col(MemoryPersonaEvolutionLog.log_id) == log.log_id
                    )
                )
                entity = result.scalar_one_or_none()
                if entity is None:
                    entity = MemoryPersonaEvolutionLog(
                        log_id=log.log_id,
                        created_at=log.created_at or datetime.now(UTC),
                    )
                    session.add(entity)

                entity.scope_type = self._enum_value(log.scope_type)
                entity.scope_id = log.scope_id
                entity.before_state = log.before_state
                entity.after_state = log.after_state
                entity.reason = log.reason
                entity.source_refs = list(log.source_refs)

                await session.flush()
                await session.refresh(entity)
                return self._to_persona_evolution_log(entity)

    async def _get_topic_state_entity(
        self,
        session: AsyncSession,
        umo: str,
        conversation_id: str,
    ) -> MemoryTopicState | None:
        result = await session.execute(
            select(MemoryTopicState).where(
                and_(
                    col(MemoryTopicState.umo) == umo,
                    col(MemoryTopicState.conversation_id) == conversation_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def _get_short_term_memory_entity(
        self,
        session: AsyncSession,
        umo: str,
        conversation_id: str,
    ) -> MemoryShortTermMemory | None:
        result = await session.execute(
            select(MemoryShortTermMemory).where(
                and_(
                    col(MemoryShortTermMemory.umo) == umo,
                    col(MemoryShortTermMemory.conversation_id) == conversation_id,
                )
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _conversation_key(conversation_id: str | None) -> str:
        return conversation_id or ""

    @staticmethod
    def _conversation_value(conversation_id: str) -> str | None:
        return conversation_id or None

    @staticmethod
    def _clamp_score(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _enum_value(value: ScopeType | str) -> str:
        return value.value if hasattr(value, "value") else str(value)

    def _to_turn_record(self, entity: MemoryTurnRecord) -> TurnRecord:
        return TurnRecord(
            turn_id=entity.turn_id,
            umo=entity.umo,
            conversation_id=entity.conversation_id,
            platform_id=entity.platform_id,
            session_id=entity.session_id,
            user_message=dict(entity.user_message or {}),
            assistant_message=dict(entity.assistant_message or {}),
            message_timestamp=entity.message_timestamp,
            source_refs=list(entity.source_refs or []),
            created_at=entity.created_at,
        )

    def _to_topic_state(self, entity: MemoryTopicState) -> TopicState:
        return TopicState(
            umo=entity.umo,
            conversation_id=self._conversation_value(entity.conversation_id),
            current_topic=entity.current_topic,
            topic_summary=entity.topic_summary,
            topic_confidence=entity.topic_confidence,
            last_active_at=entity.last_active_at,
        )

    def _to_short_term_memory(
        self,
        entity: MemoryShortTermMemory,
    ) -> ShortTermMemory:
        return ShortTermMemory(
            umo=entity.umo,
            conversation_id=self._conversation_value(entity.conversation_id),
            short_summary=entity.short_summary,
            active_focus=entity.active_focus,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_session_insight(entity: MemorySessionInsight) -> SessionInsight:
        return SessionInsight(
            insight_id=entity.insight_id,
            umo=entity.umo,
            conversation_id=entity.conversation_id,
            window_start_at=entity.window_start_at,
            window_end_at=entity.window_end_at,
            topic_summary=entity.topic_summary,
            progress_summary=entity.progress_summary,
            summary_text=entity.summary_text,
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_experience(entity: MemoryExperience) -> Experience:
        return Experience(
            experience_id=entity.experience_id,
            umo=entity.umo,
            conversation_id=entity.conversation_id,
            scope_type=entity.scope_type,
            scope_id=entity.scope_id,
            event_time=entity.event_time,
            category=entity.category,
            summary=entity.summary,
            detail_summary=entity.detail_summary,
            importance=entity.importance,
            confidence=entity.confidence,
            source_refs=list(entity.source_refs or []),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_long_term_memory_index(
        entity: MemoryLongTermMemoryIndex,
    ) -> LongTermMemoryIndex:
        return LongTermMemoryIndex(
            memory_id=entity.memory_id,
            umo=entity.umo,
            scope_type=entity.scope_type,
            scope_id=entity.scope_id,
            summary=entity.summary,
            doc_path=entity.doc_path,
            importance=entity.importance,
            confidence=entity.confidence,
            tags=list(entity.tags or []),
            source_refs=list(entity.source_refs or []),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_persona_state(entity: MemoryPersonaState) -> PersonaState:
        return PersonaState(
            state_id=entity.state_id,
            scope_type=entity.scope_type,
            scope_id=entity.scope_id,
            persona_id=entity.persona_id,
            familiarity=entity.familiarity,
            trust=entity.trust,
            warmth=entity.warmth,
            formality_preference=entity.formality_preference,
            directness_preference=entity.directness_preference,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_persona_evolution_log(
        entity: MemoryPersonaEvolutionLog,
    ) -> PersonaEvolutionLog:
        return PersonaEvolutionLog(
            log_id=entity.log_id,
            scope_type=entity.scope_type,
            scope_id=entity.scope_id,
            before_state=entity.before_state,
            after_state=entity.after_state,
            reason=entity.reason,
            source_refs=list(entity.source_refs or []),
            created_at=entity.created_at,
        )
