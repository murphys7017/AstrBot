"""Core-owned Codex SDK runtime and per-thread session adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any


class CodexSdkError(RuntimeError):
    """Raised when the shared Codex SDK runtime cannot serve a session."""


_END_OF_STREAM = object()
_EVENT_QUEUE_SIZE = 64
_INTERRUPT_RPC_TIMEOUT_SECONDS = 3.0
_INTERRUPT_DRAIN_TIMEOUT_SECONDS = 8.0
_RUNTIME_CLOSE_TIMEOUT_SECONDS = 4.0


class CodexSdkRuntime:
    """Own one lazily-started AsyncCodex client for the Core lifetime."""

    def __init__(self, *, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None
        self._lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._close_task: asyncio.Task[Any] | None = None
        self._closed = False

    @property
    def initialized(self) -> bool:
        return self._client is not None

    @property
    def closed(self) -> bool:
        return self._closed

    async def ensure_ready(self) -> Any:
        if self._closed:
            raise CodexSdkError("Codex SDK runtime is closed")
        if self._client is not None:
            return self._client

        async with self._lock:
            if self._closed:
                raise CodexSdkError("Codex SDK runtime is closed")
            if self._client is not None:
                return self._client

            client = (self._client_factory or _build_sdk_client)()
            try:
                await client.__aenter__()
            except (Exception, asyncio.CancelledError) as exc:
                await _close_unpublished_client(client)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise CodexSdkError("Codex SDK runtime failed to start") from exc
            if self._closed:
                await _close_unpublished_client(client)
                raise CodexSdkError("Codex SDK runtime is closed")
            self._client = client
            return client

    async def create_session(
        self,
        *,
        workspace: Path,
        executor_config: Mapping[str, Any],
    ) -> CodexSdkSession:
        _validate_sdk_executor_config(executor_config)
        from openai_codex import ApprovalMode, Sandbox

        client = await self.ensure_ready()
        sandbox = _resolve_sandbox(executor_config, Sandbox)
        thread = await client.thread_start(
            approval_mode=ApprovalMode.deny_all,
            cwd=str(workspace),
            sandbox=sandbox,
        )
        return CodexSdkSession(
            runtime=self,
            thread=thread,
            workspace=workspace,
            approval_mode=ApprovalMode.deny_all,
            sandbox=sandbox,
        )

    async def acquire_turn_slot(self) -> None:
        if self._closed:
            raise CodexSdkError("Codex SDK runtime is closed")
        await self._turn_lock.acquire()
        if self._closed:
            self._turn_lock.release()
            raise CodexSdkError("Codex SDK runtime is closed")

    def release_turn_slot(self) -> None:
        if self._turn_lock.locked():
            self._turn_lock.release()

    async def aclose(self) -> None:
        self._closed = True
        deadline = asyncio.get_running_loop().time() + _RUNTIME_CLOSE_TIMEOUT_SECONDS
        try:
            await asyncio.wait_for(
                self._lock.acquire(), timeout=_RUNTIME_CLOSE_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            raise CodexSdkError(
                "Codex SDK runtime close did not settle within the timeout"
            ) from exc

        try:
            close_task = self._close_task
            if close_task is None and self._client is None:
                return
            if close_task is None:
                client = self._client
                close_task = asyncio.create_task(
                    client.close(), name="codex-sdk-runtime-close"
                )
                close_task.add_done_callback(self._runtime_close_completed)
                self._close_task = close_task
        finally:
            self._lock.release()

        try:
            await asyncio.wait_for(
                asyncio.shield(close_task),
                timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
            )
        except TimeoutError as exc:
            raise CodexSdkError(
                "Codex SDK runtime close did not settle within the timeout"
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._lock:
                if self._close_task is close_task:
                    self._close_task = None
            raise
        else:
            async with self._lock:
                if self._close_task is close_task:
                    self._close_task = None
                    self._client = None

    def _runtime_close_completed(self, task: asyncio.Task[Any]) -> None:
        if self._close_task is not task:
            return
        if task.cancelled():
            self._close_task = None
            return
        if task.exception() is None:
            self._client = None
        self._close_task = None


class CodexSdkSession:
    """Own one SDK thread while borrowing the Core-wide runtime."""

    def __init__(
        self,
        *,
        runtime: CodexSdkRuntime,
        thread: Any,
        workspace: Path,
        approval_mode: Any,
        sandbox: Any,
    ) -> None:
        self._runtime = runtime
        self._thread = thread
        self._workspace = workspace
        self._approval_mode = approval_mode
        self._sandbox = sandbox
        self._turn_lock = asyncio.Lock()
        self._active_turn: Any | None = None
        self._interrupt_task: asyncio.Task[Any] | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._event_queue: asyncio.Queue[Any] | None = None
        self._turn_task: asyncio.Task[Any] | None = None
        self._turn_done: asyncio.Future[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._closed = False
        self._unusable = False

    @property
    def unusable(self) -> bool:
        return self._closed or self._unusable or self._runtime.closed

    def invalidate(self) -> None:
        self._unusable = True

    async def iter_turn(self, prompt: str) -> AsyncIterator[Any]:
        self._check_available()
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Codex turn prompt must be a non-empty string")
        await self._turn_lock.acquire()
        self._turn_task = asyncio.current_task()
        turn_done = asyncio.get_running_loop().create_future()
        self._turn_done = turn_done
        slot_acquired = False
        try:
            self._check_available()
            await self._runtime.acquire_turn_slot()
            slot_acquired = True
            self._check_available()
            try:
                handle = await self._thread.turn(
                    prompt,
                    approval_mode=self._approval_mode,
                    cwd=str(self._workspace),
                    sandbox=self._sandbox,
                )
            except asyncio.CancelledError:
                # The RPC may have reached Codex before cancellation. Without a
                # handle, only closing the runtime can establish that it stopped.
                self._unusable = True
                self._cleanup_task = asyncio.create_task(
                    _close_runtime_bounded(self._runtime)
                )
                await asyncio.shield(self._cleanup_task)
                raise
            self._active_turn = handle
            queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=_EVENT_QUEUE_SIZE)
            self._event_queue = queue
            pump = asyncio.create_task(
                _pump_turn_events(handle, queue),
                name=f"codex-sdk-events:{self._thread.id}",
            )
            self._pump_task = pump
            try:
                while True:
                    if self._closed:
                        raise asyncio.CancelledError("Codex SDK session is closed")
                    item = await queue.get()
                    if item is _END_OF_STREAM:
                        return
                    if isinstance(item, BaseException):
                        raise item
                    yield item
            except (asyncio.CancelledError, GeneratorExit):
                await self._cleanup_turn(pump, queue)
                raise
            finally:
                if pump.done():
                    await asyncio.gather(pump, return_exceptions=True)
        finally:

            def release(_cleanup: asyncio.Task[None] | None = None) -> None:
                if _cleanup is not None and not _cleanup.cancelled():
                    _cleanup.exception()
                self._active_turn = None
                self._event_queue = None
                self._pump_task = None
                self._turn_task = None
                self._turn_done = None
                self._cleanup_task = None
                if self._interrupt_task is not None and self._interrupt_task.done():
                    self._interrupt_task = None
                if slot_acquired:
                    self._runtime.release_turn_slot()
                self._turn_lock.release()
                turn_done.set_result(None)

            cleanup = self._cleanup_task
            if cleanup is not None and not cleanup.done():
                # A second cancellation must not release the slot while the
                # first cancellation is still stopping the remote turn.
                cleanup.add_done_callback(release)
            else:
                release(cleanup)

    def _check_available(self) -> None:
        if self._closed:
            raise CodexSdkError("Codex SDK session is closed")
        if self._unusable:
            raise CodexSdkError("Codex SDK session requires cleanup")
        if self._runtime.closed:
            self._unusable = True
            raise CodexSdkError("Codex SDK runtime is closed")

    async def interrupt(self, _turn_id: str | None = None) -> None:
        task = self._request_active_turn_interrupt()
        if task is not None:
            await asyncio.shield(task)

    def request_stop_for_task(self, task: asyncio.Task[Any]) -> bool:
        """Interrupt only the active turn consumed by the calling task."""
        if task is not self._turn_task or self._active_turn is None:
            return False
        return self._request_active_turn_interrupt() is not None

    def _request_active_turn_interrupt(self) -> asyncio.Task[Any] | None:
        handle = self._active_turn
        if handle is None:
            return None
        task = self._interrupt_task
        if task is None:
            task = asyncio.create_task(handle.interrupt())
            self._interrupt_task = task
        return task

    async def aclose(self) -> None:
        self._closed = True
        task, turn_done = self._turn_task, self._turn_done
        if task is None or turn_done is None:
            return
        if task is asyncio.current_task():
            pump, queue = self._pump_task, self._event_queue
            if pump is not None and queue is not None:
                await self._cleanup_turn(pump, queue)
            return
        # The iterator remains the sole event consumer until its cancellation
        # handler hands ownership to the one cleanup task.
        if self._cleanup_task is None and not task.done():
            task.cancel()
        _, pending = await asyncio.wait(
            {turn_done},
            timeout=(
                _INTERRUPT_RPC_TIMEOUT_SECONDS
                + _INTERRUPT_DRAIN_TIMEOUT_SECONDS
                + 3 * _RUNTIME_CLOSE_TIMEOUT_SECONDS
            ),
        )
        if pending:
            self._unusable = True
            raise CodexSdkError("Codex SDK session close did not settle")

    async def _cleanup_turn(
        self, pump: asyncio.Task[None], queue: asyncio.Queue[Any]
    ) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(
                self._interrupt_and_drain(pump, queue),
                name=f"codex-sdk-cleanup:{self._thread.id}",
            )
        await asyncio.shield(self._cleanup_task)

    async def _interrupt_and_drain(
        self,
        pump: asyncio.Task[None],
        queue: asyncio.Queue[Any],
    ) -> None:
        drain = asyncio.create_task(_discard_turn_events(queue))
        interrupt_task = asyncio.create_task(self.interrupt())
        done, pending = await asyncio.wait(
            {interrupt_task},
            timeout=_INTERRUPT_RPC_TIMEOUT_SECONDS,
        )
        if pending:
            self._unusable = True
            interrupt_task.cancel()
            if self._interrupt_task is not None and not self._interrupt_task.done():
                self._interrupt_task.cancel()
            await _close_runtime_bounded(self._runtime)
        else:
            await asyncio.gather(*done, return_exceptions=True)

        done, pending = await asyncio.wait(
            {pump, drain},
            timeout=_INTERRUPT_DRAIN_TIMEOUT_SECONDS,
        )
        if not pending:
            await asyncio.gather(*done, return_exceptions=True)
            return

        self._unusable = True
        if pump in pending:
            pump.cancel()
        await _close_runtime_bounded(self._runtime)
        _, pending = await asyncio.wait(
            {pump, drain},
            timeout=_RUNTIME_CLOSE_TIMEOUT_SECONDS,
        )
        if drain in pending:
            drain.cancel()
        if pump in pending:
            pump.cancel()
        settling = {task for task in (pump, drain) if task not in pending}
        if settling:
            await asyncio.gather(*settling, return_exceptions=True)


async def _close_runtime_bounded(runtime: CodexSdkRuntime) -> None:
    try:
        await runtime.aclose()
    except Exception:
        pass


async def _pump_turn_events(
    handle: Any,
    queue: asyncio.Queue[Any],
) -> None:
    try:
        async for notification in handle.stream():
            await queue.put(notification)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        await queue.put(exc)
    finally:
        await queue.put(_END_OF_STREAM)


async def _discard_turn_events(queue: asyncio.Queue[Any]) -> None:
    while await queue.get() is not _END_OF_STREAM:
        pass


def _build_sdk_client() -> Any:
    from openai_codex import AsyncCodex

    return AsyncCodex()


async def _close_unpublished_client(client: Any) -> None:
    close_task = asyncio.create_task(client.close())
    try:
        await asyncio.wait_for(
            asyncio.shield(close_task), timeout=_RUNTIME_CLOSE_TIMEOUT_SECONDS
        )
    except BaseException:
        close_task.cancel()
        done, _ = await asyncio.wait(
            {close_task}, timeout=_RUNTIME_CLOSE_TIMEOUT_SECONDS
        )
        if done:
            await asyncio.gather(close_task, return_exceptions=True)


def _validate_sdk_executor_config(config: Mapping[str, Any]) -> None:
    executable = str(config.get("executable", "codex")).strip()
    if executable.casefold() != "codex":
        raise ValueError(
            "Codex SDK uses its pinned bundled runtime; custom executable paths are unsupported"
        )

    request_timeout = _positive_float(
        config.get("request_timeout", 30.0),
        field_name="request_timeout",
    )
    if request_timeout != 30.0:
        raise ValueError(
            "custom Codex request_timeout is unsupported by the SDK; use the Core turn deadline"
        )

    max_message_bytes = _positive_int(
        config.get("max_message_bytes", 4 * 1024 * 1024),
        field_name="max_message_bytes",
    )
    if max_message_bytes != 4 * 1024 * 1024:
        raise ValueError("custom Codex max_message_bytes is unsupported by the SDK")

    approval_policy = str(config.get("approval_policy", "never")).strip().lower()
    if approval_policy not in {"never", "deny_all"}:
        raise ValueError(
            "Codex SDK currently supports only fail-closed approval_policy=never"
        )


def _resolve_sandbox(config: Mapping[str, Any], sandbox_type: Any) -> Any:
    raw_sandbox = str(config.get("sandbox", "workspace-write")).strip().lower()
    if raw_sandbox in {"workspace-write", "workspace_write"}:
        return sandbox_type.workspace_write
    if raw_sandbox in {"read-only", "read_only"}:
        return sandbox_type.read_only
    if raw_sandbox in {"full-access", "full_access", "danger-full-access"}:
        raise ValueError("Codex SDK full-access sandbox is not allowed")
    raise ValueError(f"unsupported Codex sandbox value: {raw_sandbox}")


def _positive_float(value: object, *, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"codex_cli.{field_name} must be a positive number") from exc
    if result <= 0:
        raise ValueError(f"codex_cli.{field_name} must be a positive number")
    return result


def _positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"codex_cli.{field_name} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"codex_cli.{field_name} must be a positive integer") from exc
    if result <= 0:
        raise ValueError(f"codex_cli.{field_name} must be a positive integer")
    return result


__all__ = ["CodexSdkError", "CodexSdkRuntime", "CodexSdkSession"]
