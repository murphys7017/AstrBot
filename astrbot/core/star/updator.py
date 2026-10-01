import asyncio
import keyword
import os
import re
import secrets
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

import yaml

from astrbot.core import logger
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_path
from astrbot.core.utils.io import ensure_dir, remove_dir

from ..star.star import StarMetadata
from ..updator import RepoZipUpdator
from ..zip_updator import _ArchivePathNode, _is_symlink_or_junction

_PLUGIN_METADATA_MAX_BYTES = 1024 * 1024
_PLUGIN_METADATA_REQUIRED_FIELDS = ("name", "desc", "version", "author")
_PLUGIN_METADATA_FILENAMES = ("metadata.yaml", "metadata.yml")
_PLUGIN_ARCHIVE_MAX_ENTRIES = 20_000
_PLUGIN_ARCHIVE_MAX_PATH_LENGTH = 4096
_PLUGIN_ARCHIVE_MAX_PATH_DEPTH = 128
_PLUGIN_ARCHIVE_MAX_TOTAL_PATH_LENGTH = 16 * 1024 * 1024
_PLUGIN_ARCHIVE_MAX_PATH_NODES = 100_000
_PLUGIN_ARCHIVE_MAX_FILE_SIZE = 128 * 1024 * 1024
_PLUGIN_ARCHIVE_MAX_TOTAL_SIZE = 512 * 1024 * 1024
_PLUGIN_ARCHIVE_MAX_DOWNLOAD_SIZE = 512 * 1024 * 1024
_ARCHIVE_COPY_CHUNK_SIZE = 64 * 1024
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{digit}" for digit in "123456789\u00b9\u00b2\u00b3"),
    *(f"lpt{digit}" for digit in "123456789\u00b9\u00b2\u00b3"),
}


def _create_plugin_archive_temp_file(directory: str) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    for _ in range(100):
        path = os.path.join(
            directory,
            f".astrbot-plugin-update-{secrets.token_hex(8)}",
        )
        try:
            return os.open(path, flags, 0o666), path
        except FileExistsError:
            continue
    raise FileExistsError("Could not create a temporary plugin archive file.")


@dataclass
class PreparedPluginUpdate:
    plugin_path: str
    staging_dir: str
    staged_plugin_path: str
    backup_path: str
    backup_created: bool = False
    applied: bool = False
    preserve_staging: bool = False
    finalized: bool = False


