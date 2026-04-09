from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from astrbot.core import logger

from .analyzer_manager import MemoryAnalyzerManager
from .analyzers.base import (
    MemoryAnalyzerConfigurationError,
    MemoryAnalyzerExecutionError,
)
from .config import MemoryAnalysisConfig, MemoryLongTermConfig
from .document_loader import DocumentLoader
from .store import MemoryStore
from .types import (
    Experience,
    ExperienceCategory,
    LongTermMemoryDocument,
    LongTermMemoryIndex,
    LongTermMemoryLink,
    LongTermMemoryLinkRelation,
    LongTermMemoryStatus,
    LongTermPromotionCursor,
    ScopeType,
)
from .vector_index import MemoryVectorIndex

LONG_TERM_PROMOTE_ANALYZER_NAME = "long_term_promote_v1"
LONG_TERM_COMPOSE_ANALYZER_NAME = "long_term_compose_v1"
LONG_TERM_ACTIONS = {"create", "update", "ignore"}
LONG_TERM_STATUS_VALUES = {status.value for status in LongTermMemoryStatus}


class LongTermMemoryService:
    def __init__(
        self,
        store: MemoryStore,
        *,
        analyzer_manager: MemoryAnalyzerManager | None = None,
        analysis_config: MemoryAnalysisConfig | None = None,
        long_term_config: MemoryLongTermConfig | None = None,
        document_loader: DocumentLoader | None = None,
        vector_index: MemoryVectorIndex | None = None,
    ) -> None:
        self.store = store
        self.analyzer_manager = analyzer_manager
        self.analysis_config = analysis_config
        self.long_term_config = long_term_config
        self.document_loader = document_loader or DocumentLoader(store.config)
        self.vector_index = vector_index

    def bind_provider_manager(self, provider_manager) -> None:
        if self.vector_index is not None:
            self.vector_index.bind_provider_manager(provider_manager)

    async def should_run_promotion(
        self,
        umo: str,
        conversation_id: str | None,
    ) -> bool:
        if not self._is_enabled():
            logger.info(
                "memory long-term promotion skipped: disabled umo=%s conversation_id=%s",
                umo,
                conversation_id,
            )
            return False
        scope_type, scope_id = self._resolve_scope(umo, conversation_id)
        cursor = await self.store.get_long_term_promotion_cursor(
            umo,
            scope_type,
            scope_id,
        )
        pending_experiences = await self.store.list_pending_experiences_for_scope(
            umo,
            scope_type,
            scope_id,
            cursor,
        )
        threshold = max(1, int(self.long_term_config.min_pending_experiences))
        should_run = len(pending_experiences) >= threshold
        logger.info(
            "memory long-term promotion check: umo=%s scope_type=%s scope_id=%s pending_experiences=%s threshold=%s should_run=%s",
            umo,
            self._enum_value(scope_type),
            scope_id,
            len(pending_experiences),
            threshold,
            should_run,
        )
        return should_run

    async def run_promotion(
        self,
        umo: str,
        conversation_id: str | None,
    ) -> list[LongTermMemoryIndex]:
        if not self._is_enabled():
            return []
        if self.analyzer_manager is None:
            raise RuntimeError("long-term promotion requested without analyzer manager")

        scope_type, scope_id = self._resolve_scope(umo, conversation_id)
        cursor = await self.store.get_long_term_promotion_cursor(
            umo,
            scope_type,
            scope_id,
        )
        pending_experiences = await self.store.list_pending_experiences_for_scope(
            umo,
            scope_type,
            scope_id,
            cursor,
        )
        threshold = max(1, int(self.long_term_config.min_pending_experiences))
        if len(pending_experiences) < threshold:
            return []
        candidate_experiences = [
            item
            for item in pending_experiences
            if item.importance >= self.long_term_config.min_experience_importance
        ]
        if not candidate_experiences:
            latest_pending = pending_experiences[-1]
            await self.store.upsert_long_term_promotion_cursor(
                LongTermPromotionCursor(
                    cursor_id=cursor.cursor_id
                    if cursor is not None
                    else str(uuid.uuid4()),
                    umo=umo,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    last_processed_created_at=latest_pending.created_at,
                    last_processed_experience_id=latest_pending.experience_id,
                    updated_at=datetime.now(UTC),
                )
            )
            logger.info(
                "memory long-term promotion skipped after filtering: umo=%s scope_type=%s scope_id=%s pending=%s threshold=%s min_importance=%s",
                umo,
                self._enum_value(scope_type),
                scope_id,
                len(pending_experiences),
                threshold,
                self.long_term_config.min_experience_importance,
            )
            return []

        existing_memories = await self.store.list_long_term_memory_indexes(
            umo,
            limit=0,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        actions = await self._build_promotion_actions(
            umo=umo,
            conversation_id=conversation_id,
            pending_experiences=candidate_experiences,
            existing_memories=existing_memories,
        )
        self._validate_promote_batch_constraints(actions, candidate_experiences)
        memory_map = {memory.memory_id: memory for memory in existing_memories}

        pending_memories: list[LongTermMemoryIndex] = []
        links: list[LongTermMemoryLink] = []
        documents_to_refresh: list[tuple[LongTermMemoryDocument, Path]] = []
        now = datetime.now(UTC)
        for action in actions:
            related_experiences = self._resolve_related_experiences(
                action["experience_ids"],
                candidate_experiences,
            )
            if action["action"] == "ignore":
                continue

            existing_memory = None
            existing_document = None
            target_memory_id = action.get("target_memory_id")
            if action["action"] == "update":
                if (
                    not isinstance(target_memory_id, str)
                    or not target_memory_id.strip()
                ):
                    raise MemoryAnalyzerExecutionError(
                        "long_term_promote update action missing target_memory_id"
                    )
                existing_memory = memory_map.get(target_memory_id)
                if existing_memory is None:
                    raise MemoryAnalyzerExecutionError(
                        f"long_term_promote target memory `{target_memory_id}` was not found"
                    )
                existing_document = self.document_loader.load_long_term_document(
                    existing_memory.doc_path
                )

            compose_data = await self._compose_memory(
                umo=umo,
                conversation_id=conversation_id,
                action=action,
                related_experiences=related_experiences,
                existing_memory=existing_memory,
                existing_document=existing_document,
            )

            memory_id = (
                existing_memory.memory_id
                if existing_memory is not None
                else str(uuid.uuid4())
            )
            doc_path = (
                Path(existing_memory.doc_path)
                if existing_memory is not None
                else self._build_doc_path(umo, scope_type, memory_id)
            )
            created_at = existing_memory.created_at if existing_memory else now
            existing_updates = (
                list(existing_document.updates) if existing_document else []
            )
            existing_supporting = (
                list(existing_document.supporting_experiences)
                if existing_document
                else []
            )
            updates = [
                *existing_updates,
                {
                    "timestamp": now.isoformat(),
                    "action": action["action"],
                    "summary": compose_data["summary"],
                },
            ]
            supporting_experiences = self._merge_string_list(
                existing_supporting,
                [experience.experience_id for experience in related_experiences],
            )
            source_refs = self._merge_source_refs(
                existing_memory.source_refs if existing_memory else [],
                related_experiences,
            )
            first_event_at = self._resolve_first_event_at(
                existing_memory,
                related_experiences,
            )
            last_event_at = self._resolve_last_event_at(
                existing_memory,
                related_experiences,
            )
            document = LongTermMemoryDocument(
                memory_id=memory_id,
                umo=umo,
                scope_type=scope_type,
                scope_id=scope_id,
                category=compose_data["category"],
                status=compose_data["status"],
                title=compose_data["title"],
                summary=compose_data["summary"],
                detail_summary=compose_data["detail_summary"],
                importance=compose_data["importance"],
                confidence=compose_data["confidence"],
                supporting_experiences=supporting_experiences,
                updates=updates,
                source_refs=source_refs,
                tags=list(compose_data["tags"]),
                first_event_at=first_event_at,
                last_event_at=last_event_at,
                created_at=created_at,
                updated_at=now,
            )
            documents_to_refresh.append((document, doc_path))
            pending_memories.append(
                LongTermMemoryIndex(
                    memory_id=memory_id,
                    umo=umo,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    category=compose_data["category"],
                    title=compose_data["title"],
                    summary=compose_data["summary"],
                    status=compose_data["status"],
                    doc_path=str(doc_path),
                    importance=compose_data["importance"],
                    confidence=compose_data["confidence"],
                    tags=list(compose_data["tags"]),
                    source_refs=source_refs,
                    first_event_at=first_event_at,
                    last_event_at=last_event_at,
                    created_at=created_at,
                    updated_at=now,
                )
            )

            relation_type = (
                LongTermMemoryLinkRelation.SEED
                if action["action"] == "create"
                else LongTermMemoryLinkRelation.UPDATE
            )
            for experience in related_experiences:
                links.append(
                    LongTermMemoryLink(
                        link_id=str(uuid.uuid4()),
                        memory_id=memory_id,
                        experience_id=experience.experience_id,
                        relation_type=relation_type,
                        created_at=now,
                    )
                )

        latest_pending = pending_experiences[-1]
        cursor_to_save = LongTermPromotionCursor(
            cursor_id=cursor.cursor_id if cursor is not None else str(uuid.uuid4()),
            umo=umo,
            scope_type=scope_type,
            scope_id=scope_id,
            last_processed_created_at=latest_pending.created_at,
            last_processed_experience_id=latest_pending.experience_id,
            updated_at=now,
        )
        persisted_indexes, _, _ = await self.store.persist_long_term_promotion_batch(
            pending_memories,
            links,
            cursor_to_save,
        )
        refreshed_memory_ids = self._refresh_documents(documents_to_refresh)
        refreshed_indexes = [
            index
            for index in persisted_indexes
            if index.memory_id in refreshed_memory_ids
        ]
        await self._refresh_vector_indexes(refreshed_indexes)
        logger.info(
            "memory long-term promotion finished: umo=%s scope_type=%s scope_id=%s memories=%s links=%s refreshed_docs=%s",
            umo,
            self._enum_value(scope_type),
            scope_id,
            len(persisted_indexes),
            len(links),
            len(refreshed_memory_ids),
        )
        return persisted_indexes

    def _is_enabled(self) -> bool:
        return bool(
            self.long_term_config is not None
            and self.long_term_config.enabled
            and self.analysis_config is not None
            and self.analysis_config.enabled
            and self.analyzer_manager is not None
        )

    async def _build_promotion_actions(
        self,
        *,
        umo: str,
        conversation_id: str | None,
        pending_experiences: list[Experience],
        existing_memories: list[LongTermMemoryIndex],
    ) -> list[dict[str, Any]]:
        payload = {
            "pending_experiences_json": json.dumps(
                [self._experience_to_payload(item) for item in pending_experiences],
                ensure_ascii=False,
            ),
            "existing_memories_json": json.dumps(
                [self._memory_to_payload(item) for item in existing_memories],
                ensure_ascii=False,
            ),
        }
        results = await self.analyzer_manager.dispatch_stage(
            "long_term_promote",
            payload=payload,
            umo=umo,
            conversation_id=conversation_id,
        )
        result = results.get(LONG_TERM_PROMOTE_ANALYZER_NAME)
        if result is None:
            raise MemoryAnalyzerConfigurationError(
                "long_term_promote missing required analyzer `long_term_promote_v1`"
            )
        return self._validate_promote_payload(result.data)

    async def _compose_memory(
        self,
        *,
        umo: str,
        conversation_id: str | None,
        action: dict[str, Any],
        related_experiences: list[Experience],
        existing_memory: LongTermMemoryIndex | None,
        existing_document: LongTermMemoryDocument | None,
    ) -> dict[str, Any]:
        existing_memory_payload = {}
        if existing_memory is not None:
            existing_memory_payload = self._memory_to_payload(existing_memory)
            if existing_document is not None:
                existing_memory_payload["detail_summary"] = (
                    existing_document.detail_summary or ""
                )
                existing_memory_payload["updates"] = list(existing_document.updates)
        payload = {
            "promotion_action": action["action"],
            "promotion_category": action["category"],
            "promotion_reason": action["reason"],
            "existing_memory_json": json.dumps(
                existing_memory_payload,
                ensure_ascii=False,
            ),
            "supporting_experiences_json": json.dumps(
                [self._experience_to_payload(item) for item in related_experiences],
                ensure_ascii=False,
            ),
        }
        results = await self.analyzer_manager.dispatch_stage(
            "long_term_compose",
            payload=payload,
            umo=umo,
            conversation_id=conversation_id,
        )
        result = results.get(LONG_TERM_COMPOSE_ANALYZER_NAME)
        if result is None:
            raise MemoryAnalyzerConfigurationError(
                "long_term_compose missing required analyzer `long_term_compose_v1`"
            )
        compose_data = self._validate_compose_payload(result.data)
        compose_data["category"] = action["category"]
        return compose_data

    def _validate_promote_payload(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            raise MemoryAnalyzerExecutionError(
                "long_term_promote returned invalid payload"
            )
        actions = data.get("actions")
        if not isinstance(actions, list):
            raise MemoryAnalyzerExecutionError(
                "long_term_promote missing required field `actions`"
            )
        valid_categories = {category.value for category in ExperienceCategory}
        validated: list[dict[str, Any]] = []
        for item in actions:
            if not isinstance(item, dict):
                raise MemoryAnalyzerExecutionError(
                    "long_term_promote returned invalid action item"
                )
            action = str(item.get("action", "")).strip()
            category = str(item.get("category", "")).strip()
            reason = str(item.get("reason", "")).strip()
            experience_ids = item.get("experience_ids")
            if action not in LONG_TERM_ACTIONS:
                raise MemoryAnalyzerExecutionError(
                    f"long_term_promote returned invalid action `{action}`"
                )
            if category not in valid_categories:
                raise MemoryAnalyzerExecutionError(
                    f"long_term_promote returned invalid category `{category}`"
                )
            if not reason:
                raise MemoryAnalyzerExecutionError(
                    "long_term_promote item missing required field `reason`"
                )
            if not isinstance(experience_ids, list) or not experience_ids:
                raise MemoryAnalyzerExecutionError(
                    "long_term_promote item missing required field `experience_ids`"
                )
            cleaned_experience_ids = [
                str(experience_id).strip()
                for experience_id in experience_ids
                if str(experience_id).strip()
            ]
            if not cleaned_experience_ids:
                raise MemoryAnalyzerExecutionError(
                    "long_term_promote item returned empty `experience_ids`"
                )
            validated.append(
                {
                    "action": action,
                    "target_memory_id": str(item.get("target_memory_id", "")).strip(),
                    "category": category,
                    "reason": reason,
                    "experience_ids": cleaned_experience_ids,
                }
            )
        return validated

    def _validate_promote_batch_constraints(
        self,
        actions: list[dict[str, Any]],
        pending_experiences: list[Experience],
    ) -> None:
        candidate_ids = {
            experience.experience_id
            for experience in pending_experiences
            if experience.experience_id
        }
        consumed_ids: set[str] = set()
        update_targets: set[str] = set()
        for action in actions:
            if action["action"] == "update":
                target_memory_id = action.get("target_memory_id", "")
                if target_memory_id in update_targets:
                    raise MemoryAnalyzerExecutionError(
                        "long_term_promote returned duplicate update target "
                        f"`{target_memory_id}` in one batch"
                    )
                update_targets.add(target_memory_id)
            for experience_id in action["experience_ids"]:
                if experience_id not in candidate_ids:
                    raise MemoryAnalyzerExecutionError(
                        f"long_term_promote referenced unknown experience `{experience_id}`"
                    )
                if experience_id in consumed_ids:
                    raise MemoryAnalyzerExecutionError(
                        "long_term_promote returned duplicate experience coverage "
                        f"for `{experience_id}`"
                    )
                consumed_ids.add(experience_id)
        missing_ids = sorted(candidate_ids - consumed_ids)
        if missing_ids:
            raise MemoryAnalyzerExecutionError(
                "long_term_promote did not cover all candidate experiences: "
                + ", ".join(missing_ids)
            )

    def _validate_compose_payload(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise MemoryAnalyzerExecutionError(
                "long_term_compose returned invalid payload"
            )
        required_text_fields = ("title", "summary", "detail_summary", "status")
        validated: dict[str, Any] = {}
        for field_name in required_text_fields:
            value = data.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise MemoryAnalyzerExecutionError(
                    f"long_term_compose missing required field `{field_name}`"
                )
            validated[field_name] = value.strip()
        tags = data.get("tags")
        if not isinstance(tags, list):
            raise MemoryAnalyzerExecutionError(
                "long_term_compose missing required field `tags`"
            )
        validated["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
        for field_name in ("importance", "confidence"):
            value = data.get(field_name)
            if not isinstance(value, int | float):
                raise MemoryAnalyzerExecutionError(
                    f"long_term_compose missing required field `{field_name}`"
                )
            validated[field_name] = float(value)
        if validated["status"] not in LONG_TERM_STATUS_VALUES:
            raise MemoryAnalyzerExecutionError(
                f"long_term_compose returned invalid status `{validated['status']}`"
            )
        return validated

    @staticmethod
    def _resolve_scope(
        umo: str,
        conversation_id: str | None,
    ) -> tuple[ScopeType, str]:
        if conversation_id is not None:
            return ScopeType.CONVERSATION, conversation_id
        return ScopeType.USER, umo

    @staticmethod
    def _resolve_related_experiences(
        experience_ids: list[str],
        pending_experiences: list[Experience],
    ) -> list[Experience]:
        index = {
            experience.experience_id: experience for experience in pending_experiences
        }
        related: list[Experience] = []
        for experience_id in experience_ids:
            experience = index.get(experience_id)
            if experience is None:
                raise MemoryAnalyzerExecutionError(
                    f"long_term_promote referenced unknown experience `{experience_id}`"
                )
            related.append(experience)
        return related

    def _build_doc_path(
        self,
        umo: str,
        scope_type: ScopeType | str,
        memory_id: str,
    ) -> Path:
        return (
            self.store.config.storage.docs_root
            / self._safe_path_component(umo)
            / self._safe_path_component(self._enum_value(scope_type))
            / f"{self._safe_path_component(memory_id)}.md"
        )

    @staticmethod
    def _merge_string_list(existing: list[str], additions: list[str]) -> list[str]:
        merged = list(existing)
        seen = set(existing)
        for item in additions:
            if item not in seen:
                seen.add(item)
                merged.append(item)
        return merged

    def _merge_source_refs(
        self,
        existing_source_refs: list[str],
        experiences: list[Experience],
    ) -> list[str]:
        merged = list(existing_source_refs)
        seen = set(existing_source_refs)
        for experience in experiences:
            for source_ref in experience.source_refs:
                if source_ref not in seen:
                    seen.add(source_ref)
                    merged.append(source_ref)
        return merged

    @staticmethod
    def _resolve_first_event_at(
        existing_memory: LongTermMemoryIndex | None,
        experiences: list[Experience],
    ) -> datetime | None:
        candidates = [
            experience.event_time for experience in experiences if experience.event_time
        ]
        if existing_memory and existing_memory.first_event_at is not None:
            candidates.append(existing_memory.first_event_at)
        return min(candidates) if candidates else None

    @staticmethod
    def _resolve_last_event_at(
        existing_memory: LongTermMemoryIndex | None,
        experiences: list[Experience],
    ) -> datetime | None:
        candidates = [
            experience.event_time for experience in experiences if experience.event_time
        ]
        if existing_memory and existing_memory.last_event_at is not None:
            candidates.append(existing_memory.last_event_at)
        return max(candidates) if candidates else None

    async def _refresh_vector_indexes(
        self,
        indexes: list[LongTermMemoryIndex],
    ) -> None:
        if self.vector_index is None or not self.store.config.vector_index.enabled:
            return
        for index in indexes:
            try:
                await self.vector_index.upsert_long_term_memory(index.memory_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "memory long-term vector index refresh failed: memory_id=%s error=%s",
                    index.memory_id,
                    exc,
                    exc_info=True,
                )

    def _refresh_documents(
        self,
        documents: list[tuple[LongTermMemoryDocument, Path]],
    ) -> set[str]:
        refreshed_memory_ids: set[str] = set()
        for document, doc_path in documents:
            try:
                self.document_loader.save_long_term_document(
                    document, doc_path=doc_path
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "memory long-term document refresh failed: memory_id=%s path=%s error=%s",
                    document.memory_id,
                    doc_path,
                    exc,
                    exc_info=True,
                )
                continue
            refreshed_memory_ids.add(document.memory_id)
        return refreshed_memory_ids

    @staticmethod
    def _experience_to_payload(experience: Experience) -> dict[str, Any]:
        return {
            "experience_id": experience.experience_id,
            "conversation_id": experience.conversation_id,
            "scope_type": LongTermMemoryService._enum_value(experience.scope_type),
            "scope_id": experience.scope_id,
            "event_time": experience.event_time.isoformat(),
            "category": LongTermMemoryService._enum_value(experience.category),
            "summary": experience.summary,
            "detail_summary": experience.detail_summary or "",
            "importance": experience.importance,
            "confidence": experience.confidence,
            "source_refs": list(experience.source_refs),
        }

    @staticmethod
    def _memory_to_payload(memory: LongTermMemoryIndex) -> dict[str, Any]:
        return {
            "memory_id": memory.memory_id,
            "scope_type": LongTermMemoryService._enum_value(memory.scope_type),
            "scope_id": memory.scope_id,
            "category": LongTermMemoryService._enum_value(memory.category),
            "title": memory.title,
            "summary": memory.summary,
            "status": LongTermMemoryService._enum_value(memory.status),
            "tags": list(memory.tags),
            "importance": memory.importance,
            "confidence": memory.confidence,
            "source_refs": list(memory.source_refs),
            "first_event_at": memory.first_event_at.isoformat()
            if memory.first_event_at
            else "",
            "last_event_at": memory.last_event_at.isoformat()
            if memory.last_event_at
            else "",
        }

    @staticmethod
    def _safe_path_component(value: str) -> str:
        sanitized = "".join(
            char if char.isalnum() or char in "._-" else "_" for char in value
        ).strip("._")
        return sanitized or "unknown"

    @staticmethod
    def _enum_value(value: ScopeType | str) -> str:
        return value.value if hasattr(value, "value") else str(value)
