import asyncio
import sys
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrbot.core.executors.codex_session import (
    CodexSdkError,
    CodexSdkRuntime,
)


class _ApprovalMode(Enum):
    deny_all = "deny_all"


class _Sandbox(Enum):
    workspace_write = "workspace-write"
    read_only = "read-only"


def _install_sdk_types(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "openai_codex",
        SimpleNamespace(ApprovalMode=_ApprovalMode, Sandbox=_Sandbox),
    )


class _FakeHandle:
    def __init__(self, *, blocked=False, block_interrupt=False):
        self.blocked = blocked
        self.block_interrupt = block_interrupt
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.interrupted = asyncio.Event()

    async def stream(self):
        self.started.set()
        if self.blocked:
            await self.release.wait()
        if self.interrupted.is_set():
            yield SimpleNamespace(method="turn/completed", payload=None)
            return
        yield SimpleNamespace(method="turn/started", payload=None)
        yield SimpleNamespace(method="turn/completed", payload=None)

    async def interrupt(self):
        if self.block_interrupt:
            await asyncio.Future()
        self.interrupted.set()
        self.release.set()


class _FakeThread:
    def __init__(self, thread_id, handle):
        self.id = thread_id
        self.handle = handle
        self.calls = []

    async def turn(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.handle


class _FakeClient:
    def __init__(self, handles):
        self.handles = iter(handles)
        self.enter_count = 0
        self.close_count = 0
        self.threads = []

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def thread_start(self, **kwargs):
        thread = _FakeThread(f"thread-{len(self.threads) + 1}", next(self.handles))
        thread.start_kwargs = kwargs
        self.threads.append(thread)
        return thread

    async def close(self):
        self.close_count += 1


class _BlockingEnterClient:
    def __init__(self):
        self.enter_started = asyncio.Event()
        self.enter_release = asyncio.Event()
        self.close_count = 0

    async def __aenter__(self):
        self.enter_started.set()
        await self.enter_release.wait()
        return self

    async def close(self):
        self.close_count += 1
        self.enter_release.set()


class _BlockingCloseClient:
    def __init__(self):
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_count = 0

    async def __aenter__(self):
        return self

    async def close(self):
        self.close_count += 1
        self.close_started.set()
        await self.close_release.wait()


@pytest.mark.asyncio
async def test_runtime_reuses_client_and_isolates_threads(monkeypatch, tmp_path):
    _install_sdk_types(monkeypatch)
    handles = [_FakeHandle(), _FakeHandle()]
    client = _FakeClient(handles)
    runtime = CodexSdkRuntime(client_factory=lambda: client)

    first = await runtime.create_session(
        workspace=tmp_path,
        executor_config={"sandbox": "workspace-write"},
    )
    second = await runtime.create_session(
        workspace=tmp_path,
        executor_config={"sandbox": "read-only"},
    )

    assert client.enter_count == 1
    assert len(client.threads) == 2
    assert client.threads[0].start_kwargs["approval_mode"] is _ApprovalMode.deny_all
    assert client.threads[0].start_kwargs["sandbox"] is _Sandbox.workspace_write
    assert client.threads[1].start_kwargs["sandbox"] is _Sandbox.read_only

    events = [event async for event in first.iter_turn("first request")]
    assert [event.method for event in events] == ["turn/started", "turn/completed"]
    assert client.threads[0].calls[0][0] == "first request"
    assert client.threads[1].calls == []

    await first.aclose()
    await second.aclose()
    await runtime.aclose()
    assert client.close_count == 1
    assert first.unusable is True
    assert second.unusable is True


@pytest.mark.asyncio
async def test_cancel_during_runtime_start_closes_unpublished_client():
    client = _BlockingEnterClient()
    runtime = CodexSdkRuntime(client_factory=lambda: client)
    start = asyncio.create_task(runtime.ensure_ready())

    await asyncio.wait_for(client.enter_started.wait(), timeout=1)
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert client.close_count == 1
    assert runtime.initialized is False


@pytest.mark.asyncio
async def test_runtime_close_is_bounded_while_startup_holds_lock(monkeypatch):
    import astrbot.core.executors.codex_session as codex_session

    monkeypatch.setattr(codex_session, "_RUNTIME_CLOSE_TIMEOUT_SECONDS", 0.01)
    client = _BlockingEnterClient()
    runtime = CodexSdkRuntime(client_factory=lambda: client)
    startup = asyncio.create_task(runtime.ensure_ready())

    await asyncio.wait_for(client.enter_started.wait(), timeout=1)
    with pytest.raises(CodexSdkError, match="close did not settle"):
        await runtime.aclose()

    assert runtime.closed is True
    assert runtime.initialized is False

    client.enter_release.set()
    with pytest.raises(CodexSdkError, match="runtime is closed"):
        await asyncio.wait_for(startup, timeout=1)
    assert client.close_count == 1
    await runtime.aclose()


@pytest.mark.asyncio
async def test_runtime_serializes_overlapping_turns_across_threads(monkeypatch):
    _install_sdk_types(monkeypatch)
    first_handle = _FakeHandle(blocked=True)
    second_handle = _FakeHandle()
    client = _FakeClient([first_handle, second_handle])
    runtime = CodexSdkRuntime(client_factory=lambda: client)
    first = await runtime.create_session(workspace=Path.cwd(), executor_config={})
    second = await runtime.create_session(workspace=Path.cwd(), executor_config={})

    first_turn = asyncio.create_task(
        _collect_events(first, "first request")
    )
    await asyncio.wait_for(first_handle.started.wait(), timeout=1)
    second_turn = asyncio.create_task(
        _collect_events(second, "second request")
    )
    await asyncio.sleep(0)
    assert not second_handle.started.is_set()

    first_handle.release.set()
    first_events, second_events = await asyncio.gather(
        asyncio.wait_for(first_turn, timeout=1),
        asyncio.wait_for(second_turn, timeout=1),
    )
    assert [event.method for event in first_events] == [
        "turn/started",
        "turn/completed",
    ]
    assert [event.method for event in second_events] == [
        "turn/started",
        "turn/completed",
    ]
    assert second_handle.started.is_set()
    await first.aclose()
    await second.aclose()
    await runtime.aclose()


@pytest.mark.asyncio
async def test_cancelled_queued_turn_does_not_interrupt_active_turn(monkeypatch):
    _install_sdk_types(monkeypatch)
    first_handle = _FakeHandle(blocked=True)
    second_handle = _FakeHandle()
    client = _FakeClient([first_handle, second_handle])
    runtime = CodexSdkRuntime(client_factory=lambda: client)
    first = await runtime.create_session(workspace=Path.cwd(), executor_config={})
    second = await runtime.create_session(workspace=Path.cwd(), executor_config={})

    first_turn = asyncio.create_task(_collect_events(first, "first request"))
    await asyncio.wait_for(first_handle.started.wait(), timeout=1)
    queued_turn = asyncio.create_task(_collect_events(second, "queued request"))
    await asyncio.sleep(0)
    assert not second_handle.started.is_set()

    queued_turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(queued_turn, timeout=1)
    assert not first_handle.interrupted.is_set()

    first_handle.release.set()
    await asyncio.wait_for(first_turn, timeout=1)
    retry_events = await asyncio.wait_for(
        _collect_events(second, "retry request"),
        timeout=1,
    )
    assert [event.method for event in retry_events] == [
        "turn/started",
        "turn/completed",
    ]

    await first.aclose()
    await second.aclose()
    await runtime.aclose()


@pytest.mark.asyncio
async def test_runtime_close_is_bounded_and_can_be_retried(monkeypatch):
    import astrbot.core.executors.codex_session as codex_session

    monkeypatch.setattr(codex_session, "_RUNTIME_CLOSE_TIMEOUT_SECONDS", 0.01)
    client = _BlockingCloseClient()
    runtime = CodexSdkRuntime(client_factory=lambda: client)
    await runtime.ensure_ready()

    with pytest.raises(CodexSdkError, match="close did not settle"):
        await runtime.aclose()

    assert runtime.closed is True
    assert runtime.initialized is True
    assert client.close_count == 1

    client.close_release.set()
    await runtime.aclose()

    assert runtime.initialized is False
    assert client.close_count == 1


@pytest.mark.asyncio
async def test_cancel_bounds_interrupt_and_closes_unresponsive_runtime(
    monkeypatch,
    tmp_path,
):
    import astrbot.core.executors.codex_session as codex_session

    _install_sdk_types(monkeypatch)
    monkeypatch.setattr(codex_session, "_INTERRUPT_RPC_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(codex_session, "_INTERRUPT_DRAIN_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(codex_session, "_RUNTIME_CLOSE_TIMEOUT_SECONDS", 0.1)
    handle = _FakeHandle(blocked=True, block_interrupt=True)
    client = _FakeClient([handle])
    runtime = CodexSdkRuntime(client_factory=lambda: client)
    session = await runtime.create_session(workspace=tmp_path, executor_config={})
    turn = asyncio.create_task(_collect_events(session, "cancel me"))
    await asyncio.wait_for(handle.started.wait(), timeout=1)

    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(turn, timeout=1)

    assert client.close_count == 1
    assert session.unusable is True


async def _collect_events(session, prompt):
    return [event async for event in session.iter_turn(prompt)]
