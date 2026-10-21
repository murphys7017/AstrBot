"""Core-owned registry for long-lived external executor sessions."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .codex_session import CodexSdkRuntime, CodexSdkSession
from .external import ExternalExecutorSessionKey


@dataclass(slots=True)
class _SessionEntry:
    session: CodexSdkSession
    fingerprint: str


class ExternalExecutorSessionRegistry:
    """Own and reuse one external session per complete execution key."""

    def __init__(self, runtime: CodexSdkRuntime | None = None) -> None:
        self._runtime = runtime or CodexSdkRuntime()
        self._sessions: dict[ExternalExecutorSessionKey, _SessionEntry] = {}
        self._key_locks: dict[ExternalExecutorSessionKey, asyncio.Lock] = {}
        self._creating_tasks: set[asyncio.Task[Any]] = set()
        self._lock = asyncio.Lock()
        self._closed = False

    async def get_or_create(
        self,
        *,
        key: ExternalExecutorSessionKey,
        executor_config: Mapping[str, Any],
    ) -> CodexSdkSession:
        if self._closed:
            raise RuntimeError("external executor session registry is closed")
        if key.executor_id != "codex_cli":
            raise ValueError(f"unsupported external executor: {key.executor_id}")
        fingerprint = _fingerprint_config(executor_config)
        async with self._lock:
            if self._closed:
                raise RuntimeError("external executor session registry is closed")
            key_lock = self._key_locks.setdefault(key, asyncio.Lock())

        async with key_lock:
            async with self._lock:
                if self._closed:
                    raise RuntimeError("external executor session registry is closed")
                existing = self._sessions.get(key)
                if existing is not None and existing.session.unusable:
                    stale = existing
                    existing = None
                else:
                    stale = None
                if (
                    existing is not None
                    and existing.fingerprint == fingerprint
                ):
                    return existing.session
                if stale is None:
                    stale = existing
                creator_task = asyncio.current_task()
                if creator_task is not None:
                    self._creating_tasks.add(creator_task)

            session: CodexSdkSession | None = None
            try:
                if stale is not None:
                    try:
                        await stale.session.aclose()
                    except BaseException:
                        stale.session.invalidate()
                        raise
                    async with self._lock:
                        if self._sessions.get(key) is stale:
                            self._sessions.pop(key, None)
                session = await self._runtime.create_session(
                    workspace=key.workspace,
                    executor_config=executor_config,
                )
                async with self._lock:
                    should_close = self._closed
                    if not should_close:
                        self._sessions[key] = _SessionEntry(
                            session=session,
                            fingerprint=fingerprint,
                        )
                if should_close:
                    await session.aclose()
                    raise RuntimeError("external executor session registry is closed")
                return session
            except BaseException:
                if session is not None:
                    with contextlib.suppress(BaseException):
                        await session.aclose()
                raise
            finally:
                async with self._lock:
                    if creator_task is not None:
                        self._creating_tasks.discard(creator_task)

    async def discard(self, key: ExternalExecutorSessionKey) -> None:
        async with self._lock:
            key_lock = self._key_locks.get(key)
        if key_lock is None:
            return
        async with key_lock:
            async with self._lock:
                entry = self._sessions.get(key)
            if entry is not None:
                await entry.session.aclose()
                async with self._lock:
                    if self._sessions.get(key) is entry:
                        self._sessions.pop(key, None)

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            sessions = [entry.session for entry in self._sessions.values()]
            self._sessions.clear()
            creating = [
                task
                for task in self._creating_tasks
                if task is not asyncio.current_task()
            ]
        if sessions:
            await asyncio.gather(
                *(session.aclose() for session in sessions),
                return_exceptions=True,
            )
        if creating:
            for task in creating:
                task.cancel()
            _, pending = await asyncio.wait(creating, timeout=1.0)
            if pending:
                raise RuntimeError(
                    f"external executor session creation did not stop: {len(pending)} task(s)"
                )

    def __len__(self) -> int:
        return len(self._sessions)


def _fingerprint_config(config: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(config), ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError("external executor configuration must be serializable") from exc


__all__ = ["ExternalExecutorSessionRegistry"]
