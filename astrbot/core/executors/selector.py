"""Core-wide admission and draining for the active execution backend."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from astrbot.core.config.execution import (
    CORE_EXECUTOR_CODEX_CLI_ID,
    CORE_EXECUTOR_NATIVE_ID,
)

_SUPPORTED_EXECUTORS = frozenset(
    {CORE_EXECUTOR_NATIVE_ID, CORE_EXECUTOR_CODEX_CLI_ID}
)


class CoreExecutorSelectorError(RuntimeError):
    """Base error for Core-wide executor selection and draining."""


class CoreExecutorSwitchInProgress(CoreExecutorSelectorError):
    """Raised when a new run arrives while the Core is draining a switch."""


class CoreExecutorDrainTimeout(CoreExecutorSelectorError):
    """Raised when old runs do not release before the switch deadline."""


class CoreExecutorLease:
    """One admitted Core run whose release participates in backend draining."""

    def __init__(
        self,
        selector: CoreExecutorSelector,
        executor_id: str,
        *,
        stop_preparation: Callable[[], None] | None,
    ) -> None:
        self.executor_id = executor_id
        self._selector = selector
        self._stop_preparation = stop_preparation
        self._stop_run: Callable[[], None] | None = None
        self._stop_requested = False
        self._released = False
        self._stop_errors: list[Exception] = []
        self._cleanup_task: asyncio.Task[Any] | None = None
        self._deferred_release_task: asyncio.Task[Any] | None = None

    @property
    def stop_errors(self) -> tuple[Exception, ...]:
        return tuple(self._stop_errors)

    def bind_stop(self, callback: Callable[[], None]) -> None:
        """Attach the concrete Body stop signal after preparation completes."""

        if self._released:
            raise CoreExecutorSelectorError("executor lease has already been released")
        self._stop_run = callback
        if self._stop_requested:
            self._invoke(callback)

    def bind_cleanup_task(self, task: asyncio.Task[Any]) -> None:
        """Keep the selector lease active until detached Body cleanup settles."""

        if self._released or self._deferred_release_task is not None:
            raise CoreExecutorSelectorError(
                "cannot attach cleanup after executor lease release"
            )
        self._cleanup_task = task

    def request_stop(self) -> None:
        """Request cancellation without waiting for the Body to settle."""

        if self._released:
            return
        self._stop_requested = True
        callback = self._stop_run or self._stop_preparation
        if callback is not None:
            self._invoke(callback)

    def _invoke(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:
            self._stop_errors.append(exc)

    async def aclose(self) -> None:
        if self._released or self._deferred_release_task is not None:
            return
        cleanup = self._cleanup_task
        if cleanup is not None and not cleanup.done():
            self._deferred_release_task = cleanup
            cleanup.add_done_callback(self._cleanup_completed)
            return
        await self._release_now()

    def _cleanup_completed(self, _cleanup: asyncio.Task[Any]) -> None:
        if not self._released:
            asyncio.create_task(self._release_now())

    async def _release_now(self) -> None:
        if self._released:
            return
        self._released = True
        await self._selector._release(self)

    async def __aenter__(self) -> CoreExecutorLease:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()


class CoreExecutorSelector:
    """Own one active executor id and block switching until old runs drain."""

    def __init__(
        self,
        active_executor_id: str,
        *,
        persist_active_executor: Callable[[str], None] | None = None,
    ) -> None:
        self._active_executor_id = _normalize_executor_id(active_executor_id)
        self._persist_active_executor = persist_active_executor
        self._lock = asyncio.Lock()
        self._leases: set[CoreExecutorLease] = set()
        self._drained = asyncio.Event()
        self._drained.set()
        self._switching = False

    @property
    def active_executor_id(self) -> str:
        return self._active_executor_id

    @property
    def switching(self) -> bool:
        return self._switching

    @property
    def active_run_count(self) -> int:
        return len(self._leases)

    async def acquire(
        self,
        executor_id: str,
        *,
        stop_preparation: Callable[[], None] | None = None,
    ) -> CoreExecutorLease:
        """Admit a run only for the current backend and outside a switch."""

        normalized = _normalize_executor_id(executor_id)
        async with self._lock:
            if self._switching:
                raise CoreExecutorSwitchInProgress(
                    "Core executor is switching; new execution is temporarily rejected"
                )
            if normalized != self._active_executor_id:
                raise CoreExecutorSelectorError(
                    "requested executor is not active: "
                    f"requested={normalized} active={self._active_executor_id}"
                )
            lease = CoreExecutorLease(
                self,
                normalized,
                stop_preparation=stop_preparation,
            )
            self._leases.add(lease)
            self._drained.clear()
            return lease

    async def switch_to(
        self,
        executor_id: str,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Stop admission, request old runs to stop, drain, then persist and swap."""

        target = _normalize_executor_id(executor_id)
        timeout = _positive_timeout(timeout_seconds)
        if target not in _SUPPORTED_EXECUTORS:
            raise ValueError(f"unsupported Core executor: {target}")

        async with self._lock:
            if self._switching:
                raise CoreExecutorSwitchInProgress(
                    "another Core executor switch is already in progress"
                )
            if target == self._active_executor_id:
                return
            self._switching = True
            leases = tuple(self._leases)
            for lease in leases:
                lease.request_stop()

        try:
            if leases:
                try:
                    await asyncio.wait_for(self._drained.wait(), timeout=timeout)
                except TimeoutError as exc:
                    raise CoreExecutorDrainTimeout(
                        "Core executor switch timed out waiting for old runs to clean up: "
                        f"active_executor={self._active_executor_id} "
                        f"active_run_count={self.active_run_count}"
                    ) from exc

            async with self._lock:
                if self._leases:
                    raise CoreExecutorDrainTimeout(
                        "Core executor switch cannot proceed while old runs remain active"
                    )
                if self._persist_active_executor is not None:
                    self._persist_active_executor(target)
                self._active_executor_id = target
        finally:
            async with self._lock:
                self._switching = False

    async def _release(self, lease: CoreExecutorLease) -> None:
        async with self._lock:
            self._leases.discard(lease)
            if not self._leases:
                self._drained.set()


