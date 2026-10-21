import asyncio
import sys
from enum import Enum
from types import SimpleNamespace

import pytest

from astrbot.core.executors.codex_session import (
    CodexSdkRuntime,
    CodexSdkRuntimeBusy,
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
async def test_runtime_rejects_overlapping_turns_across_threads(monkeypatch, tmp_path):
    _install_sdk_types(monkeypatch)
    first_handle = _FakeHandle(blocked=True)
    client = _FakeClient([first_handle, _FakeHandle()])
    runtime = CodexSdkRuntime(client_factory=lambda: client)
    first = await runtime.create_session(workspace=tmp_path, executor_config={})
    second = await runtime.create_session(workspace=tmp_path, executor_config={})

    first_turn = asyncio.create_task(
        _collect_events(first, "first request")
    )
    await asyncio.wait_for(first_handle.started.wait(), timeout=1)
    with pytest.raises(CodexSdkRuntimeBusy, match="already has an active turn"):
        await _collect_events(second, "second request")

    first_handle.release.set()
    await first_turn
    await first.aclose()
    await second.aclose()
    await runtime.aclose()


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
