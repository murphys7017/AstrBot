from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from astrbot.core import logger

from .document_loader import DocumentLoader
from .store import MemoryStore
from .types import (
    ExperienceCategory,
    JsonDict,
    LongTermMemoryDocument,
    LongTermMemoryIndex,
    LongTermMemoryStatus,
    ScopeType,
)
from .vector_index import MemoryVectorIndex


class LongTermMemoryManualService:
    def __init__(
        self,
        store: MemoryStore,
        *,
        document_loader: DocumentLoader | None = None,
        vector_index: MemoryVectorIndex | None = None,
    ) -> None:
        self.store = store
        self.document_loader = document_loader or DocumentLoader(store.config)
        self.vector_index = vector_index

    def bind_provider_manager(self, provider_manager) -> None:
        if self.vector_index is not None:
            self.vector_index.bind_provider_manager(provider_manager)

    async def upsert_memory_from_document(
        self,
        doc_path: Path | str,
    ) -> LongTermMemoryIndex:
        document = self.document_loader.load_long_term_document(doc_path)
        return await self._upsert_document(document)

    async def upsert_memory_from_payload(
        self,
        payload: JsonDict,
    ) -> LongTermMemoryIndex:
        document = self._document_from_payload(payload)
        return await self._upsert_document(document)

    async def _upsert_document(
        self,
        document: LongTermMemoryDocument,
    ) -> LongTermMemoryIndex:
        self._validate_document(document)
        await self._ensure_vector_index_ready()
        normalized_doc = LongTermMemoryDocument(
            memory_id=document.memory_id.strip(),
            umo=document.umo.strip(),
            scope_type=self._validated_scope_type(document.scope_type),
            scope_id=document.scope_id.strip(),
            category=self._validated_category(document.category),
            status=self._validated_status(document.status),
            title=document.title.strip(),
            summary=document.summary.strip(),
            detail_summary=document.detail_summary.strip()
            if isinstance(document.detail_summary, str)
            and document.detail_summary.strip()
            else None,
            importance=float(document.importance),
            confidence=float(document.confidence),
            supporting_experiences=[
                item.strip()
                for item in document.supporting_experiences
                if isinstance(item, str) and item.strip()
            ],
            updates=[item for item in document.updates if isinstance(item, dict)],
            source_refs=[
                str(item).strip() for item in document.source_refs if str(item).strip()
            ],
            tags=[str(item).strip() for item in document.tags if str(item).strip()],
            first_event_at=document.first_event_at,
            last_event_at=document.last_event_at,
            created_at=document.created_at,
            updated_at=document.updated_at or datetime.now(UTC),
        )
        normalized_path = self.document_loader.build_long_term_doc_path(normalized_doc)
        existing = await self.store.get_long_term_memory_index(normalized_doc.memory_id)
        created_at = normalized_doc.created_at or (
            existing.created_at if existing is not None else datetime.now(UTC)
        )
        updated_at = normalized_doc.updated_at or datetime.now(UTC)
        normalized_doc.created_at = created_at
        normalized_doc.updated_at = updated_at
        index = LongTermMemoryIndex(
            memory_id=normalized_doc.memory_id,
            umo=normalized_doc.umo,
            scope_type=normalized_doc.scope_type,
            scope_id=normalized_doc.scope_id,
            category=normalized_doc.category,
            title=normalized_doc.title,
            summary=normalized_doc.summary,
            status=normalized_doc.status,
            doc_path=str(normalized_path),
            importance=normalized_doc.importance,
            confidence=normalized_doc.confidence,
            tags=list(normalized_doc.tags),
            source_refs=list(normalized_doc.source_refs),
            first_event_at=normalized_doc.first_event_at,
            last_event_at=normalized_doc.last_event_at,
            created_at=created_at,
            updated_at=updated_at,
        )
        prepared_write = self.document_loader.prepare_long_term_document_write(
            normalized_doc,
            doc_path=normalized_path,
        )
        write_applied = False
        try:
            self.document_loader.apply_prepared_write(prepared_write)
            write_applied = True
            persisted = await self.store.upsert_long_term_memory_index(index)
        except Exception:
            if write_applied:
                self.document_loader.rollback_prepared_write(prepared_write)
            else:
                self.document_loader.cleanup_prepared_write(prepared_write)
            raise
        finally:
            self.document_loader.cleanup_prepared_write(prepared_write)

        await self._refresh_vector_index(persisted.memory_id)
        logger.info(
            "memory long-term manual import finished: memory_id=%s path=%s",
            persisted.memory_id,
            normalized_path,
        )
        return persisted

    def _document_from_payload(self, payload: JsonDict) -> LongTermMemoryDocument:
        def _as_string_list(value: object) -> list[str]:
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        def _as_updates(value: object) -> list[JsonDict]:
            if not isinstance(value, list):
                return []
            return [item for item in value if isinstance(item, dict)]

        return LongTermMemoryDocument(
            memory_id=str(payload.get("memory_id", "")).strip(),
            umo=str(payload.get("umo", "")).strip(),
            scope_type=str(payload.get("scope_type", "")).strip(),
            scope_id=str(payload.get("scope_id", "")).strip(),
            category=str(payload.get("category", "")).strip(),
            status=str(payload.get("status", "")).strip(),
            title=str(payload.get("title", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            detail_summary=(
                str(payload.get("detail_summary")).strip()
                if payload.get("detail_summary") is not None
                else None
            ),
            importance=payload.get("importance", 0.0),  # type: ignore[arg-type]
            confidence=payload.get("confidence", 0.0),  # type: ignore[arg-type]
            supporting_experiences=_as_string_list(
                payload.get("supporting_experiences")
            ),
            updates=_as_updates(payload.get("updates")),
            source_refs=_as_string_list(payload.get("source_refs")),
            tags=_as_string_list(payload.get("tags")),
            first_event_at=self._coerce_datetime(payload.get("first_event_at")),
            last_event_at=self._coerce_datetime(payload.get("last_event_at")),
            created_at=self._coerce_datetime(payload.get("created_at")),
            updated_at=self._coerce_datetime(payload.get("updated_at")),
        )

    def _validate_document(self, document: LongTermMemoryDocument) -> None:
        if not document.memory_id.strip():
            raise ValueError(
                "long-term manual import missing required field `memory_id`"
            )
        if not document.umo.strip():
            raise ValueError("long-term manual import missing required field `umo`")
        if not document.scope_id.strip():
            raise ValueError(
                "long-term manual import missing required field `scope_id`"
            )
        if not document.title.strip():
            raise ValueError("long-term manual import missing required field `title`")
        if not document.summary.strip():
            raise ValueError("long-term manual import missing required `Summary`")
        self._validated_scope_type(document.scope_type)
        self._validated_category(document.category)
        self._validated_status(document.status)
        for field_name, value in (
            ("importance", document.importance),
            ("confidence", document.confidence),
        ):
            if not isinstance(value, int | float):
                raise ValueError(
                    f"long-term manual import field `{field_name}` must be numeric"
                )
            score = float(value)
            if not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"long-term manual import field `{field_name}` must be between 0 and 1"
                )

    @staticmethod
    def _validated_scope_type(value: ScopeType | str) -> str:
        raw = value.value if hasattr(value, "value") else str(value)
        valid_values = {item.value for item in ScopeType}
        if raw not in valid_values:
            raise ValueError(f"long-term manual import invalid scope_type `{raw}`")
        return raw

    @staticmethod
    def _validated_category(value: ExperienceCategory | str) -> str:
        raw = value.value if hasattr(value, "value") else str(value)
        valid_values = {item.value for item in ExperienceCategory}
        if raw not in valid_values:
            raise ValueError(f"long-term manual import invalid category `{raw}`")
        return raw

    @staticmethod
    def _validated_status(value: LongTermMemoryStatus | str) -> str:
        raw = value.value if hasattr(value, "value") else str(value)
        valid_values = {item.value for item in LongTermMemoryStatus}
        if raw not in valid_values:
            raise ValueError(f"long-term manual import invalid status `{raw}`")
        return raw

    @staticmethod
    def _coerce_datetime(value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("long-term manual import datetime field must be ISO string")

    async def _refresh_vector_index(self, memory_id: str) -> None:
        if self.vector_index is None or not self.store.config.vector_index.enabled:
            return
        await self.vector_index.upsert_long_term_memory(memory_id)

    async def _ensure_vector_index_ready(self) -> None:
        if self.vector_index is None or not self.store.config.vector_index.enabled:
            return
        await self.vector_index.ensure_ready()
