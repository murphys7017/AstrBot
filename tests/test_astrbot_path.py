import os
import tempfile
from pathlib import Path

from astrbot.core.utils.astrbot_path import get_astrbot_system_tmp_path


def test_system_tmp_path_keeps_an_existing_directory(monkeypatch, tmp_path):
    system_temp = tmp_path / "system_temp"
    (system_temp / ".astrbot").mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(system_temp))

    assert get_astrbot_system_tmp_path() == os.path.realpath(
        str(system_temp / ".astrbot")
    )


def test_system_tmp_path_never_shadows_marker_file(monkeypatch, tmp_path):
    system_temp = tmp_path / "system_temp"
    system_temp.mkdir()
    marker = system_temp / ".astrbot"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(tempfile, "tempdir", str(system_temp))

    resolved = get_astrbot_system_tmp_path()

    assert resolved == os.path.realpath(str(system_temp / ".astrbot-tmp"))
    Path(resolved).mkdir(parents=True, exist_ok=True)
    assert marker.is_file()


def test_fallback_temp_dir_is_ignored():
    repo_root = Path(__file__).resolve().parents[1]
    for ignore_file in (".gitignore", ".dockerignore"):
        entries = {
            line.strip()
            for line in (repo_root / ignore_file).read_text(encoding="utf-8").splitlines()
        }
        assert ".astrbot-tmp" in entries
