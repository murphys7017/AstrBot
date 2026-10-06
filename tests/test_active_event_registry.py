import asyncio
from dataclasses import dataclass, field

import pytest

from astrbot.core.utils.active_event_registry import ActiveEventRegistry


@dataclass(eq=False)
class Event:
    unified_msg_origin: str = "test:FriendMessage:session"
    extras: dict = field(default_factory=dict)
    stopped: bool = False

    def is_stopped(self):
        return self.stopped

    def stop_event(self):
        self.stopped = True

    def get_extra(self, key):
        return self.extras.get(key)

    def set_extra(self, key, value):
        self.extras[key] = value


@pytest.mark.asyncio
async def test_stopping_session_cancels_detached_background_without_late_output():
    registry = ActiveEventRegistry()
    owner = Event()
    started = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()
    output = []

    async def background():
        try:
            started.set()
            await asyncio.Event().wait()
            output.append("late result")
        finally:
            cleanup_started.set()
            await cleanup_release.wait()

    task = asyncio.create_task(background())
    registry.register(owner)
    registry.register_background_task(owner, task)
    await started.wait()
    registry.unregister(owner)
    assert registry.request_agent_stop_all(owner.unified_msg_origin) == 1
    await cleanup_started.wait()
    registry.request_agent_stop_all(owner.unified_msg_origin)
    cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert output == []
    await asyncio.sleep(0)
    assert registry.request_agent_stop_all(owner.unified_msg_origin) == 0
