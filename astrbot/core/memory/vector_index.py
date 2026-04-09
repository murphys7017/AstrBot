from __future__ import annotations

import json
from pathlib import Path

from astrbot.core import logger
from astrbot.core.db.vec_db.faiss_impl import FaissVecDB
from astrbot.core.provider.provider import EmbeddingProvider

from .config import MemoryConfig, get_memory_config
from .document_loader import DocumentLoader
from .document_serializer import DocumentSerializer
from .types import LongTermMemoryIndex, ScopeType, VectorSearchHit


class MemoryVectorIndex:
    def __init__(
        self,
        store,
        *,
        config: MemoryConfig | None = None,
        document_loader: DocumentLoader | None = None,
        serializer: DocumentSerializer | None = None,
    ) -> None:
        self.store = store
        self.config = config or get_memory_config()
        self.document_loader = document_loader or DocumentLoader(self.config)
        self.serializer = serializer or DocumentSerializer()
        self.provider_manager = None
        self._vec_db: FaissVecDB | None = None

    def bind_provider_manager(self, provider_manager) -> None:
        self.provider_manager = provider_manager

    async def upsert_long_term_memory(self, memory_id: str) -> None:
        memory = await self.store.get_long_term_memory_index(memory_id)
        if memory is None:
            raise RuntimeError(f"long-term memory `{memory_id}` was not found")
        vec_db = await self._ensure_vec_db()
        document = self.document_loader.load_long_term_document(memory.doc_path)
        search_text = self.serializer.build_search_text(memory, document)
        metadata = self._build_metadata(memory)
        await vec_db.delete(memory.memory_id)
        await vec_db.insert(
            content=search_text,
            metadata=metadata,
            id=memory.memory_id,
        )

    async def delete_long_term_memory(self, memory_id: str) -> None:
        vec_db = await self._ensure_vec_db()
        await vec_db.delete(memory_id)

    async def search_long_term_memories(
        self,
        umo: str,
        query: str,
        top_k: int,
        metadata_filters: dict | None = None,
    ) -> list[VectorSearchHit]:
        vec_db = await self._ensure_vec_db()
        filters = {"umo": umo}
        if metadata_filters:
            filters.update(metadata_filters)
        results = await vec_db.retrieve(
            query=query,
            k=max(1, top_k),
            fetch_k=max(4, top_k * 4),
            rerank=False,
            metadata_filters=filters,
        )
        hits: list[VectorSearchHit] = []
        for result in results:
            doc_id = result.data.get("doc_id")
            metadata_raw = result.data.get("metadata")
            metadata = {}
            if isinstance(metadata_raw, str) and metadata_raw.strip():
                loaded = json.loads(metadata_raw)
                if isinstance(loaded, dict):
                    metadata = loaded
            if isinstance(doc_id, str) and doc_id.strip():
                hits.append(
                    VectorSearchHit(
                        memory_id=doc_id,
                        score=float(result.similarity),
                        metadata=metadata,
                    )
                )
        return hits

    async def _ensure_vec_db(self) -> FaissVecDB:
        if not self.config.vector_index.enabled:
            raise RuntimeError("memory vector index is disabled")
        if self.provider_manager is None:
            raise RuntimeError("memory vector index is not bound to ProviderManager")
        if not self.config.vector_index.provider_id:
            raise RuntimeError("memory vector index provider_id is not configured")
        if self._vec_db is not None:
            return self._vec_db

        embedding_provider = await self.provider_manager.get_provider_by_id(
            self.config.vector_index.provider_id
        )
        if embedding_provider is None:
            raise RuntimeError(
                "memory vector index embedding provider was not found: "
                f"{self.config.vector_index.provider_id}"
            )
        if not isinstance(embedding_provider, EmbeddingProvider):
            raise RuntimeError(
                "memory vector index provider is not an embedding provider: "
                f"{self.config.vector_index.provider_id}"
            )
        if self.config.vector_index.model:
            embedding_provider.set_model(self.config.vector_index.model)

        root_dir = Path(self.config.vector_index.root_dir) / "long_term"
        root_dir.mkdir(parents=True, exist_ok=True)
        vec_db = FaissVecDB(
            doc_store_path=str(root_dir / "doc.db"),
            index_store_path=str(root_dir / "index.faiss"),
            embedding_provider=embedding_provider,
        )
        await vec_db.initialize()
        self._vec_db = vec_db
        logger.info(
            "memory vector index initialized: provider_id=%s model=%s root=%s",
            self.config.vector_index.provider_id,
            self.config.vector_index.model or None,
            root_dir,
        )
        return vec_db

    @staticmethod
    def _build_metadata(memory: LongTermMemoryIndex) -> dict[str, object]:
        return {
            "memory_id": memory.memory_id,
            "umo": memory.umo,
            "scope_type": MemoryVectorIndex._enum_value(memory.scope_type),
            "scope_id": memory.scope_id,
            "category": MemoryVectorIndex._enum_value(memory.category),
            "status": MemoryVectorIndex._enum_value(memory.status),
            "tags": list(memory.tags),
        }

    @staticmethod
    def _enum_value(value: ScopeType | str) -> str:
        return value.value if hasattr(value, "value") else str(value)
