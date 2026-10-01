import asyncio
import threading
import time
import zipfile
from pathlib import Path

import pytest

import astrbot.core.star.updator as plugin_updator_module
from astrbot.core.star.star import StarMetadata
from astrbot.core.star.updator import PluginUpdator, PreparedPluginUpdate

_VALID_METADATA = "name: demo\ndesc: demo\nversion: '1.0'\nauthor: test\n"


def _write_archive(path: Path, entries: dict[str, bytes | str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)


@pytest.mark.parametrize(
    "bad_path",
    ["repo/Plugin.py"],
)
def test_plugin_archive_rejects_case_collisions(
    tmp_path: Path,
    bad_path: str,
) -> None:
    archive_path = tmp_path / "plugin.zip"
    entries = {
        "repo/metadata.yaml": _VALID_METADATA,
        "repo/plugin.py": "pass\n",
        bad_path: "pass\n",
    }
    _write_archive(archive_path, entries)

    with pytest.raises(ValueError, match="Unsafe plugin archive path|case-colliding"):
        PluginUpdator.validate_plugin_archive(str(archive_path), str(tmp_path / "out"))


def test_plugin_archive_path_parser_rejects_backslash_separators() -> None:
    with pytest.raises(ValueError, match="Unsafe plugin archive path"):
        PluginUpdator._archive_member_parts("repo\\metadata.yaml", False)


@pytest.mark.parametrize(
    ("limit_name", "limit", "expected_error"),
    [
        ("_PLUGIN_ARCHIVE_MAX_ENTRIES", 2, "too many entries"),
        ("_PLUGIN_ARCHIVE_MAX_FILE_SIZE", 8, "size limit"),
        ("_PLUGIN_ARCHIVE_MAX_TOTAL_SIZE", 10, "total size limit"),
    ],
)
def test_plugin_archive_enforces_entry_and_expansion_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    limit_name: str,
    limit: int,
    expected_error: str,
) -> None:
    archive_path = tmp_path / "plugin.zip"
    _write_archive(
        archive_path,
        {
            "repo/": "",
            "repo/metadata.yaml": _VALID_METADATA,
            "repo/plugin.py": "x" * 16,
        },
    )
    monkeypatch.setattr(plugin_updator_module, limit_name, limit)
    if limit_name == "_PLUGIN_ARCHIVE_MAX_TOTAL_SIZE":
        monkeypatch.setattr(
            plugin_updator_module,
            "_PLUGIN_ARCHIVE_MAX_FILE_SIZE",
            1024,
        )

    with pytest.raises(ValueError, match=expected_error):
        PluginUpdator.validate_plugin_archive(str(archive_path), str(tmp_path / "out"))


def test_legacy_info_plugin_archives_are_only_allowed_for_updates(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "legacy.zip"
    _write_archive(archive_path, {"repo/main.py": "class Main: pass\n"})

    with pytest.raises(ValueError, match="metadata.yaml"):
        PluginUpdator.validate_plugin_archive(str(archive_path), str(tmp_path / "new"))

    assert (
        PluginUpdator.validate_plugin_archive(
            str(archive_path),
            str(tmp_path / "update"),
            allow_legacy_metadata=True,
        )
        is None
    )


def test_plugin_update_swap_retains_backup_for_rollback_and_finalizes_on_success(
    tmp_path: Path,
) -> None:
    plugin_store = tmp_path / "plugins"
    plugin_store.mkdir()
    installed_plugin = plugin_store / "demo"
    installed_plugin.mkdir()
    (installed_plugin / "version.txt").write_text("old", encoding="utf-8")

    staging_dir = plugin_store / ".plugin-update-rollback"
    staged_plugin = staging_dir / "plugin"
    staged_plugin.mkdir(parents=True)
    (staged_plugin / "version.txt").write_text("new", encoding="utf-8")
    rollback_plan = PreparedPluginUpdate(
        plugin_path=str(installed_plugin),
        staging_dir=str(staging_dir),
        staged_plugin_path=str(staged_plugin),
        backup_path=str(staging_dir / "previous"),
    )
    updater = PluginUpdator()
    updater.plugin_store_path = str(plugin_store)

    updater.apply_update(rollback_plan)
    assert (installed_plugin / "version.txt").read_text(encoding="utf-8") == "new"
    assert (Path(rollback_plan.backup_path) / "version.txt").read_text(
        encoding="utf-8"
    ) == "old"

    updater.rollback_update(rollback_plan)
    assert (installed_plugin / "version.txt").read_text(encoding="utf-8") == "old"
    updater.cleanup_prepared_update(rollback_plan)
    assert not staging_dir.exists()

    success_stage = plugin_store / ".plugin-update-success"
    success_plugin = success_stage / "plugin"
    success_plugin.mkdir(parents=True)
    (success_plugin / "version.txt").write_text("new", encoding="utf-8")
    success_plan = PreparedPluginUpdate(
        plugin_path=str(installed_plugin),
        staging_dir=str(success_stage),
        staged_plugin_path=str(success_plugin),
        backup_path=str(success_stage / "previous"),
    )
    updater.apply_update(success_plan)
    assert (Path(success_plan.backup_path) / "version.txt").read_text(
        encoding="utf-8"
    ) == "old"

    updater.finalize_update(success_plan)
    assert (installed_plugin / "version.txt").read_text(encoding="utf-8") == "new"
    assert not success_stage.exists()


@pytest.mark.asyncio
async def test_update_keeps_two_argument_call_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    updater = PluginUpdator()
    updater.plugin_store_path = str(tmp_path)
    plugin_path = tmp_path / "demo"
    plugin_path.mkdir()
    (plugin_path / "metadata.yaml").write_text(_VALID_METADATA, encoding="utf-8")
    staged_dir = tmp_path / ".plugin-update-compatible"
    staged_plugin = staged_dir / "plugin"
    staged_plugin.mkdir(parents=True)
    (staged_plugin / "metadata.yaml").write_text(_VALID_METADATA, encoding="utf-8")
    (staged_plugin / "main.py").write_text("class Main: pass\n", encoding="utf-8")
    plan = PreparedPluginUpdate(
        plugin_path=str(plugin_path),
        staging_dir=str(staged_dir),
        staged_plugin_path=str(staged_plugin),
        backup_path=str(staged_dir / "previous"),
    )

    async def prepare_update(plugin, proxy="", download_url="", **kwargs):
        assert plugin.name == "demo"
        assert proxy == ""
        assert download_url == ""
        return plan

    monkeypatch.setattr(updater, "prepare_update", prepare_update)

    result = await updater.update(
        StarMetadata(name="demo", repo="repo", root_dir_name="demo")
    )

    assert result == str(plugin_path)
    assert (plugin_path / "main.py").is_file()
    assert not staged_dir.exists()


@pytest.mark.asyncio
async def test_async_unzip_offloads_work_and_waits_for_worker_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = PluginUpdator()
    worker_finished = threading.Event()

    def slow_unzip(*args, **kwargs):
        time.sleep(0.04)
        worker_finished.set()

    monkeypatch.setattr(updater, "unzip_file", slow_unzip)
    task = asyncio.create_task(updater.unzip_file_async("archive.zip", "target"))
    await asyncio.sleep(0)
    assert not worker_finished.is_set()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert worker_finished.is_set()
