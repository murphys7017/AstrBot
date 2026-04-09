from __future__ import annotations

from pathlib import Path
from typing import Any

from astrbot.core import logger

from .analyzer_manager import MemoryAnalyzerManager
from .config import get_memory_config
from .consolidation_service import ConsolidationService
from .document_search import DocumentSearchService
from .experience_service import ExperienceService
from .history_source import RecentConversationSource
from .long_term_service import LongTermMemoryService
from .manual_service import LongTermMemoryManualService
from .short_term_service import ShortTermMemoryService
from .snapshot_builder import MemorySnapshotBuilder
from .store import MemoryStore
from .turn_record_service import TurnRecordService
from .types import (
    DocumentSearchRequest,
    DocumentSearchResult,
    Experience,
    LongTermMemoryIndex,
    MemorySnapshot,
    MemoryUpdateRequest,
    SessionInsight,
    TurnRecord,
)
from .vector_index import MemoryVectorIndex


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        turn_record_service: TurnRecordService,
        short_term_service: ShortTermMemoryService,
        snapshot_builder: MemorySnapshotBuilder,
        analyzer_manager: MemoryAnalyzerManager | None = None,
        consolidation_service: ConsolidationService | None = None,
        experience_service: ExperienceService | None = None,
        long_term_service: LongTermMemoryService | None = None,
        manual_long_term_service: LongTermMemoryManualService | None = None,
        document_search_service: DocumentSearchService | None = None,
    ) -> None:
        self.store = store
        self.turn_record_service = turn_record_service
        self.short_term_service = short_term_service
        self.snapshot_builder = snapshot_builder
        self.analyzer_manager = analyzer_manager or MemoryAnalyzerManager()
        self.consolidation_service = consolidation_service
        self.experience_service = experience_service
        self.long_term_service = long_term_service
        self.manual_long_term_service = manual_long_term_service
        self.document_search_service = document_search_service

    def bind_provider_manager(self, provider_manager) -> None:
        self.analyzer_manager.bind_provider_manager(provider_manager)
        if self.long_term_service is not None:
            self.long_term_service.bind_provider_manager(provider_manager)
        if self.manual_long_term_service is not None:
            self.manual_long_term_service.bind_provider_manager(provider_manager)

    async def update_from_postprocess(self, req: MemoryUpdateRequest) -> TurnRecord:
        logger.info(
            "memory update started: umo=%s conversation_id=%s source_refs=%s",
            req.umo,
            req.conversation_id,
            req.source_refs,
        )
        turn = await self.turn_record_service.ingest_turn(req)
        conversation_history = _get_conversation_history(req.provider_request)
        await self.short_term_service.update_after_turn(
            turn,
            conversation_history=conversation_history,
        )
        if (
            self.consolidation_service is not None
            and await self.consolidation_service.should_run_consolidation(
                turn.umo,
                turn.conversation_id,
            )
        ):
            logger.info(
                "memory consolidation triggered after update: umo=%s conversation_id=%s",
                turn.umo,
                turn.conversation_id,
            )
            _, experiences = await self.run_consolidation(
                turn.umo, turn.conversation_id
            )
            if (
                experiences
                and self.long_term_service is not None
                and await self.long_term_service.should_run_promotion(
                    turn.umo,
                    turn.conversation_id,
                )
            ):
                logger.info(
                    "memory long-term promotion triggered after consolidation: umo=%s conversation_id=%s",
                    turn.umo,
                    turn.conversation_id,
                )
                await self.long_term_service.run_promotion(
                    turn.umo,
                    turn.conversation_id,
                )
        logger.info(
            "memory update finished: turn_id=%s umo=%s conversation_id=%s",
            turn.turn_id,
            turn.umo,
            turn.conversation_id,
        )
        return turn

    async def get_snapshot(
        self,
        umo: str,
        conversation_id: str | None,
        query: str | None = None,
    ) -> MemorySnapshot:
        logger.info(
            "memory snapshot requested: umo=%s conversation_id=%s query_present=%s",
            umo,
            conversation_id,
            query is not None,
        )
        return await self.snapshot_builder.build_snapshot(umo, conversation_id, query)

    async def run_consolidation(
        self,
        umo: str,
        conversation_id: str | None,
    ) -> tuple[SessionInsight | None, list[Experience]]:
        if self.consolidation_service is None:
            logger.info(
                "memory consolidation skipped: service unavailable umo=%s conversation_id=%s",
                umo,
                conversation_id,
            )
            return None, []
        if self.experience_service is None:
            raise RuntimeError(
                "memory consolidation requested without experience service"
            )

        logger.info(
            "memory consolidation started: umo=%s conversation_id=%s",
            umo,
            conversation_id,
        )
        insight, experiences = await self.consolidation_service.run_for_scope(
            umo,
            conversation_id,
        )
        (
            persisted_insight,
            persisted_experiences,
        ) = await self.store.persist_consolidation_batch(
            insight,
            experiences,
        )
        projection_paths: list[Path] = []
        try:
            projection_paths = (
                await self.experience_service.refresh_projections_for_experiences(
                    persisted_experiences
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "memory consolidation projection refresh failed: umo=%s conversation_id=%s error=%s",
                umo,
                conversation_id,
                exc,
                exc_info=True,
            )
        logger.info(
            "memory consolidation finished: umo=%s conversation_id=%s insight_created=%s experiences=%s projections=%s",
            umo,
            conversation_id,
            persisted_insight is not None,
            len(persisted_experiences),
            len(projection_paths),
        )
        return persisted_insight, persisted_experiences

    async def search_long_term_memories(
        self,
        req: DocumentSearchRequest,
    ) -> list[DocumentSearchResult]:
        if self.document_search_service is None:
            raise RuntimeError("memory document search service is unavailable")
        return await self.document_search_service.search_long_term_memories(req)

    async def import_long_term_memory_document(
        self,
        doc_path: Path | str,
    ) -> LongTermMemoryIndex:
        if self.manual_long_term_service is None:
            raise RuntimeError("memory manual long-term service is unavailable")
        return await self.manual_long_term_service.upsert_memory_from_document(doc_path)


_MEMORY_SERVICE: MemoryService | None = None


def get_memory_service() -> MemoryService:
    global _MEMORY_SERVICE
    if _MEMORY_SERVICE is None:
        config = get_memory_config()
        store = MemoryStore(config=config)
        analyzer_manager = MemoryAnalyzerManager(config.analysis)
        history_source = RecentConversationSource(
            store,
            recent_turns_window=config.short_term.recent_turns_window,
        )
        turn_record_service = TurnRecordService(store)
        short_term_service = ShortTermMemoryService(
            store,
            history_source,
            analyzer_manager=analyzer_manager,
            analysis_config=config.analysis,
        )
        consolidation_service = ConsolidationService(
            store,
            analyzer_manager=analyzer_manager,
            analysis_config=config.analysis,
            consolidation_config=config.consolidation,
        )
        experience_service = ExperienceService(store)
        vector_index = MemoryVectorIndex(store, config=config)
        long_term_service = LongTermMemoryService(
            store,
            analyzer_manager=analyzer_manager,
            analysis_config=config.analysis,
            long_term_config=config.long_term,
            vector_index=vector_index,
        )
        manual_long_term_service = LongTermMemoryManualService(
            store,
            vector_index=vector_index,
        )
        document_search_service = DocumentSearchService(
            store,
            vector_index=vector_index,
        )
        snapshot_builder = MemorySnapshotBuilder(store)
        _MEMORY_SERVICE = MemoryService(
            store,
            turn_record_service,
            short_term_service,
            snapshot_builder,
            analyzer_manager,
            consolidation_service,
            experience_service,
            long_term_service,
            manual_long_term_service,
            document_search_service,
        )
    return _MEMORY_SERVICE


async def shutdown_memory_service() -> None:
    global _MEMORY_SERVICE
    if _MEMORY_SERVICE is None:
        return
    await _MEMORY_SERVICE.store.close()
    _MEMORY_SERVICE = None


def _get_conversation_history(
    provider_request: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    if not isinstance(provider_request, dict):
        return None
    history = provider_request.get("conversation_history")
    if isinstance(history, list):
        return [item for item in history if isinstance(item, dict)]
    return None
