import inspect
import os
import re
import shutil
import stat
import tempfile
import time
import zipfile
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn

import certifi
import httpx

from astrbot.core import logger
from astrbot.core.utils.io import ensure_dir, on_error
from astrbot.core.utils.version_comparator import VersionComparator

_REPO_ARCHIVE_MAX_ENTRIES = 20_000
_REPO_ARCHIVE_MAX_CENTRAL_DIRECTORY_SIZE = 8 * 1024 * 1024
_REPO_ARCHIVE_MAX_PATH_LENGTH = 4096
_REPO_ARCHIVE_MAX_PATH_DEPTH = 128
_REPO_ARCHIVE_MAX_TOTAL_PATH_LENGTH = 16 * 1024 * 1024
_REPO_ARCHIVE_MAX_PATH_NODES = 100_000
_REPO_ARCHIVE_MAX_FILE_SIZE = 128 * 1024 * 1024
_REPO_ARCHIVE_MAX_TOTAL_SIZE = 512 * 1024 * 1024
_ARCHIVE_COPY_CHUNK_SIZE = 64 * 1024
_CENTRAL_DIRECTORY_HEADER_SIGNATURE = b"PK\x01\x02"
_CENTRAL_DIRECTORY_HEADER_SIZE = 46
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{digit}" for digit in "123456789\u00b9\u00b2\u00b3"),
    *(f"lpt{digit}" for digit in "123456789\u00b9\u00b2\u00b3"),
}


def _is_symlink_or_junction(path: str) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return os.path.islink(path) or (is_junction is not None and is_junction(path))


@dataclass(slots=True)
class _ArchivePathNode:
    spelling: str | None = None
    kind: str | None = None
    children: dict[str, "_ArchivePathNode"] = field(default_factory=dict)


class ReleaseInfo:
    version: str
    published_at: str
    body: str

    def __init__(
        self,
        version: str = "",
        published_at: str = "",
        body: str = "",
    ) -> None:
        self.version = version
        self.published_at = published_at
        self.body = body

    def __str__(self) -> str:
        return f"\n{self.body}\n\n版本: {self.version} | 发布于: {self.published_at}"


