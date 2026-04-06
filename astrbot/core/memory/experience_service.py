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
        await self.projection_service.refresh_for_experiences(persisted)
        return persisted

    async def list_recent(self, umo: str, limit: int) -> list[Experience]:
        return await self.store.list_recent_experiences(umo, limit)

    async def list_by_time_range(
        self,
        umo: str,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> list[Experience]:
        return await self.store.list_experiences_by_time_range(umo, start_at, end_at)

    async def refresh_projection_for_scope(
        self,
        umo: str,
        scope_type: str,
        scope_id: str,
    ) -> Path | None:
        return await self.projection_service.refresh_scope_projection(
            umo,
            scope_type,
            scope_id,
        )
