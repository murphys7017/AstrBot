from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from astrbot.core.skills.skill_manager import SkillManager


@pytest.mark.parametrize("skill_name_hint", [None, ""])
def test_install_root_zip_rejects_traversal_fallback_without_deleting_data(
    monkeypatch,
    tmp_path: Path,
    skill_name_hint: str | None,
):
    data_dir = tmp_path / "data"
    skills_root = data_dir / "skills"
    temp_dir = tmp_path / "temp"
    existing_skill = skills_root / "existing"
    existing_skill.mkdir(parents=True)
    temp_dir.mkdir()
    sentinel = data_dir / "preserve.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    (existing_skill / "SKILL.md").write_text("existing", encoding="utf-8")

    monkeypatch.setattr(
        "astrbot.core.skills.skill_manager.get_astrbot_data_path",
        lambda: str(data_dir),
    )
    monkeypatch.setattr(
        "astrbot.core.skills.skill_manager.get_astrbot_temp_path",
        lambda: str(temp_dir),
    )

    archive_path = tmp_path / "...zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("SKILL.md", "---\ndescription: test\n---\n")

    manager = SkillManager(skills_root=str(skills_root))

    with pytest.raises(ValueError, match="Invalid skill name"):
        manager.install_skill_from_zip(
            str(archive_path), skill_name_hint=skill_name_hint
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert (existing_skill / "SKILL.md").read_text(encoding="utf-8") == "existing"
