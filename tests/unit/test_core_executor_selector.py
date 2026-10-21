import asyncio
from types import SimpleNamespace

import pytest

from astrbot.core.executors.selector import (
    CoreExecutorDrainTimeout,
    CoreExecutorSelector,
    CoreExecutorSelectorError,
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

    assert selector.active_executor_id == "native"
    assert selector.switching is False
    with pytest.raises(CoreExecutorSelectorError, match="not active"):
        await selector.acquire("codex_cli")

    await lease.aclose()
    replacement = await selector.acquire("native")
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


def test_selector_migrates_matching_legacy_profile_choices():
    class _Config(dict):
        save_count = 0

        def save_config(self):
            self.save_count += 1

    default = _Config(
        core_executor={"active_executor_id": ""},
        core_execution={"executor_id": "codex_cli"},
    )
    manager = SimpleNamespace(
        default_conf=default,
        confs={
            "default": default,
            "bot-b": {"core_execution": {"executor_id": "codex_cli"}},
        },
    )

    selector = build_core_executor_selector(manager)

    assert selector.active_executor_id == "codex_cli"
    assert default["core_executor"]["active_executor_id"] == "codex_cli"
    assert default.save_count == 1


def test_selector_rejects_conflicting_legacy_profile_choices():
    default = {
        "core_executor": {"active_executor_id": ""},
        "core_execution": {"executor_id": "native"},
    }
    manager = SimpleNamespace(
        default_conf=default,
        confs={
            "default": default,
            "bot-b": {"core_execution": {"executor_id": "codex_cli"}},
        },
    )

    with pytest.raises(ValueError, match="legacy profiles conflict"):
        build_core_executor_selector(manager)


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
