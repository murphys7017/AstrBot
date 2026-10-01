from zipfile import ZipFile

import pytest

import astrbot.cli.utils.plugin as plugin_utils


def test_get_archive_root_dir_accepts_one_plugin_root(tmp_path):
    archive_path = tmp_path / "plugin.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("demo/sub/main.py", "pass\n")
        archive.writestr("demo/", "")
        archive.writestr("demo/sub/", "")

    with ZipFile(archive_path) as archive:
        assert plugin_utils._get_archive_root_dir(archive) == "demo"


@pytest.mark.parametrize(
    ("limit_name", "limit", "message"),
    [
        ("_PLUGIN_ARCHIVE_MAX_ENTRIES", 1, "too many entries"),
        ("_PLUGIN_ARCHIVE_MAX_PATH_NODES", 2, "too many path nodes"),
    ],
)
def test_get_archive_root_dir_enforces_resource_limits(
    tmp_path,
    monkeypatch,
    limit_name,
    limit,
    message,
):
    archive_path = tmp_path / "limited-plugin.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("demo/main.py", "pass\n")
        archive.writestr("demo/utils.py", "pass\n")

    monkeypatch.setattr(plugin_utils, limit_name, limit)
    with ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match=message):
            plugin_utils._get_archive_root_dir(archive)


def test_get_archive_root_dir_rejects_excessive_path_depth(tmp_path):
    archive_path = tmp_path / "deep-plugin.zip"
    deep_path = "/".join(["demo", *(["a"] * 2000), "main.py"])
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(deep_path, "pass\n")

    with ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="path is too deep"):
            plugin_utils._get_archive_root_dir(archive)


def test_get_archive_root_dir_rejects_file_parent_conflict(tmp_path):
    archive_path = tmp_path / "conflicting-plugin.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("demo/plugin", "file\n")
        archive.writestr("demo/plugin/child.py", "pass\n")

    with ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="conflicts with a file"):
            plugin_utils._get_archive_root_dir(archive)
