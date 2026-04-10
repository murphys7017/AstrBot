from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .projection import ExperienceProjectionService
from .store import MemoryStore
from .types import Experience


class ExperienceService:
    def __init__(
        self,
        store: MemoryStore,
        projection_service: ExperienceProjectionService | None = None,
    ) -> None:
        self.store = store
        self.projection_service = projection_service or ExperienceProjectionService(
            store
        )

    async def persist_experiences(
        self,
        experiences: list[Experience],
    ) -> list[Experience]:
        persisted: list[Experience] = []
        for experience in experiences:
            persisted.append(await self.store.save_experience(experience))
        return persisted

    async def list_recent(
        self,
        canonical_user_id: str,
        limit: int,
        conversation_id: str | None = None,
    ) -> list[Experience]:
        return await self.store.list_recent_experiences(
            canonical_user_id,
            limit,
            conversation_id=conversation_id,
        )

    async def list_by_time_range(
        self,
        canonical_user_id: str,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> list[Experience]:
        return await self.store.list_experiences_by_time_range(
            canonical_user_id,
            start_at,
            end_at,
        )

    async def refresh_projection_for_scope(
        self,
        canonical_user_id: str,
        scope_type: str,
        scope_id: str,
    ) -> Path | None:
        return await self.projection_service.refresh_scope_projection(
            canonical_user_id,
            scope_type,
            scope_id,
        )

    async def refresh_projections_for_experiences(
        self,
        experiences: list[Experience],
    ) -> list[Path]:
        return await self.projection_service.refresh_for_experiences(experiences)
