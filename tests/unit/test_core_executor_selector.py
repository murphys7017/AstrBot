import asyncio
from types import SimpleNamespace

import pytest

from astrbot.core.executors.selector import (
    CoreExecutorDrainTimeout,
    CoreExecutorSelector,
    CoreExecutorSwitchInProgress,
    build_core_executor_selector,
)


@pytest.mark.asyncio
async def test_switch_stops_admission_and_waits_for_old_run_release():
    selector = CoreExecutorSelector("native")
    stop_requested = asyncio.Event()
    lease = await selector.acquire("native")
    lease.bind_stop(stop_requested.set)

    switch = asyncio.create_task(
        selector.switch_to("codex_cli", timeout_seconds=1)
    )
    await asyncio.wait_for(stop_requested.wait(), timeout=1)

    assert selector.active_executor_id == "native"
    assert selector.switching is True
    with pytest.raises(CoreExecutorSwitchInProgress):
        await selector.acquire("codex_cli")

    await lease.aclose()
    await switch

    assert selector.active_executor_id == "codex_cli"
    assert selector.active_run_count == 0


@pytest.mark.asyncio
async def test_switch_timeout_keeps_old_executor_and_reopens_admission():
    selector = CoreExecutorSelector("native")
    lease = await selector.acquire("native")

    with pytest.raises(CoreExecutorDrainTimeout):
        await selector.switch_to("codex_cli", timeout_seconds=0.01)

    assert selector.default_executor_id == "native"
    assert selector.switching is False

    await lease.aclose()
    replacement = await selector.acquire("codex_cli")
    await replacement.aclose()


@pytest.mark.asyncio
async def test_switch_waits_for_detached_body_cleanup_task():
    selector = CoreExecutorSelector("native")
    stop_requested = asyncio.Event()
    lease = await selector.acquire("native", stop_preparation=stop_requested.set)
    finish_cleanup = asyncio.Event()

    async def cleanup():
        await finish_cleanup.wait()

    cleanup_task = asyncio.create_task(cleanup())
    lease.bind_cleanup_task(cleanup_task)
    switch = asyncio.create_task(
        selector.switch_to("codex_cli", timeout_seconds=1)
    )
    await asyncio.wait_for(stop_requested.wait(), timeout=1)
    await lease.aclose()

    assert selector.active_executor_id == "native"
    assert selector.active_run_count == 1

    finish_cleanup.set()
    await switch
    assert selector.active_executor_id == "codex_cli"
    assert selector.active_run_count == 0


def test_selector_uses_system_default_without_collapsing_profile_choices():
    class _Config(dict):
        save_count = 0

        def save_config(self):
            self.save_count += 1

    default = _Config(core_executor={"active_executor_id": ""})
    profile = {"core_execution": {"executor_id": "codex_cli"}}
    manager = SimpleNamespace(
        default_conf=default,
        confs={"default": default, "bot-codex": profile},
    )

    selector = build_core_executor_selector(manager)

    assert selector.default_executor_id == "native"
    assert default["core_executor"]["active_executor_id"] == "native"
    assert default.save_count == 1
    assert profile["core_execution"]["executor_id"] == "codex_cli"


@pytest.mark.asyncio
async def test_selector_admits_different_profile_executors_concurrently():
    selector = CoreExecutorSelector("native")
    native_lease = await selector.acquire("native")
    codex_lease = await selector.acquire("codex_cli")

    assert selector.active_run_count == 2

    await native_lease.aclose()
    await codex_lease.aclose()
    assert selector.active_run_count == 0


@pytest.mark.parametrize("explicit", ["native", "codex_cli"])
def test_selector_preserves_explicit_system_default_for_mixed_profiles(explicit):
    default = {
        "core_executor": {"active_executor_id": explicit},
        "core_execution": {"executor_id": "native"},
    }
    manager = SimpleNamespace(
        default_conf=default,
        confs={
            "default": default,
            "bot-b": {"core_execution": {"executor_id": "codex_cli"}},
        },
    )

    selector = build_core_executor_selector(manager)

    assert selector.default_executor_id == explicit
    assert default["core_executor"]["active_executor_id"] == explicit


@pytest.mark.asyncio
async def test_selector_persists_global_runtime_switch():
    class _Config(dict):
        def save_config(self):
            self.save_count = getattr(self, "save_count", 0) + 1

    default = _Config(
        core_executor={"active_executor_id": "native"},
        core_execution={"executor_id": "native"},
    )
    selector = build_core_executor_selector(
        SimpleNamespace(default_conf=default, confs={"default": default})
    )

    await selector.switch_to("codex_cli")

    assert selector.active_executor_id == "codex_cli"
    assert default["core_executor"]["active_executor_id"] == "codex_cli"
    assert default.save_count == 1