def build_core_executor_selector(config_manager: Any) -> CoreExecutorSelector:
    """Migrate one consistent legacy profile choice into the global setting."""

    default_config = config_manager.default_conf
    section = default_config.get("core_executor")
    if not isinstance(section, dict):
        section = {}
        default_config["core_executor"] = section

    active = str(section.get("active_executor_id") or "").strip().lower()
    if active:
        active = _normalize_executor_id(active)
        if active not in _SUPPORTED_EXECUTORS:
            raise ValueError(f"unsupported core_executor.active_executor_id: {active}")
    else:
        profiles = getattr(config_manager, "confs", {"default": default_config})
        legacy_choices: dict[str, str] = {}
        for profile_id, config in profiles.items():
            core_execution = config.get("core_execution", {})
            if not isinstance(core_execution, Mapping):
                raise ValueError(
                    f"configuration {profile_id!r} has an invalid core_execution section"
                )
            choice = _normalize_executor_id(
                core_execution.get("executor_id", CORE_EXECUTOR_NATIVE_ID)
            )
            if choice not in _SUPPORTED_EXECUTORS:
                raise ValueError(
                    f"configuration {profile_id!r} selects unsupported executor {choice!r}"
                )
            legacy_choices[str(profile_id)] = choice

        distinct = set(legacy_choices.values())
        if len(distinct) > 1:
            details = ", ".join(
                f"{profile_id}={choice}"
                for profile_id, choice in sorted(legacy_choices.items())
            )
            raise ValueError(
                "Core executor selection must be global, but legacy profiles conflict: "
                f"{details}. Set core_executor.active_executor_id explicitly."
            )
        active = next(iter(distinct), CORE_EXECUTOR_NATIVE_ID)
        section["active_executor_id"] = active
        save_config = getattr(default_config, "save_config", None)
        if callable(save_config):
            save_config()

    def persist(executor_id: str) -> None:
        section["active_executor_id"] = executor_id
        save_config = getattr(default_config, "save_config", None)
        if callable(save_config):
            save_config()

    return CoreExecutorSelector(active, persist_active_executor=persist)


def _normalize_executor_id(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("executor_id must be a non-empty string")
    return normalized


def _positive_timeout(value: object) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_seconds must be a positive number") from exc
    if timeout <= 0:
        raise ValueError("timeout_seconds must be a positive number")
    return timeout


__all__ = [
    "CoreExecutorDrainTimeout",
    "CoreExecutorLease",
    "CoreExecutorSelector",
    "CoreExecutorSelectorError",
    "CoreExecutorSwitchInProgress",
    "build_core_executor_selector",
]
