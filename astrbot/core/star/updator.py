import asyncio
import keyword
import os
import re
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

_PLUGIN_METADATA_MAX_BYTES = 1024 * 1024
_PLUGIN_METADATA_REQUIRED_FIELDS = ("name", "desc", "version", "author")
_PLUGIN_METADATA_FILENAMES = ("metadata.yaml", "metadata.yml")
_PLUGIN_ARCHIVE_MAX_ENTRIES = 20_000
_PLUGIN_ARCHIVE_MAX_FILE_SIZE = 128 * 1024 * 1024
_PLUGIN_ARCHIVE_MAX_TOTAL_SIZE = 512 * 1024 * 1024
_ARCHIVE_COPY_CHUNK_SIZE = 64 * 1024
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


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
            await self._download_file(download_url, plugin_path + ".zip")
        else:
            await self.download_from_repo_url(plugin_path, repo_url, proxy)
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
                await self._download_file(download_url, archive_path)
            else:
                await self.download_from_repo_url(
                    os.path.join(staging_dir, "archive"),
                    repo_url,
                    proxy=proxy,
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

            member_written = 0
            with (
                archive.open(member, "r") as source,
                open(
                    destination,
                    "wb",
                ) as target,
            ):
                while chunk := source.read(_ARCHIVE_COPY_CHUNK_SIZE):
                    member_written += len(chunk)
                    total_written += len(chunk)
                    if member_written > _PLUGIN_ARCHIVE_MAX_FILE_SIZE:
                        raise ValueError(
                            f"Plugin archive member exceeds the size limit: {member.filename!r}"
                        )
                    if total_written > _PLUGIN_ARCHIVE_MAX_TOTAL_SIZE:
                        raise ValueError("Plugin archive exceeds the total size limit.")
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
                os.chmod(destination, stat.S_IMODE(mode) & 0o777)
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
        explicit_paths: set[str] = set()
        path_kinds: dict[str, str] = {}
        path_spellings: dict[str, str] = {}
        declared_total_size = 0
        for member in members:
            name = member.filename
            parts = cls._archive_member_parts(name, member.is_dir())
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

            canonical_parts = [part.casefold() for part in parts]
            canonical_path = "/".join(canonical_parts)
            if canonical_path in explicit_paths:
                raise ValueError(
                    f"Plugin archive contains duplicate or case-colliding paths: {name!r}"
                )
            explicit_paths.add(canonical_path)

            for index in range(1, len(parts) + 1):
                canonical_prefix = "/".join(canonical_parts[:index])
                spelling = "/".join(parts[:index])
                previous_spelling = path_spellings.get(canonical_prefix)
                if previous_spelling is not None and previous_spelling != spelling:
                    raise ValueError(
                        f"Plugin archive contains case-colliding paths: {name!r}"
                    )
                path_spellings.setdefault(canonical_prefix, spelling)

            kind = "directory" if member.is_dir() else "file"
            for index in range(1, len(canonical_parts)):
                parent = "/".join(canonical_parts[:index])
                if path_kinds.get(parent) == "file":
                    raise ValueError(
                        f"Plugin archive path conflicts with a file: {name!r}"
                    )
                path_kinds.setdefault(parent, "directory")
            existing_kind = path_kinds.get(canonical_path)
            if existing_kind and existing_kind != kind:
                raise ValueError(f"Plugin archive path has conflicting types: {name!r}")
            path_kinds[canonical_path] = kind

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
            if os.path.islink(current) or (
                os.path.lexists(current) and not os.path.isdir(current)
            ):
                raise ValueError(
                    f"Plugin archive path traverses a non-directory: {current!r}"
                )
            os.makedirs(current, exist_ok=True)
        if os.path.islink(destination):
            raise ValueError(
                f"Plugin archive path targets a symbolic link: {destination!r}"
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