class PluginUpdator(RepoZipUpdator):
    def __init__(self, repo_mirror: str = "", verify: str | bool | None = None) -> None:
        super().__init__(repo_mirror, verify=verify)
        self.plugin_store_path = get_astrbot_plugin_path()

    def get_plugin_store_path(self) -> str:
        return self.plugin_store_path

    @staticmethod
    async def _run_archive_io_in_thread(function, *args, **kwargs):
        worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            try:
                worker.result()
            except BaseException:
                pass
            raise

    async def unzip_file_async(
        self,
        zip_path: str,
        target_dir: str,
        *,
        allow_legacy_metadata: bool = False,
    ) -> None:
        await self._run_archive_io_in_thread(
            self.unzip_file,
            zip_path,
            target_dir,
            allow_legacy_metadata=allow_legacy_metadata,
        )

    async def install(self, repo_url: str, proxy="", download_url: str = "") -> str:
        _, repo_name, _ = self.parse_github_url(repo_url)
        repo_name = self.format_name(repo_name)
        plugin_path = os.path.join(self.plugin_store_path, repo_name)
        if download_url:
            logger.info(f"Downloading plugin archive for {repo_name}: {download_url}")
            await self._download_file(
                download_url,
                plugin_path + ".zip",
                max_size=_PLUGIN_ARCHIVE_MAX_DOWNLOAD_SIZE,
            )
        else:
            await self.download_from_repo_url(
                plugin_path,
                repo_url,
                proxy,
                max_size=_PLUGIN_ARCHIVE_MAX_DOWNLOAD_SIZE,
            )
        await self.unzip_file_async(plugin_path + ".zip", plugin_path)

        return plugin_path

    async def prepare_update(
        self,
        plugin: StarMetadata,
        proxy="",
        download_url: str = "",
        *,
        allow_legacy_metadata: bool | None = None,
    ) -> PreparedPluginUpdate:
        """Download, validate, and extract an update without touching the plugin."""
        repo_url = plugin.repo
        if not repo_url and not download_url:
            raise Exception(
                f"Plugin {plugin.name} does not specify a repository URL or download URL."
            )
        if not plugin.root_dir_name:
            raise Exception(
                f"Plugin {plugin.name} does not specify a root directory name."
            )

        plugin_path = os.path.join(self.plugin_store_path, plugin.root_dir_name)
        if not os.path.isdir(plugin_path):
            raise FileNotFoundError(f"Plugin directory does not exist: {plugin_path}")

        if allow_legacy_metadata is None:
            allow_legacy_metadata = not any(
                os.path.isfile(os.path.join(plugin_path, filename))
                for filename in _PLUGIN_METADATA_FILENAMES
            )

        ensure_dir(self.plugin_store_path)
        staging_dir = tempfile.mkdtemp(
            prefix=".plugin-update-",
            dir=self.plugin_store_path,
        )
        archive_path = os.path.join(staging_dir, "archive.zip")
        staged_plugin_path = os.path.join(staging_dir, "plugin")
        plan = PreparedPluginUpdate(
            plugin_path=plugin_path,
            staging_dir=staging_dir,
            staged_plugin_path=staged_plugin_path,
            backup_path=os.path.join(staging_dir, "previous"),
        )

        logger.info(
            "Preparing plugin update at %s from %s",
            plugin_path,
            download_url or repo_url,
        )
        try:
            if download_url:
                await self._download_file(
                    download_url,
                    archive_path,
                    max_size=_PLUGIN_ARCHIVE_MAX_DOWNLOAD_SIZE,
                )
            else:
                await self.download_from_repo_url(
                    os.path.join(staging_dir, "archive"),
                    repo_url,
                    proxy=proxy,
                    max_size=_PLUGIN_ARCHIVE_MAX_DOWNLOAD_SIZE,
                )

            archive_plugin_name = await self._run_archive_io_in_thread(
                self.validate_plugin_archive,
                archive_path,
                staged_plugin_path,
                allow_legacy_metadata=allow_legacy_metadata,
            )
            if (
                archive_plugin_name is not None
                and plugin.name
                and archive_plugin_name != plugin.name
            ):
                raise ValueError(
                    f"Plugin archive name {archive_plugin_name!r} does not match "
                    f"installed plugin {plugin.name!r}."
                )

            await self.unzip_file_async(
                archive_path,
                staged_plugin_path,
                allow_legacy_metadata=allow_legacy_metadata,
            )
            return plan
        except BaseException:
            self.cleanup_prepared_update(plan)
            raise

    def apply_update(self, plan: PreparedPluginUpdate) -> None:
        """Swap in the staged plugin and retain the old directory for rollback."""
        if plan.applied:
            raise RuntimeError("Plugin update has already been applied.")
        if not os.path.isdir(plan.plugin_path):
            raise FileNotFoundError(
                f"Plugin directory does not exist: {plan.plugin_path}"
            )

        os.replace(plan.plugin_path, plan.backup_path)
        plan.backup_created = True
        try:
            os.replace(plan.staged_plugin_path, plan.plugin_path)
        except OSError:
            try:
                os.replace(plan.backup_path, plan.plugin_path)
                plan.backup_created = False
            except OSError as restore_error:
                plan.preserve_staging = True
                logger.critical(
                    "Plugin update failed and the previous plugin could not be "
                    "restored. Backup retained at %s: %s",
                    plan.backup_path,
                    restore_error,
                )
                raise RuntimeError(
                    "Plugin update failed; the previous plugin backup was "
                    f"retained at {plan.backup_path}."
                ) from restore_error
            raise
        plan.applied = True

    def rollback_update(self, plan: PreparedPluginUpdate) -> None:
        """Restore the previous directory while preserving it if recovery fails."""
        if not plan.applied and not plan.backup_created:
            return

        if not plan.applied:
            if os.path.lexists(plan.plugin_path):
                raise RuntimeError(
                    "Cannot restore the plugin backup because the destination is occupied."
                )
            try:
                os.replace(plan.backup_path, plan.plugin_path)
            except OSError as restore_error:
                plan.preserve_staging = True
                logger.critical(
                    "Plugin update rollback failed; the previous plugin backup is "
                    "retained at %s: %s",
                    plan.backup_path,
                    restore_error,
                )
                raise RuntimeError(
                    "Plugin update rollback failed; the previous plugin backup "
                    f"was retained at {plan.backup_path}."
                ) from restore_error
            plan.backup_created = False
            plan.preserve_staging = False
            return

        failed_path = os.path.join(plan.staging_dir, "failed")
        os.replace(plan.plugin_path, failed_path)
        try:
            os.replace(plan.backup_path, plan.plugin_path)
        except OSError as restore_error:
            try:
                os.replace(failed_path, plan.plugin_path)
            except OSError:
                plan.preserve_staging = True
            logger.critical(
                "Plugin update rollback failed; the previous plugin backup is "
                "retained at %s: %s",
                plan.backup_path,
                restore_error,
            )
            raise RuntimeError(
                "Plugin update rollback failed; the previous plugin backup "
                f"was retained at {plan.backup_path}."
            ) from restore_error

        plan.applied = False
        plan.backup_created = False
        plan.preserve_staging = False
        try:
            remove_dir(failed_path)
        except Exception:
            logger.warning(
                "Failed to remove rejected plugin version %s",
                failed_path,
                exc_info=True,
            )

    def finalize_update(self, plan: PreparedPluginUpdate) -> None:
        """Discard the old plugin only after the new plugin is known to load."""
        if not plan.applied:
            raise RuntimeError("Cannot finalize a plugin update that was not applied.")
        if plan.backup_created:
            try:
                remove_dir(plan.backup_path)
                plan.backup_created = False
            except Exception:
                plan.preserve_staging = True
                logger.warning(
                    "Failed to remove replaced plugin backup %s",
                    plan.backup_path,
                    exc_info=True,
                )
                return
        try:
            remove_dir(plan.staging_dir)
            plan.finalized = True
        except Exception:
            logger.warning(
                "Failed to remove plugin update staging directory %s",
                plan.staging_dir,
                exc_info=True,
            )

    def cleanup_prepared_update(self, plan: PreparedPluginUpdate) -> None:
        if plan.preserve_staging or plan.applied or plan.backup_created:
            return
        try:
            remove_dir(plan.staging_dir)
            plan.finalized = True
        except Exception:
            logger.warning(
                "Failed to remove plugin update staging directory %s",
                plan.staging_dir,
                exc_info=True,
            )

    async def update(
        self,
        plugin: StarMetadata,
        proxy="",
        download_url: str = "",
    ) -> str:
        """Backward-compatible one-step update API."""
        plan = await self.prepare_update(
            plugin,
            proxy=proxy,
            download_url=download_url,
        )
        try:
            self.apply_update(plan)
            self.finalize_update(plan)
        except BaseException:
            if plan.applied or plan.backup_created:
                self.rollback_update(plan)
            self.cleanup_prepared_update(plan)
            raise
        return plan.plugin_path

    def unzip_file(
        self,
        zip_path: str,
        target_dir: str,
        *,
        allow_legacy_metadata: bool = False,
    ) -> None:
        self.validate_plugin_archive(
            zip_path,
            target_dir,
            allow_legacy_metadata=allow_legacy_metadata,
        )
        ensure_dir(target_dir)
        logger.info(f"Extracting archive: {zip_path}")
        with zipfile.ZipFile(zip_path, "r") as archive:
            update_dir = self._extract_archive_contents(archive, target_dir)

        self._finalize_extracted_archive(zip_path, target_dir, update_dir)

    def _extract_archive_contents(
        self,
        archive: zipfile.ZipFile,
        target_dir: str,
    ) -> str:
        entries = archive.infolist()
        update_dir = self._resolve_archive_root_dir(
            [member.filename for member in entries]
        )
        root_parts = update_dir.split(os.sep) if update_dir else []
        archive_root = root_parts[0] if root_parts else ""
        match = re.fullmatch(r"(.+)-([0-9a-fA-F]{40})", archive_root)
        member_parts = [
            (member, self._archive_member_parts(member.filename, member.is_dir()))
            for member in entries
        ]
        shorten_root = bool(
            match
            and all(not parts or parts[0] == archive_root for _, parts in member_parts)
        )
        if shorten_root and match:
            short_root = f"{match[1]}-{match[2][:8]}"
            update_dir = os.path.join(short_root, *root_parts[1:])
        else:
            short_root = archive_root

        total_written = 0
        target_root = os.path.abspath(target_dir)
        for member, parts in member_parts:
            if shorten_root and parts and parts[0] == archive_root:
                parts[0] = short_root
            destination = self._prepare_archive_destination(target_root, parts)
            if member.is_dir():
                ensure_dir(destination)
                continue

            existing_mode = None
            try:
                existing_stat = os.stat(destination, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISREG(existing_stat.st_mode):
                    existing_mode = stat.S_IMODE(existing_stat.st_mode)

            fd, temporary_path = _create_plugin_archive_temp_file(
                os.path.dirname(destination)
            )
            member_written = 0
            try:
                with (
                    os.fdopen(fd, "wb") as target,
                    archive.open(member, "r") as source,
                ):
                    while chunk := source.read(_ARCHIVE_COPY_CHUNK_SIZE):
                        member_written += len(chunk)
                        total_written += len(chunk)
                        if member_written > _PLUGIN_ARCHIVE_MAX_FILE_SIZE:
                            raise ValueError(
                                f"Plugin archive member exceeds the size limit: {member.filename!r}"
                            )
                        if total_written > _PLUGIN_ARCHIVE_MAX_TOTAL_SIZE:
                            raise ValueError(
                                "Plugin archive exceeds the total size limit."
                            )
                        if member_written > member.file_size:
                            raise ValueError(
                                f"Plugin archive member expands beyond its declared size: {member.filename!r}"
                            )
                        target.write(chunk)
                if member_written != member.file_size:
                    raise ValueError(
                        f"Plugin archive member size does not match its directory entry: {member.filename!r}"
                    )
                mode = member.external_attr >> 16
                if stat.S_ISREG(mode):
                    os.chmod(temporary_path, stat.S_IMODE(mode) & 0o777)
                elif existing_mode is not None:
                    os.chmod(temporary_path, existing_mode)
                os.replace(temporary_path, destination)
            finally:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
        return update_dir

    @staticmethod
    def _archive_member_parts(name: str, is_dir: bool) -> list[str]:
        windows_path = PureWindowsPath(name)
        if (
            not name
            or "\x00" in name
            or "\\" in name
            or PurePosixPath(name).is_absolute()
            or windows_path.root
            or windows_path.drive
        ):
            raise ValueError(f"Unsafe plugin archive path: {name!r}")

        raw_parts = name.split("/")
        if is_dir and raw_parts[-1] == "":
            raw_parts.pop()
        while raw_parts and raw_parts[0] == ".":
            raw_parts.pop(0)
        if not raw_parts:
            if is_dir:
                return []
            raise ValueError(f"Unsafe plugin archive path: {name!r}")
        if any(not part for part in raw_parts):
            raise ValueError(f"Unsafe plugin archive path: {name!r}")
        for part in raw_parts:
            windows_basename = part.split(".", 1)[0].casefold()
            if (
                part in {".", ".."}
                or part.rstrip(" .") != part
                or any(char in part for char in '<>:"|?*')
                or any(ord(char) < 32 for char in part)
                or windows_basename in _WINDOWS_RESERVED_NAMES
            ):
                raise ValueError(f"Unsafe plugin archive path: {name!r}")
        return raw_parts

    @classmethod
    def _validate_archive_member_paths(
        cls,
        archive: zipfile.ZipFile,
        target_dir: str,
    ) -> None:
        members = archive.infolist()
        if len(members) > _PLUGIN_ARCHIVE_MAX_ENTRIES:
            raise ValueError("Plugin archive contains too many entries.")

        target_root = os.path.abspath(target_dir)
        path_tree = _ArchivePathNode()
        path_node_count = 1
        total_path_length = 0
        declared_total_size = 0
        for member in members:
            name = member.filename
            if len(name) > _PLUGIN_ARCHIVE_MAX_PATH_LENGTH:
                raise ValueError(f"Plugin archive path is too long: {name!r}")
            total_path_length += len(name)
            if total_path_length > _PLUGIN_ARCHIVE_MAX_TOTAL_PATH_LENGTH:
                raise ValueError("Plugin archive contains too much path data.")

            parts = cls._archive_member_parts(name, member.is_dir())
            if len(parts) > _PLUGIN_ARCHIVE_MAX_PATH_DEPTH:
                raise ValueError(f"Plugin archive path is too deep: {name!r}")
            path = os.path.abspath(os.path.join(target_root, *parts))
            try:
                common_path = os.path.commonpath([target_root, path])
            except ValueError as exc:
                raise ValueError(f"Unsafe plugin archive path: {name!r}") from exc
            if os.path.normcase(common_path) != os.path.normcase(target_root):
                raise ValueError(f"Unsafe plugin archive path: {name!r}")

            mode = member.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK:
                raise ValueError(f"Plugin archive symlink is not allowed: {name!r}")
            if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f"Unsupported plugin archive entry type: {name!r}")
            if member.is_dir() != (file_type == stat.S_IFDIR) and file_type:
                raise ValueError(f"Invalid plugin archive entry type: {name!r}")

            node = path_tree
            for part in parts:
                if node.kind == "file":
                    raise ValueError(
                        f"Plugin archive path conflicts with a file: {name!r}"
                    )
                key = part.casefold()
                child = node.children.get(key)
                if child is None:
                    if path_node_count >= _PLUGIN_ARCHIVE_MAX_PATH_NODES:
                        raise ValueError("Plugin archive contains too many path nodes.")
                    child = _ArchivePathNode(spelling=part)
                    node.children[key] = child
                    path_node_count += 1
                elif child.spelling != part:
                    raise ValueError(
                        f"Plugin archive contains case-colliding paths: {name!r}"
                    )
                node = child

            kind = "directory" if member.is_dir() else "file"
            if node.kind and node.kind != kind:
                raise ValueError(f"Plugin archive path has conflicting types: {name!r}")
            if node.kind:
                raise ValueError(f"Plugin archive contains duplicate paths: {name!r}")
            if kind == "file" and node.children:
                raise ValueError(
                    f"Plugin archive path conflicts with a directory: {name!r}"
                )
            node.kind = kind

            if member.file_size < 0:
                raise ValueError(f"Plugin archive member has an invalid size: {name!r}")
            if member.is_dir():
                if member.file_size:
                    raise ValueError(f"Plugin archive directory is not empty: {name!r}")
            else:
                if member.file_size > _PLUGIN_ARCHIVE_MAX_FILE_SIZE:
                    raise ValueError(
                        f"Plugin archive member exceeds the size limit: {name!r}"
                    )
                declared_total_size += member.file_size
                if declared_total_size > _PLUGIN_ARCHIVE_MAX_TOTAL_SIZE:
                    raise ValueError("Plugin archive exceeds the total size limit.")

    @staticmethod
    def _prepare_archive_destination(target_root: str, parts: list[str]) -> str:
        destination = os.path.abspath(os.path.join(target_root, *parts))
        try:
            common_path = os.path.commonpath([target_root, destination])
        except ValueError as exc:
            raise ValueError("Unsafe plugin archive path.") from exc
        if os.path.normcase(common_path) != os.path.normcase(target_root):
            raise ValueError("Unsafe plugin archive path.")

        current = target_root
        for part in parts[:-1]:
            current = os.path.join(current, part)
            if _is_symlink_or_junction(current) or (
                os.path.lexists(current) and not os.path.isdir(current)
            ):
                raise ValueError(
                    "Plugin archive path traverses a symbolic link, junction, "
                    f"or non-directory: {current!r}"
                )
            os.makedirs(current, exist_ok=True)
        if _is_symlink_or_junction(destination):
            raise ValueError(
                f"Plugin archive path targets a symbolic link or junction: {destination!r}"
            )
        return destination

    @classmethod
    def validate_plugin_archive(
        cls,
        zip_path: str,
        target_dir: str,
        *,
        allow_legacy_metadata: bool = False,
    ) -> str | None:
        try:
            entry_count = cls._read_archive_entry_count(zip_path)
            if entry_count is not None and entry_count > _PLUGIN_ARCHIVE_MAX_ENTRIES:
                raise ValueError("Plugin archive contains too many entries.")
            with zipfile.ZipFile(zip_path, "r") as archive:
                cls._validate_archive_member_paths(archive, target_dir)
                entries = archive.namelist()
                update_dir = cls._resolve_archive_root_dir(entries)
                portable_root = update_dir.replace(os.sep, "/").rstrip("/.")
                metadata_entries = []
                for filename in _PLUGIN_METADATA_FILENAMES:
                    expected_parts = (
                        portable_root.split("/") if portable_root else []
                    ) + [filename]
                    metadata_entries = [
                        member
                        for member in archive.infolist()
                        if cls._archive_member_parts(
                            member.filename,
                            member.is_dir(),
                        )
                        == expected_parts
                    ]
                    if metadata_entries:
                        break
                if not metadata_entries and allow_legacy_metadata:
                    return None
                if len(metadata_entries) != 1 or metadata_entries[0].is_dir():
                    raise ValueError(
                        "Plugin archive must contain exactly one metadata.yaml or "
                        "metadata.yml at its repository root."
                    )

                metadata_entry = metadata_entries[0]
                if metadata_entry.file_size > _PLUGIN_METADATA_MAX_BYTES:
                    raise ValueError("Plugin metadata exceeds 1 MB.")
                with archive.open(metadata_entry, "r") as metadata_file:
                    raw_metadata = metadata_file.read(_PLUGIN_METADATA_MAX_BYTES + 1)
                if len(raw_metadata) > _PLUGIN_METADATA_MAX_BYTES:
                    raise ValueError("Plugin metadata exceeds 1 MB.")
                if len(raw_metadata) != metadata_entry.file_size:
                    raise ValueError(
                        "Plugin metadata size does not match its directory entry."
                    )
                metadata = yaml.safe_load(raw_metadata.decode("utf-8"))
        except zipfile.BadZipFile as exc:
            raise ValueError("Plugin archive is not a valid ZIP file.") from exc
        except UnicodeDecodeError as exc:
            raise ValueError("Plugin metadata must use UTF-8 encoding.") from exc
        except yaml.YAMLError as exc:
            raise ValueError("Plugin metadata is invalid YAML.") from exc

        if not isinstance(metadata, dict):
            raise ValueError("Plugin metadata must be a YAML mapping.")
        if "desc" not in metadata and "description" in metadata:
            metadata["desc"] = metadata["description"]
        for field in _PLUGIN_METADATA_REQUIRED_FIELDS:
            value = metadata.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Plugin metadata field {field!r} must be a non-empty string."
                )

        plugin_name = metadata["name"].strip()
        if (
            "/" in plugin_name
            or "\\" in plugin_name
            or not plugin_name.isidentifier()
            or keyword.iskeyword(plugin_name)
        ):
            raise ValueError("Plugin metadata name is not a valid Python module name.")
        return plugin_name
