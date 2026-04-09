from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrbot.core.memory.projection import ExperienceProjectionService
from astrbot.core.memory.types import Experience


class _StubStore:
    def __init__(self, projections_root: Path, experiences: list[Experience]) -> None:
        self.config = SimpleNamespace(
            storage=SimpleNamespace(projections_root=projections_root)
        )
        self._experiences = experiences

    async def list_experiences_for_scope(
        self,
        umo: str,
        scope_type: str,
        scope_id: str,
        *,
        ascending: bool = False,
    ) -> list[Experience]:
        return list(self._experiences)


def _build_experience(
    *,
    umo: str,
    scope_type: str,
    scope_id: str,
) -> Experience:
    now = datetime.now(UTC)
    return Experience(
        experience_id="exp-1",
        umo=umo,
        conversation_id="conv-1",
        scope_type=scope_type,
        scope_id=scope_id,
        event_time=now,
        category="episodic_event",
        summary="Projection summary",
        detail_summary="Projection detail",
        importance=0.8,
        confidence=0.9,
        source_refs=["turn:1"],
        created_at=now,
        updated_at=now,
    )


def test_projection_path_stays_stable_for_same_non_ascii_inputs(temp_dir: Path):
    experience = _build_experience(umo="测试用户", scope_type="会话", scope_id="主题一")
    service = ExperienceProjectionService(
        _StubStore(temp_dir / "projections", [experience])
    )

    first_path = service._build_projection_path("测试用户", "会话", "主题一")
    second_path = service._build_projection_path("测试用户", "会话", "主题一")

    assert first_path == second_path
    assert first_path.stem != "unknown"
    assert first_path.stem.startswith("value--")


def test_projection_path_distinguishes_different_non_ascii_inputs(temp_dir: Path):
    experience = _build_experience(
        umo="测试用户", scope_type="conversation", scope_id="主题一"
    )
    service = ExperienceProjectionService(
        _StubStore(temp_dir / "projections", [experience])
    )

    first_path = service._build_projection_path("测试用户甲", "conversation", "主题一")
    second_path = service._build_projection_path("测试用户乙", "conversation", "主题一")

    assert first_path != second_path
    assert first_path.parent != second_path.parent


def test_projection_path_keeps_ascii_slug_readable(temp_dir: Path):
    experience = _build_experience(
        umo="test:private:user",
        scope_type="conversation",
        scope_id="conv-1",
    )
    service = ExperienceProjectionService(
        _StubStore(temp_dir / "projections", [experience])
    )

    projection_path = service._build_projection_path(
        "test:private:user",
        "conversation",
        "conv-1",
    )

    assert projection_path.parent.parent.name.startswith("test_private_user--")
    assert projection_path.parent.name.startswith("conversation--")
    assert projection_path.name.startswith("conv-1--")


@pytest.mark.asyncio
async def test_refresh_scope_projection_writes_hashed_projection_path(temp_dir: Path):
    experience = _build_experience(
        umo="用户甲", scope_type="conversation", scope_id="当前话题"
    )
    service = ExperienceProjectionService(
        _StubStore(temp_dir / "projections", [experience])
    )

    projection_path = await service.refresh_scope_projection(
        "用户甲",
        "conversation",
        "当前话题",
    )

    assert projection_path is not None
    assert projection_path.exists()
    assert (
        projection_path.parent.parent.parent == temp_dir / "projections" / "experiences"
    )
    assert projection_path.name.endswith(".md")
    assert "--" in projection_path.stem
    assert projection_path.name != "unknown.md"
