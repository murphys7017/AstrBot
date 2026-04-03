from __future__ import annotations

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
