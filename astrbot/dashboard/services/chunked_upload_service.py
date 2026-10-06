"""Shared resumable upload session management."""

from __future__ import annotations

import asyncio
import math
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astrbot.core import logger
from astrbot.core.utils.upload import UploadTooLargeError

DEFAULT_CHUNK_SIZE = 1024 * 1024
DEFAULT_EXPIRE_SECONDS = 3600
CLEANUP_INTERVAL_SECONDS = 300


class ChunkedUploadError(Exception):
    """Raised when a resumable upload session is invalid."""


@dataclass
class UploadSession:
    id: str
    owner: str
    purpose: str
    filename: str
    original_filename: str
    total_size: int
    total_chunks: int
    chunk_size: int
    chunk_dir: Path
    meta: dict[str, Any] = field(default_factory=dict)
    received_chunks: set[int] = field(default_factory=set)
    created_at: float = 0.0
    last_activity: float = 0.0


class ChunkedUploadService:
    """Store upload chunks on disk with bounded memory and resumable state."""

    def __init__(
        self,
        chunks_root: str | Path,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        expire_seconds: int = DEFAULT_EXPIRE_SECONDS,
    ) -> None:
        self.chunks_root = Path(chunks_root)
        self.chunk_size = chunk_size
        self.expire_seconds = expire_seconds
        self.sessions: dict[str, UploadSession] = {}
        self._cleanup_task: asyncio.Task | None = None

    def init_session(
        self,
        *,
        owner: str,
        purpose: str,
        filename: str,
        original_filename: str,
        total_size: int,
        meta: dict[str, Any] | None = None,
    ) -> UploadSession:
        if total_size <= 0:
            raise ChunkedUploadError("Invalid file size")
        upload_id = str(uuid.uuid4())
        chunk_dir = self.chunks_root / upload_id
        chunk_dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        session = UploadSession(
            id=upload_id,
            owner=owner,
            purpose=purpose,
            filename=filename,
            original_filename=original_filename,
            total_size=total_size,
            total_chunks=math.ceil(total_size / self.chunk_size),
            chunk_size=self.chunk_size,
            chunk_dir=chunk_dir,
            meta=meta or {},
            created_at=now,
            last_activity=now,
        )
        self.sessions[upload_id] = session
        self.ensure_cleanup_task_started()
        return session

    def get_session(
        self,
        upload_id: str,
        *,
        owner: str | None = None,
        purpose: str | None = None,
    ) -> UploadSession:
        session = self.sessions.get(upload_id)
        expired = session is not None and time.time() - session.last_activity > self.expire_seconds
        if (
            session is None
            or expired
            or (owner is not None and session.owner != owner)
            or (purpose is not None and session.purpose != purpose)
        ):
            raise ChunkedUploadError("Upload session not found or expired")
        return session

    async def save_chunk(
        self,
        upload_id: str,
        chunk_index: int,
        file: Any,
        *,
        owner: str | None = None,
        purpose: str | None = None,
    ) -> dict[str, int]:
        session = self.get_session(upload_id, owner=owner, purpose=purpose)
        if chunk_index < 0 or chunk_index >= session.total_chunks:
            raise ChunkedUploadError("Chunk index out of range")

        chunk_path = session.chunk_dir / f"{chunk_index}.part"
        temp_path = session.chunk_dir / f"{chunk_index}.{uuid.uuid4().hex}.tmp"
        try:
            written = await file.save(temp_path, max_bytes=session.chunk_size)
            expected = min(session.chunk_size, session.total_size - chunk_index * session.chunk_size)
            if written != expected:
                raise ChunkedUploadError(
                    f"Chunk size mismatch: got {written} bytes, expected {expected}"
                )
            await asyncio.to_thread(os.replace, temp_path, chunk_path)
        except UploadTooLargeError as exc:
            temp_path.unlink(missing_ok=True)
            raise ChunkedUploadError("Chunk exceeds the size limit") from exc
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

        session.received_chunks.add(chunk_index)
        session.last_activity = time.time()
        return {
            "received": len(session.received_chunks),
            "total": session.total_chunks,
            "chunk_index": chunk_index,
        }

    def session_status(
        self,
        upload_id: str,
        *,
        owner: str | None = None,
        purpose: str | None = None,
    ) -> dict[str, Any]:
        session = self.get_session(upload_id, owner=owner, purpose=purpose)
        remaining = self.expire_seconds - (time.time() - session.last_activity)
        return {
            "received_chunks": sorted(session.received_chunks),
            "total_chunks": session.total_chunks,
            "chunk_size": session.chunk_size,
            "expires_in": max(0, int(remaining)),
        }

    async def assemble(
        self,
        upload_id: str,
        dest: str | Path,
        *,
        owner: str | None = None,
        purpose: str | None = None,
    ) -> int:
        session = self.get_session(upload_id, owner=owner, purpose=purpose)
        if len(session.received_chunks) != session.total_chunks:
            missing = sorted(set(range(session.total_chunks)) - session.received_chunks)
            raise ChunkedUploadError(f"Chunks incomplete, missing: {missing[:10]}")

        dest_path = Path(dest)
        try:
            with dest_path.open("wb") as output:
                for index in range(session.total_chunks):
                    with (session.chunk_dir / f"{index}.part").open("rb") as part:
                        shutil.copyfileobj(part, output)
            size = dest_path.stat().st_size
            if size != session.total_size:
                raise ChunkedUploadError("Merged size does not match declared size")
        except BaseException:
            dest_path.unlink(missing_ok=True)
            raise
        await self.cleanup_session(upload_id)
        return size

    async def abort(self, upload_id: str, *, owner: str | None = None, purpose: str | None = None) -> bool:
        session = self.sessions.get(upload_id)
        if session is None:
            return False
        if owner is not None and session.owner != owner:
            raise ChunkedUploadError("Upload session not found or expired")
        if purpose is not None and session.purpose != purpose:
            raise ChunkedUploadError("Upload session not found or expired")
        await self.cleanup_session(upload_id)
        return True

    async def cleanup_session(self, upload_id: str) -> None:
        session = self.sessions.get(upload_id)
        if session is None:
            return
        try:
            shutil.rmtree(session.chunk_dir, ignore_errors=False)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Failed to clean upload session %s: %s", upload_id, exc)
            return
        self.sessions.pop(upload_id, None)

    def ensure_cleanup_task_started(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                self._cleanup_task = asyncio.create_task(self._cleanup_expired_sessions())
            except RuntimeError:
                pass

    async def _cleanup_expired_sessions(self) -> None:
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                now = time.time()
                expired = [
                    upload_id
                    for upload_id, session in self.sessions.items()
                    if now - session.last_activity > self.expire_seconds
                ]
                for upload_id in expired:
                    await self.cleanup_session(upload_id)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Failed to clean upload sessions: %s", exc)
