import asyncio
from pathlib import Path

import pytest

from astrbot.core.executors.external import ExternalExecutorSessionKey
from astrbot.core.executors.session_registry import ExternalExecutorSessionRegistry


class _Session:
    def __init__(self, workspace, config):
        self.workspace = workspace
        self.config = dict(config)
        self.closed = False
        self.unusable = False

    async def aclose(self):
        self.closed = True

    def invalidate(self):
        self.unusable = True


class _Runtime:
    def __init__(self):
        self.sessions = []

    async def create_session(self, *, workspace, executor_config):
        session = _Session(workspace, executor_config)
        self.sessions.append(session)
        return session


def _key(root, session_id="session-a", instance_id="codex-main"):
    return ExternalExecutorSessionKey(
        executor_id="codex_cli",
        executor_instance_id=instance_id,
        runtime_config_id="bot-a",
        session_id=session_id,
        workspace_root=root,
        workspace=root,
    )


@pytest.mark.asyncio
async def test_registry_reuses_key_and_closes_sessions(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    runtime = _Runtime()
    registry = ExternalExecutorSessionRegistry(runtime=runtime)

    first = await registry.get_or_create(key=_key(root), executor_config={})
    second = await registry.get_or_create(key=_key(root), executor_config={})

    assert first is second
    assert len(runtime.sessions) == 1
    await registry.aclose()
    assert first.closed is True


@pytest.mark.asyncio
async def test_registry_replaces_session_when_configuration_changes(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    runtime = _Runtime()
    registry = ExternalExecutorSessionRegistry(runtime=runtime)

    first = await registry.get_or_create(
        key=_key(root), executor_config={"sandbox": "workspace-write"}
    )
    second = await registry.get_or_create(
        key=_key(root), executor_config={"sandbox": "read-only"}
    )

    assert first is not second
    assert first.closed is True
    assert second.closed is False
    await registry.aclose()


@pytest.mark.asyncio
async def test_registry_isolates_different_codex_instances(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    runtime = _Runtime()
    registry = ExternalExecutorSessionRegistry(runtime=runtime)

    first = await registry.get_or_create(
        key=_key(root, instance_id="codex-a"), executor_config={}
    )
    second = await registry.get_or_create(
        key=_key(root, instance_id="codex-b"), executor_config={}
    )

    assert first is not second
    await registry.aclose()


@pytest.mark.asyncio
async def test_registry_rejects_custom_executable():
    root = Path.cwd()
    key = _key(root)
    with pytest.raises(ValueError, match="pinned bundled runtime"):
        await ExternalExecutorSessionRegistry().get_or_create(
            key=key,
            executor_config={"executable": "codex --unsafe"},
        )


@pytest.mark.asyncio
async def test_registry_starts_different_keys_without_serializing_creation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    all_started = asyncio.Event()
    release = asyncio.Event()

    class _ConcurrentRuntime(_Runtime):
        async def create_session(self, *, workspace, executor_config):
            session = _Session(workspace, executor_config)
            self.sessions.append(session)
            if len(self.sessions) == 2:
                all_started.set()
            await release.wait()
            return session

    runtime = _ConcurrentRuntime()
    registry = ExternalExecutorSessionRegistry(runtime=runtime)
    first = asyncio.create_task(
        registry.get_or_create(key=_key(root, "a"), executor_config={})
    )
    second = asyncio.create_task(
        registry.get_or_create(key=_key(root, "b"), executor_config={})
    )

    await asyncio.wait_for(all_started.wait(), timeout=1)
    release.set()
    await asyncio.gather(first, second)
    await registry.aclose()


@pytest.mark.asyncio
async def test_registry_serializes_configuration_replacement(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class _VersionedRuntime(_Runtime):
        async def create_session(self, *, workspace, executor_config):
            session = _Session(workspace, executor_config)
            self.sessions.append(session)
            if executor_config.get("sandbox") == "workspace-write":
                first_started.set()
                await release_first.wait()
            return session

    runtime = _VersionedRuntime()
    registry = ExternalExecutorSessionRegistry(runtime=runtime)
    first = asyncio.create_task(
        registry.get_or_create(
            key=_key(root), executor_config={"sandbox": "workspace-write"}
        )
    )
    await first_started.wait()
    second = asyncio.create_task(
        registry.get_or_create(
            key=_key(root), executor_config={"sandbox": "read-only"}
        )
    )
    release_first.set()
    first_session, second_session = await asyncio.gather(first, second)

    assert first_session is not second_session
    assert first_session.closed is True
    assert second_session.closed is False
    await registry.aclose()