class RepoZipUpdator:
    def __init__(self, repo_mirror: str = "", verify: str | bool | None = None) -> None:
        self.repo_mirror = repo_mirror
        self.rm_on_error = on_error
        self.httpx_verify = certifi.where() if verify is None else verify

    def _create_httpx_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            trust_env=True,
            verify=self.httpx_verify,
        )

    @staticmethod
    def _read_archive_entry_count(zip_path: str | Path) -> int | None:
        # Bound and count central-directory records before ZipFile materializes them.
        with open(zip_path, "rb") as archive_file:
            end_record = zipfile._EndRecData(archive_file)
            if end_record is None:
                return None

            declared_count = int(end_record[4])
            directory_size = int(end_record[5])
            directory_offset = int(end_record[6])
            if declared_count > _REPO_ARCHIVE_MAX_ENTRIES:
                raise ValueError("Update archive contains too many entries.")
            if directory_size > _REPO_ARCHIVE_MAX_CENTRAL_DIRECTORY_SIZE:
                raise ValueError("Update archive central directory is too large.")

            concat = int(end_record[9]) - directory_size - directory_offset
            if end_record[0] == zipfile.stringEndArchive64:
                concat -= zipfile.sizeEndCentDir64 + zipfile.sizeEndCentDir64Locator
            archive_file.seek(directory_offset + concat)

            remaining = directory_size
            actual_count = 0
            while remaining:
                header = archive_file.read(_CENTRAL_DIRECTORY_HEADER_SIZE)
                if (
                    len(header) != _CENTRAL_DIRECTORY_HEADER_SIZE
                    or header[:4] != _CENTRAL_DIRECTORY_HEADER_SIGNATURE
                ):
                    raise zipfile.BadZipFile("Invalid central directory entry.")
                filename_size = int.from_bytes(header[28:30], "little")
                extra_size = int.from_bytes(header[30:32], "little")
                comment_size = int.from_bytes(header[32:34], "little")
                record_size = (
                    _CENTRAL_DIRECTORY_HEADER_SIZE
                    + filename_size
                    + extra_size
                    + comment_size
                )
                if record_size > remaining:
                    raise zipfile.BadZipFile("Truncated central directory entry.")
                archive_file.seek(record_size - _CENTRAL_DIRECTORY_HEADER_SIZE, 1)
                remaining -= record_size
                actual_count += 1
                if actual_count > _REPO_ARCHIVE_MAX_ENTRIES:
                    raise ValueError("Update archive contains too many entries.")

            if actual_count != declared_count:
                raise zipfile.BadZipFile(
                    "Central directory entry count does not match the ZIP trailer."
                )
            return actual_count

    @staticmethod
    def _truncate_response_body(body: str, max_len: int = 1000) -> str:
        if len(body) <= max_len:
            return body
        return body[:max_len] + "...[truncated]"

    async def _download_file(
        self,
        url: str,
        path: str,
        timeout: float = 1800.0,
        progress_callback=None,
        *,
        max_size: int | None = None,
    ) -> None:
        if max_size is not None and max_size < 0:
            raise ValueError("Download size limit cannot be negative.")
        target_path = Path(path)
        ensure_dir(target_path.parent)

        async def emit_progress(payload: dict) -> None:
            if not progress_callback:
                return
            result = progress_callback(payload)
            if inspect.isawaitable(result):
                await result

        try:
            async with self._create_httpx_client(timeout=timeout) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))
                    if max_size is not None and total_size > max_size:
                        raise ValueError(
                            f"Download exceeds the size limit of {max_size} bytes."
                        )
                    downloaded_size = 0
                    start_time = time.time()
                    await emit_progress(
                        {
                            "url": url,
                            "downloaded": 0,
                            "total": total_size,
                            "percent": 0,
                            "speed": 0,
                        }
                    )
                    with target_path.open("wb") as file:
                        async for chunk in response.aiter_bytes(8192):
                            if (
                                max_size is not None
                                and downloaded_size + len(chunk) > max_size
                            ):
                                raise ValueError(
                                    f"Download exceeds the size limit of {max_size} bytes."
                                )
                            file.write(chunk)
                            downloaded_size += len(chunk)
                            elapsed_time = max(time.time() - start_time, 1)
                            await emit_progress(
                                {
                                    "url": url,
                                    "downloaded": downloaded_size,
                                    "total": total_size,
                                    "percent": downloaded_size / total_size
                                    if total_size > 0
                                    else 0,
                                    "speed": downloaded_size / 1024 / elapsed_time,
                                }
                            )
                    await emit_progress(
                        {
                            "url": url,
                            "downloaded": downloaded_size,
                            "total": total_size,
                            "percent": 1,
                            "speed": 0,
                        }
                    )
        except Exception as e:
            logger.error(f"下载文件失败: {url} -> {target_path}, 错误: {e}")
            if self.rm_on_error and target_path.exists():
                target_path.unlink()
            raise

    async def fetch_release_info(self, url: str, latest: bool = True) -> list:
        """请求版本信息。
        返回一个列表，每个元素是一个字典，包含版本号、发布时间、更新内容、commit hash等信息。
        """
        try:
            async with self._create_httpx_client() as client:
                response = await client.get(url)
                response.raise_for_status()
                result = response.json()
            if not result:
                return []
            # if latest:
            #     ret = self.github_api_release_parser([result[0]])
            # else:
            #     ret = self.github_api_release_parser(result)
            ret = []
            for release in result:
                ret.append(
                    {
                        "version": release["name"],
                        "published_at": release["published_at"],
                        "body": release["body"],
                        "tag_name": release["tag_name"],
                        "zipball_url": release["zipball_url"],
                    },
                )
        except httpx.HTTPStatusError as e:
            response_body = ""
            if e.response is not None:
                response_body = self._truncate_response_body(e.response.text)
                logger.error(
                    f"请求 {url} 失败，状态码: {e.response.status_code}, 内容: {response_body}",
                )
            raise Exception("解析版本信息失败") from e
        except Exception as e:
            logger.error(f"解析版本信息时发生异常: {e}")
            raise Exception("解析版本信息失败") from e
        return ret

    def github_api_release_parser(self, releases: list) -> list:
        """解析 GitHub API 返回的 releases 信息。
        返回一个列表，每个元素是一个字典，包含版本号、发布时间、更新内容、commit hash等信息。
        """
        ret = []
        for release in releases:
            ret.append(
                {
                    "version": release["name"],
                    "published_at": release["published_at"],
                    "body": release["body"],
                    "tag_name": release["tag_name"],
                    "zipball_url": release["zipball_url"],
                },
            )
        return ret

    def unzip(self) -> NoReturn:
        raise NotImplementedError

    async def update(self) -> NoReturn:
        raise NotImplementedError

    def compare_version(self, v1: str, v2: str) -> int:
        """Semver 版本比较"""
        return VersionComparator.compare_version(v1, v2)

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
            raise ValueError(f"Unsafe update archive path: {name!r}")

        parts = name.split("/")
        if is_dir and parts[-1] == "":
            parts.pop()
        while parts and parts[0] == ".":
            parts.pop(0)
        if not parts:
            if is_dir:
                return []
            raise ValueError(f"Unsafe update archive path: {name!r}")
        for part in parts:
            windows_basename = part.split(".", 1)[0].casefold()
            if (
                part in {"", ".", ".."}
                or part.rstrip(" .") != part
                or any(char in part for char in '<>:"|?*')
                or any(ord(char) < 32 for char in part)
                or windows_basename in _WINDOWS_RESERVED_NAMES
            ):
                raise ValueError(f"Unsafe update archive path: {name!r}")
        return parts

    @classmethod
    def _validate_archive_members(
        cls,
        archive: zipfile.ZipFile,
        target_dir: str,
    ) -> list[tuple[zipfile.ZipInfo, list[str]]]:
        members = archive.infolist()
        if len(members) > _REPO_ARCHIVE_MAX_ENTRIES:
            raise ValueError("Update archive contains too many entries.")

        target_root = os.path.abspath(target_dir)
        path_tree = _ArchivePathNode()
        path_node_count = 1
        total_path_length = 0
        declared_total_size = 0
        validated_members = []
        for member in members:
            name = member.filename
            if len(name) > _REPO_ARCHIVE_MAX_PATH_LENGTH:
                raise ValueError(f"Update archive path is too long: {name!r}")
            total_path_length += len(name)
            if total_path_length > _REPO_ARCHIVE_MAX_TOTAL_PATH_LENGTH:
                raise ValueError("Update archive contains too much path data.")

            parts = cls._archive_member_parts(name, member.is_dir())
            if len(parts) > _REPO_ARCHIVE_MAX_PATH_DEPTH:
                raise ValueError(f"Update archive path is too deep: {name!r}")
            destination = os.path.abspath(os.path.join(target_root, *parts))
            try:
                common_path = os.path.commonpath([target_root, destination])
            except ValueError as exc:
                raise ValueError(f"Unsafe update archive path: {name!r}") from exc
            if os.path.normcase(common_path) != os.path.normcase(target_root):
                raise ValueError(f"Unsafe update archive path: {name!r}")

            mode = member.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK:
                raise ValueError(f"Update archive symlink is not allowed: {name!r}")
            if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f"Unsupported update archive entry type: {name!r}")
            if member.is_dir() != (file_type == stat.S_IFDIR) and file_type:
                raise ValueError(f"Invalid update archive entry type: {name!r}")

            node = path_tree
            for part in parts:
                if node.kind == "file":
                    raise ValueError(
                        f"Update archive path conflicts with a file: {name!r}"
                    )
                key = part.casefold()
                child = node.children.get(key)
                if child is None:
                    if path_node_count >= _REPO_ARCHIVE_MAX_PATH_NODES:
                        raise ValueError("Update archive contains too many path nodes.")
                    child = _ArchivePathNode(spelling=part)
                    node.children[key] = child
                    path_node_count += 1
                elif child.spelling != part:
                    raise ValueError(
                        f"Update archive contains case-colliding paths: {name!r}"
                    )
                node = child

            kind = "directory" if member.is_dir() else "file"
            if node.kind and node.kind != kind:
                raise ValueError(f"Update archive path has conflicting types: {name!r}")
            if node.kind:
                raise ValueError(f"Update archive contains duplicate paths: {name!r}")
            if kind == "file" and node.children:
                raise ValueError(
                    f"Update archive path conflicts with a directory: {name!r}"
                )
            node.kind = kind

            if member.file_size < 0:
                raise ValueError(f"Update archive member has an invalid size: {name!r}")
            if member.is_dir():
                if member.file_size:
                    raise ValueError(f"Update archive directory is not empty: {name!r}")
            else:
                if member.file_size > _REPO_ARCHIVE_MAX_FILE_SIZE:
                    raise ValueError(
                        f"Update archive member exceeds the size limit: {name!r}"
                    )
                declared_total_size += member.file_size
                if declared_total_size > _REPO_ARCHIVE_MAX_TOTAL_SIZE:
                    raise ValueError("Update archive exceeds the total size limit.")
            validated_members.append((member, parts))
        return validated_members

    @staticmethod
    def _prepare_archive_destination(target_root: str, parts: list[str]) -> str:
        destination = os.path.abspath(os.path.join(target_root, *parts))
        try:
            common_path = os.path.commonpath([target_root, destination])
        except ValueError as exc:
            raise ValueError("Unsafe update archive path.") from exc
        if os.path.normcase(common_path) != os.path.normcase(target_root):
            raise ValueError("Unsafe update archive path.")

        current = target_root
        for part in parts[:-1]:
            current = os.path.join(current, part)
            if _is_symlink_or_junction(current) or (
                os.path.lexists(current) and not os.path.isdir(current)
            ):
                raise ValueError(
                    "Update archive path traverses a symbolic link, junction, "
                    f"or non-directory: {current!r}"
                )
            os.makedirs(current, exist_ok=True)
        if _is_symlink_or_junction(destination):
            raise ValueError(
                f"Update archive path targets a symbolic link or junction: {destination!r}"
            )
        return destination

    @classmethod
    def _extract_archive_members(
        cls,
        archive: zipfile.ZipFile,
        target_dir: str,
        members: list[tuple[zipfile.ZipInfo, list[str]]],
    ) -> None:
        target_root = os.path.abspath(target_dir)
        total_written = 0
        for member, parts in members:
            if not parts:
                continue
            destination = cls._prepare_archive_destination(target_root, parts)
            if member.is_dir():
                if os.path.lexists(destination) and not os.path.isdir(destination):
                    raise ValueError(
                        f"Update archive directory conflicts with an existing file: {destination!r}"
                    )
                os.makedirs(destination, exist_ok=True)
                continue
            if os.path.lexists(destination) and not os.path.isfile(destination):
                raise ValueError(
                    f"Update archive file conflicts with an existing directory: {destination!r}"
                )

            fd, temporary_path = tempfile.mkstemp(
                prefix=".astrbot-update-",
                dir=os.path.dirname(destination),
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
                        if member_written > _REPO_ARCHIVE_MAX_FILE_SIZE:
                            raise ValueError(
                                f"Update archive member exceeds the size limit: {member.filename!r}"
                            )
                        if total_written > _REPO_ARCHIVE_MAX_TOTAL_SIZE:
                            raise ValueError(
                                "Update archive exceeds the total size limit."
                            )
                        if member_written > member.file_size:
                            raise ValueError(
                                f"Update archive member expands beyond its declared size: {member.filename!r}"
                            )
                        target.write(chunk)
                if member_written != member.file_size:
                    raise ValueError(
                        f"Update archive member size does not match its directory entry: {member.filename!r}"
                    )
                os.replace(temporary_path, destination)
                mode = member.external_attr >> 16
                if stat.S_ISREG(mode):
                    os.chmod(destination, stat.S_IMODE(mode) & 0o777)
            finally:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)

    async def check_update(
        self,
        url: str,
        current_version: str,
        consider_prerelease: bool = True,
    ) -> ReleaseInfo | None:
        update_data = await self.fetch_release_info(url)

        sel_release_data = None
        if consider_prerelease:
            tag_name = update_data[0]["tag_name"]
            sel_release_data = update_data[0]
        else:
            for data in update_data:
                # 跳过带有 alpha、beta 等预发布标签的版本
                if re.search(
                    r"[\-_.]?(alpha|beta|rc|dev)[\-_.]?\d*$",
                    data["tag_name"],
                    re.IGNORECASE,
                ):
                    continue
                tag_name = data["tag_name"]
                sel_release_data = data
                break

        if not sel_release_data or not tag_name:
            logger.error("未找到合适的发布版本")
            return None

        if self.compare_version(current_version, tag_name) >= 0:
            return None
        return ReleaseInfo(
            version=tag_name,
            published_at=sel_release_data["published_at"],
            body=f"{tag_name}\n\n{sel_release_data['body']}",
        )

    async def download_from_repo_url(
        self,
        target_path: str,
        repo_url: str,
        proxy="",
        *,
        max_size: int | None = None,
    ) -> None:
        author, repo, branch = self.parse_github_url(repo_url)

        logger.info(f"正在下载更新 {repo} ...")

        if branch:
            logger.info(f"正在从指定分支 {branch} 下载 {author}/{repo}")
            release_url = (
                f"https://github.com/{author}/{repo}/archive/refs/heads/{branch}.zip"
            )
        else:
            # GitHub resolves HEAD to the repository's configured default branch.
            # This avoids a separate metadata request and does not assume master.
            logger.info(f"正在从默认引用 HEAD 下载 {author}/{repo}")
            release_url = f"https://github.com/{author}/{repo}/archive/HEAD.zip"

        if proxy:
            proxy = proxy.rstrip("/")
            release_url = f"{proxy}/{release_url}"
            logger.info(
                f"检查到设置了镜像站，将使用镜像站下载 {author}/{repo} 仓库源码: {release_url}",
            )

        if max_size is None:
            await self._download_file(release_url, target_path + ".zip")
        else:
            await self._download_file(
                release_url,
                target_path + ".zip",
                max_size=max_size,
            )

    def parse_github_url(self, url: str):
        """使用正则表达式解析 GitHub 仓库 URL，支持 `.git` 后缀和 `tree/branch` 结构
        Returns:
            tuple[str, str, str]: 返回作者名、仓库名和分支名
        Raises:
            ValueError: 如果 URL 格式不正确
        """
        cleaned_url = url.rstrip("/")
        pattern = r"^https://github\.com/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)(\.git)?(?:/tree/([a-zA-Z0-9_-]+))?$"
        match = re.match(pattern, cleaned_url)

        if match:
            author = match.group(1)
            repo = match.group(2)
            branch = match.group(4)
            return author, repo, branch
        raise ValueError("无效的 GitHub URL")

    def unzip_file(self, zip_path: str, target_dir: str) -> None:
        """解压缩文件, 并将压缩包内**第一个**文件夹内的文件移动到 target_dir"""
        entry_count = self._read_archive_entry_count(zip_path)
        if entry_count is not None and entry_count > _REPO_ARCHIVE_MAX_ENTRIES:
            raise ValueError("Update archive contains too many entries.")
        ensure_dir(target_dir)
        with zipfile.ZipFile(zip_path, "r") as z:
            validated_members = self._validate_archive_members(z, target_dir)
            update_dir = self._resolve_archive_root_dir(z.namelist())
            self._extract_archive_members(z, target_dir, validated_members)
        logger.debug(f"解压文件完成: {zip_path}")

        self._finalize_extracted_archive(zip_path, target_dir, update_dir)

    @staticmethod
    def _resolve_archive_root_dir(entries: list[str]) -> str:
        normalized_entries = [os.path.normpath(entry) for entry in entries]
        portable_entries = [entry.replace("\\", "/") for entry in normalized_entries]
        root_candidates: list[str] = []
        sorted_entries = sorted(portable_entries)

        for raw_entry, normalized_entry, portable_entry in zip(
            entries, normalized_entries, portable_entries
        ):
            if normalized_entry == ".":
                continue

            child_index = bisect_left(sorted_entries, f"{portable_entry}/")
            has_children = child_index < len(sorted_entries) and sorted_entries[
                child_index
            ].startswith(f"{portable_entry}/")
            if raw_entry.endswith(("/", "\\")) or has_children:
                root_candidates.append(normalized_entry)
                continue

            parent_portable, _, _ = portable_entry.rpartition("/")
            if not parent_portable:
                return ""
            root_candidates.append(parent_portable.replace("/", os.sep))

        if not root_candidates:
            return ""
        return os.path.commonpath(root_candidates)

    def _finalize_extracted_archive(
        self,
        zip_path: str,
        target_dir: str,
        update_dir: str,
    ) -> None:
        target_root_path = os.path.normpath(target_dir)

        def _join_under_root(root: str, *parts: str) -> str:
            path = os.path.normpath(os.path.join(root, *parts))
            try:
                if os.path.commonpath([root, path]) != root:
                    raise ValueError("path escapes root directory")
            except ValueError as exc:
                raise ValueError("path escapes root directory") from exc
            return path

        if not update_dir:
            try:
                os.remove(zip_path)
            except Exception:
                logger.warning(f"删除更新文件失败，可以手动删除 {zip_path}")
            return

        update_root_path = _join_under_root(target_root_path, update_dir)

        files = os.listdir(update_root_path)
        for f in files:
            update_item_path = _join_under_root(update_root_path, f)
            target_item_path = _join_under_root(target_root_path, f)
            if os.path.isdir(update_item_path):
                if os.path.exists(target_item_path):
                    shutil.rmtree(target_item_path, onerror=on_error)
            elif os.path.exists(target_item_path):
                os.remove(target_item_path)
            shutil.move(update_item_path, target_root_path)

        try:
            logger.debug(f"删除临时更新文件: {zip_path} 和 {update_root_path}")
            shutil.rmtree(update_root_path, onerror=on_error)
            os.remove(zip_path)
        except Exception:
            logger.warning(
                f"删除更新文件失败，可以手动删除 {zip_path} 和 {update_root_path}"
            )

    def format_name(self, name: str) -> str:
        return name.replace("-", "_").lower()
