from __future__ import annotations

from typing import Any

from astrbot.core import logger

from .analyzer_manager import MemoryAnalyzerManager
from .config import get_memory_config
from .history_source import RecentConversationSource
from .short_term_service import ShortTermMemoryService
from .snapshot_builder import MemorySnapshotBuilder
from .store import MemoryStore
from .turn_record_service import TurnRecordService
from .types import MemorySnapshot, MemoryUpdateRequest, TurnRecord


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        turn_record_service: TurnRecordService,
        short_term_service: ShortTermMemoryService,
        snapshot_builder: MemorySnapshotBuilder,
        analyzer_manager: MemoryAnalyzerManager | None = None,
    ) -> None:
        self.store = store
        self.turn_record_service = turn_record_service
        self.short_term_service = short_term_service
        self.snapshot_builder = snapshot_builder
        self.analyzer_manager = analyzer_manager or MemoryAnalyzerManager()

    def bind_provider_manager(self, provider_manager) -> None:
        self.analyzer_manager.bind_provider_manager(provider_manager)

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
        snapshot_builder = MemorySnapshotBuilder(store)
        _MEMORY_SERVICE = MemoryService(
            store,
            turn_record_service,
            short_term_service,
            snapshot_builder,
            analyzer_manager,
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
