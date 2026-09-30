from __future__ import annotations

import asyncio

from .document_loader import DocumentLoader
from .types import (
    DocumentSearchRequest,
    DocumentSearchResult,
    LongTermMemoryIndex,
    VectorSearchHit,
)
from .vector_index import MemoryVectorIndex


class DocumentSearchService:
    def __init__(
        self,
        store,
        vector_index: MemoryVectorIndex,
        document_loader: DocumentLoader | None = None,
    ) -> None:
        self.store = store
        self.vector_index = vector_index
        self.document_loader = document_loader or DocumentLoader(vector_index.config)

    async def search_long_term_memories(
        self,
        req: DocumentSearchRequest,
    ) -> list[DocumentSearchResult]:
        metadata_filters = self._build_metadata_filters(req)
        hits = await self.vector_index.search_long_term_memories(
            req.canonical_user_id,
            req.query,
            top_k=max(1, req.top_k),
            metadata_filters=metadata_filters,
        )
        indexes = await self._load_indexes([hit.memory_id for hit in hits])
        index_by_id = {index.memory_id: index for index in indexes}
        matched: list[tuple[VectorSearchHit, LongTermMemoryIndex, float]] = []
        for hit in hits:
            index = index_by_id.get(hit.memory_id)
            if index is None:
                continue
            if not self._matches_request_scope(index, req):
                continue
            matched.append((hit, index, hit.score))

        body_texts: dict[str, str] = {}
        if req.include_body and matched:
            loaded_bodies = await asyncio.gather(
                *(
                    self._load_body_text(index)
                    for _, index, _ in matched
                )
            )
            body_texts = {
                index.memory_id: body_text
                for (_, index, _), body_text in zip(
                    matched,
                    loaded_bodies,
                    strict=True,
                )
            }

        hydrated: list[tuple[DocumentSearchResult, float]] = []
        for hit, index, score in matched:
            hydrated.append(
                (
                    DocumentSearchResult(
                        memory_id=index.memory_id,
                        score=score,
                        title=index.title,
                        summary=index.summary,
                        category=index.category,
                        tags=list(index.tags),
                        doc_path=index.doc_path,
                        body_text=body_texts.get(index.memory_id),
                        updated_at=index.updated_at,
                    ),
                    index.importance,
                )
            )
        hydrated.sort(
            key=lambda item: (
                item[0].score,
                item[1],
                item[0].updated_at.isoformat() if item[0].updated_at else "",
                item[0].memory_id,
            ),
            reverse=True,
        )
        return [item[0] for item in hydrated]

    async def _load_indexes(self, memory_ids: list[str]) -> list[LongTermMemoryIndex]:
        batch_loader = getattr(self.store, "get_long_term_memory_indexes", None)
        if callable(batch_loader):
            return await batch_loader(memory_ids)
        indexes = await asyncio.gather(
            *(self.store.get_long_term_memory_index(memory_id) for memory_id in memory_ids)
        )
        return [index for index in indexes if index is not None]

    async def _load_body_text(self, index: LongTermMemoryIndex) -> str:
        document = await asyncio.to_thread(
            self.document_loader.load_long_term_document,
            index.doc_path,
        )
        return self.document_loader.extract_body_text(document)

    def _matches_request_scope(
        self,
        index: LongTermMemoryIndex,
        req: DocumentSearchRequest,
    ) -> bool:
        if (
            req.canonical_user_id is not None
            and index.canonical_user_id != req.canonical_user_id
        ):
            return False
        if (
            req.scope_type is not None
            and self._enum_value(index.scope_type) != self._enum_value(req.scope_type)
        ):
            return False
        return req.scope_id is None or index.scope_id == req.scope_id

    def _build_metadata_filters(self, req: DocumentSearchRequest) -> dict[str, object]:
        filters: dict[str, object] = {}
        if req.scope_type is not None:
            filters["scope_type"] = self._enum_value(req.scope_type)
        if req.scope_id is not None:
            filters["scope_id"] = req.scope_id
        if req.category is not None:
            filters["category"] = self._enum_value(req.category)
        return filters

    @staticmethod
    def _enum_value(value: str) -> str:
        return value.value if hasattr(value, "value") else str(value)
