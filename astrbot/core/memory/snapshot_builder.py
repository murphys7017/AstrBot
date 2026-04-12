from __future__ import annotations

from astrbot.core import logger

from .document_search import DocumentSearchService
from .store import MemoryStore
from .types import (
    DocumentSearchRequest,
    Experience,
    LongTermMemoryIndex,
    MemorySnapshot,
    ScopeType,
)

SNAPSHOT_EXPERIENCE_LIMIT = 10
SNAPSHOT_LONG_TERM_LIMIT = 10


class MemorySnapshotBuilder:
    def __init__(
        self,
        store: MemoryStore,
        document_search_service: DocumentSearchService | None = None,
    ) -> None:
        self.store = store
        self.document_search_service = document_search_service

    async def build_snapshot(
        self,
        umo: str,
        conversation_id: str | None,
        query: str | None = None,
    ) -> MemorySnapshot:
        topic_state = await self.store.get_topic_state(umo, conversation_id)
        short_term_memory = await self.store.get_short_term_memory(umo, conversation_id)
        recent_turns = await self.store.get_recent_turn_records(
            umo,
            limit=1,
            conversation_id=conversation_id,
        )
        latest_turn = recent_turns[0] if recent_turns else None
        canonical_user_id = latest_turn.canonical_user_id if latest_turn else None
        platform_user_key = latest_turn.platform_user_key if latest_turn else None
        experiences = []
        long_term_memories = []
        persona_state = None
        if canonical_user_id:
            long_term_memories = await self._load_snapshot_long_term_memories(
                umo=umo,
                canonical_user_id=canonical_user_id,
                conversation_id=conversation_id,
                query=query,
            )
            experiences = await self._load_snapshot_experiences(
                canonical_user_id=canonical_user_id,
                conversation_id=conversation_id,
                query=query,
                long_term_memories=long_term_memories,
            )
            persona_state = await self.store.get_persona_state(
                ScopeType.USER,
                canonical_user_id,
            )
        logger.info(
            "memory snapshot built: umo=%s conversation_id=%s topic_state=%s short_term_memory=%s canonical_user_id=%s experiences=%s long_term_memories=%s persona_state=%s query_present=%s",
            umo,
            conversation_id,
            topic_state is not None,
            short_term_memory is not None,
            canonical_user_id,
            len(experiences),
            len(long_term_memories),
            persona_state is not None,
            query is not None,
        )
        return MemorySnapshot(
            umo=umo,
            conversation_id=conversation_id,
            platform_user_key=platform_user_key,
            canonical_user_id=canonical_user_id,
            topic_state=topic_state,
            short_term_memory=short_term_memory,
            experiences=experiences,
            long_term_memories=long_term_memories,
            persona_state=persona_state,
            debug_meta={"query": query} if query is not None else {},
        )

    async def _load_snapshot_long_term_memories(
        self,
        *,
        umo: str,
        canonical_user_id: str,
        conversation_id: str | None,
        query: str | None,
    ) -> list[LongTermMemoryIndex]:
        if query and self.document_search_service is not None:
            results = await self.document_search_service.search_long_term_memories(
                DocumentSearchRequest(
                    canonical_user_id=canonical_user_id,
                    query=query,
                    umo=umo,
                    conversation_id=conversation_id,
                    scope_type=ScopeType.USER,
                    scope_id=canonical_user_id,
                    top_k=SNAPSHOT_LONG_TERM_LIMIT,
                )
            )
            memories: list[LongTermMemoryIndex] = []
            for item in results:
                memory = await self.store.get_long_term_memory_index(item.memory_id)
                if memory is not None:
                    memories.append(memory)
            return memories

        return await self.store.list_long_term_memory_indexes(
            canonical_user_id,
            SNAPSHOT_LONG_TERM_LIMIT,
            scope_type=ScopeType.USER,
            scope_id=canonical_user_id,
        )

    async def _load_snapshot_experiences(
        self,
        *,
        canonical_user_id: str,
        conversation_id: str | None,
        query: str | None,
        long_term_memories: list[LongTermMemoryIndex],
    ) -> list[Experience]:
        recent_experiences = await self.store.list_recent_experiences(
            canonical_user_id,
            SNAPSHOT_EXPERIENCE_LIMIT,
            conversation_id=conversation_id,
        )
        if not query or not long_term_memories:
            return recent_experiences

        experiences: list[Experience] = []
        seen_experience_ids: set[str] = set()
        for memory in long_term_memories:
            links = await self.store.list_long_term_memory_links(memory.memory_id)
            for link in reversed(links):
                if link.experience_id in seen_experience_ids:
                    continue
                experience = await self.store.get_experience(link.experience_id)
                if experience is None:
                    continue
                seen_experience_ids.add(experience.experience_id)
                experiences.append(experience)
                if len(experiences) >= SNAPSHOT_EXPERIENCE_LIMIT:
                    return experiences

        for experience in recent_experiences:
            if experience.experience_id in seen_experience_ids:
                continue
            seen_experience_ids.add(experience.experience_id)
            experiences.append(experience)
            if len(experiences) >= SNAPSHOT_EXPERIENCE_LIMIT:
                break
        return experiences
