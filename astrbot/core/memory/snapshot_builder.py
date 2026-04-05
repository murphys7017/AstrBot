from __future__ import annotations

from astrbot.core import logger

from .store import MemoryStore
from .types import MemorySnapshot


class MemorySnapshotBuilder:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def build_snapshot(
        self,
        umo: str,
        conversation_id: str | None,
        query: str | None = None,
    ) -> MemorySnapshot:
        topic_state = await self.store.get_topic_state(umo, conversation_id)
        short_term_memory = await self.store.get_short_term_memory(umo, conversation_id)
        logger.info(
            "memory snapshot built: umo=%s conversation_id=%s topic_state=%s short_term_memory=%s query_present=%s",
            umo,
            conversation_id,
            topic_state is not None,
            short_term_memory is not None,
            query is not None,
        )
        return MemorySnapshot(
            umo=umo,
            conversation_id=conversation_id,
            topic_state=topic_state,
            short_term_memory=short_term_memory,
            experiences=[],
            long_term_memories=[],
            persona_state=None,
            debug_meta={"query": query} if query is not None else {},
        )
