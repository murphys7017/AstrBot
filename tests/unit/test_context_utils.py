from unittest.mock import MagicMock

import pytest

from astrbot.core.message.message_event_result import MessageEventResult
from astrbot.core.pipeline import context_utils
from astrbot.core.pipeline.context_utils import call_event_hook, call_handler
from astrbot.core.star.star_handler import EventType, StarHandlerMetadata


@pytest.mark.asyncio
async def test_call_handler_supports_legacy_sync_generator():
    event = MagicMock()
    result = MessageEventResult().message("ok")

    def handler(_event):
        yield result

    yielded = [item async for item in call_handler(event, handler)]

    assert yielded == [None]
    event.set_result.assert_called_once_with(result)


@pytest.mark.asyncio
async def test_call_event_hook_preserves_stop_check_when_handler_assertion_fails(
    monkeypatch,
):
    event = MagicMock()
    event.is_stopped.return_value = True
    handler = StarHandlerMetadata(
        event_type=EventType.OnLLMRequestEvent,
        handler_full_name="invalid_hook",
        handler_name="invalid_hook",
        handler_module_path="astrbot.core.invalid_hook",
        handler=lambda _event: None,
        event_filters=[],
    )
    monkeypatch.setattr(
        context_utils.star_handlers_registry,
        "get_handlers_by_event_type",
        lambda *_args, **_kwargs: [handler],
    )

    assert await call_event_hook(event, EventType.OnLLMRequestEvent) is True
