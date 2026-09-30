import pytest

from astrbot.core.pipeline.waking_check import stage as waking_stage
from astrbot.core.star.star import star_map
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)


class _RaisingFilter:
    def filter(self, _event, _config):
        raise RuntimeError("filter failed")


class _Event:
    def __init__(self) -> None:
        self.plugins_name = None
        self._extras = {}
        self.sent = []
        self.stopped = False

    def get_extra(self, key=None, default=None):
        if key is None:
            return self._extras
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value

    async def send(self, message):
        self.sent.append(message)

    def stop_event(self):
        self.stopped = True

    def get_sender_id(self):
        return "sender-1"


@pytest.mark.asyncio
async def test_handler_filter_error_survives_plugin_unload_race(monkeypatch):
    handler_module_path = "tests.race_unloaded_plugin.handlers"
    handler = StarHandlerMetadata(
        event_type=EventType.AdapterMessageEvent,
        handler_full_name="race_handler",
        handler_name="race_handler",
        handler_module_path=handler_module_path,
        handler=lambda _event: None,
        event_filters=[_RaisingFilter()],
    )
    event = _Event()

    async def build_snapshot(**_kwargs):
        return None

    monkeypatch.delitem(star_map, handler_module_path, raising=False)
    monkeypatch.setattr(
        waking_stage,
        "build_plugin_admission_snapshot",
        build_snapshot,
    )
    monkeypatch.setattr(
        waking_stage,
        "capability_allowed",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        star_handlers_registry,
        "get_handlers_by_event_type",
        lambda *_args, **_kwargs: [handler],
    )

    await waking_stage._discover_activated_handlers(
        event,
        config={"plugin_set": ["*"]},
        disable_builtin_commands=False,
        no_permission_reply=True,
    )

    assert event.stopped
    assert len(event.sent) == 1
    assert (
        event.sent[0].get_plain_text()
        == f"插件 {handler_module_path}: filter failed"
    )
