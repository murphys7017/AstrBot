from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from .store import MemoryStore
from .types import Experience, ScopeType


class ExperienceProjectionService:
    def __init__(
        self,
        store: MemoryStore,
        *,
        projections_root: Path | None = None,
    ) -> None:
        self.store = store
        self.projections_root = (
            projections_root
            if projections_root is not None
            else self.store.config.storage.projections_root
        )

    async def refresh_for_experiences(
        self,
        experiences: list[Experience],
    ) -> list[Path]:
        written_paths: list[Path] = []
        seen_scopes: set[tuple[str, str, str]] = set()

        for experience in experiences:
            scope_key = (
                experience.umo,
                self._enum_value(experience.scope_type),
                experience.scope_id,
            )
            if scope_key in seen_scopes:
                continue
            seen_scopes.add(scope_key)
            path = await self.refresh_scope_projection(
                experience.umo,
                experience.scope_type,
                experience.scope_id,
            )
            if path is not None:
                written_paths.append(path)
        return written_paths

    async def refresh_scope_projection(
        self,
        umo: str,
        scope_type: ScopeType | str,
        scope_id: str,
    ) -> Path | None:
        experiences = await self.store.list_experiences_for_scope(
            umo,
            scope_type,
            scope_id,
            ascending=True,
        )
        if not experiences:
            return None

        projection_path = self._build_projection_path(umo, scope_type, scope_id)
        projection_path.parent.mkdir(parents=True, exist_ok=True)
        projection_path.write_text(
            self._render_projection_markdown(
                experiences,
                umo=umo,
                scope_type=scope_type,
                scope_id=scope_id,
            ),
            encoding="utf-8",
        )
        return projection_path

    def _build_projection_path(
        self,
        umo: str,
        scope_type: ScopeType | str,
        scope_id: str,
    ) -> Path:
        return (
            self.projections_root
            / "experiences"
            / self._safe_path_component(umo)
            / self._safe_path_component(self._enum_value(scope_type))
            / f"{self._safe_path_component(scope_id)}.md"
        )

    def _render_projection_markdown(
        self,
        experiences: list[Experience],
        *,
        umo: str,
        scope_type: ScopeType | str,
        scope_id: str,
    ) -> str:
        generated_at = datetime.now(UTC).isoformat()
        lines = [
            "---",
            "projection_type: experience_timeline",
            f"umo: {umo}",
            f"scope_type: {self._enum_value(scope_type)}",
            f"scope_id: {scope_id}",
            f"experience_count: {len(experiences)}",
            f"generated_at: {generated_at}",
            "---",
            "",
            "# Experience Timeline",
            "",
        ]

        for experience in experiences:
            lines.extend(
                [
                    f"## {experience.event_time.isoformat()}",
                    f"- id: {experience.experience_id}",
                    f"- category: {self._enum_value(experience.category)}",
                    f"- summary: {experience.summary}",
                    f"- importance: {experience.importance:.2f}",
                    f"- confidence: {experience.confidence:.2f}",
                ]
            )
            if experience.detail_summary:
                lines.append(f"- detail_summary: {experience.detail_summary}")
            if experience.source_refs:
                lines.append("- source_refs:")
                lines.extend(f"  - {ref}" for ref in experience.source_refs)
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _safe_path_component(value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
        return sanitized or "unknown"

    @staticmethod
    def _enum_value(value: ScopeType | str) -> str:
        return value.value if hasattr(value, "value") else str(value)
