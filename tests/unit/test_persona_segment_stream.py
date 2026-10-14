import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot.core.interaction.expression_agent import (
    InteractionExpressionError,
    PersonaExpressionResult,
)
from astrbot.core.interaction.output_controller import InteractionOutputController
from astrbot.core.interaction.turn_state import (
    get_interaction_turn_immediate_persona_state,
    get_interaction_turn_immediate_reply,
    get_interaction_turn_visible_outputs,
)
from astrbot.core.interaction.types import PersonalResponseAction
from astrbot.core.star.star_handler import EventType


class StreamEvent:
    def __init__(self):
        self._extras = {"_turn_id": "turn-1"}
        self.sender_started = asyncio.Event()
        self.sender_finished = asyncio.Event()
        self.delivered_text_parts = []

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value

    def get_platform_name(self):
        return "webchat"

    async def send_interaction_streaming(
        self,
        generator,
        *,
        platform_extras=None,
        use_fallback=False,
    ):
        self.sender_started.set()
        try:
            async for message in generator:
                if message.type == "persona_speech_delta":
                    self.delivered_text_parts.append(message.get_plain_text())
        finally:
            self.sender_finished.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("header_first", [False, True])
async def test_persona_stream_cancellation_drains_tasks(header_first):
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=False
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()

    event = StreamEvent()
    producer_started = asyncio.Event()
    producer_cancelled = asyncio.Event()
    wait_forever = asyncio.Event()

    async def producer(emit_record, _message_id):
        producer_started.set()
        try:
            if header_first:
                await emit_record(
                    {
                        "type": "header",
                        "turn_action": "reply",
                        "persona_result_id": "result-1",
                    }
                )
            await wait_forever.wait()
        finally:
            producer_cancelled.set()

    async def on_header(_record):
        return None

    task = asyncio.create_task(
        controller.emit_persona_segment_stream(
            event,
            producer=producer,
            on_header=on_header,
        )
    )
    await asyncio.wait_for(producer_started.wait(), timeout=1)
    if header_first:
        await asyncio.wait_for(event.sender_started.wait(), timeout=1)

    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert producer_cancelled.is_set()
    assert event.sender_finished.is_set() is header_first


@pytest.mark.asyncio
async def test_silent_persona_stream_does_not_start_webchat_delivery():
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=False
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()

    event = StreamEvent()

    async def producer(emit_record, message_id):
        assert message_id == "stream-1"
        result = PersonaExpressionResult(
            speech="",
            turn_action=PersonalResponseAction.SILENT,
        )
        await emit_record({"type": "header", "turn_action": "silent"})
        await emit_record({"type": "finish", "result": result})
        return result

    outcome = await controller.emit_persona_segment_stream(
        event,
        producer=producer,
        on_header=AsyncMock(return_value=False),
    )

    assert outcome.expression.turn_action is PersonalResponseAction.SILENT
    assert outcome.status == "completed"
    assert outcome.emitted is False
    assert event.sender_started.is_set() is False
    controller._notify_lifecycle.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_stream_preserves_empty_segment_persona_state(monkeypatch):
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=False
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()
    event = StreamEvent()
    finish_events = []

    def registered_handlers(event_type, **_kwargs):
        if event_type is EventType.OnPersonaExpressionStreamFinishedEvent:
            return [object()]
        return []

    async def capture_finish(_event, event_type, **kwargs):
        assert event_type is EventType.OnPersonaExpressionStreamFinishedEvent
        finish_events.append(kwargs)
        return False

    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.star_handlers_registry.get_handlers_by_event_type",
        registered_handlers,
    )
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.call_event_hook",
        capture_finish,
    )

    async def producer(emit_record, _message_id):
        await emit_record(
            {
                "type": "header",
                "turn_action": "reply",
                "persona_result_id": "result-1",
            }
        )
        await emit_record({"type": "segment_start", "segment_index": 0})
        await emit_record(
            {
                "type": "speech_delta",
                "segment_index": 0,
                "delta_index": 0,
                "text": "hello",
            }
        )
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 0,
                "segment": {
                    "speech": "hello",
                    "actions": [],
                    "thought": "",
                    "tendency": {},
                },
            }
        )
        await emit_record({"type": "segment_start", "segment_index": 1})
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 1,
                "segment": {
                    "speech": "",
                    "actions": ["blink"],
                    "thought": "",
                    "tendency": {},
                },
            }
        )
        result = PersonaExpressionResult(speech="hello")
        await emit_record({"type": "finish", "result": result})
        return result

    await controller.emit_persona_segment_stream(
        event,
        producer=producer,
        on_header=AsyncMock(),
    )

    assert get_interaction_turn_immediate_persona_state(event)[0] == ("blink",)
    assert finish_events == [
        {
            "turn_id": "turn-1",
            "persona_result_id": "result-1",
            "message_id": "stream-1",
            "segment_count": 2,
            "status": "completed",
            "failure_reason": None,
            "execution_surface": "personal_expression",
        }
    ]


@pytest.mark.asyncio
async def test_incomplete_stream_reports_accepted_segment_prefix(monkeypatch):
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=False
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()
    event = StreamEvent()
    finish_events = []

    def registered_handlers(event_type, **_kwargs):
        if event_type is EventType.OnPersonaExpressionStreamFinishedEvent:
            return [object()]
        return []

    async def capture_finish(_event, event_type, **kwargs):
        assert event_type is EventType.OnPersonaExpressionStreamFinishedEvent
        finish_events.append(kwargs)
        return False

    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.star_handlers_registry.get_handlers_by_event_type",
        registered_handlers,
    )
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.call_event_hook",
        capture_finish,
    )

    async def producer(emit_record, _message_id):
        await emit_record(
            {
                "type": "header",
                "turn_action": "reply",
                "persona_result_id": "result-1",
            }
        )
        await emit_record({"type": "segment_start", "segment_index": 0})
        await emit_record(
            {
                "type": "speech_delta",
                "segment_index": 0,
                "delta_index": 0,
                "text": "accepted",
            }
        )
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 0,
                "segment": {
                    "speech": "accepted",
                    "actions": [],
                    "thought": "",
                    "tendency": {},
                },
            }
        )
        raise InteractionExpressionError("provider_failed")

    outcome = await controller.emit_persona_segment_stream(
        event,
        producer=producer,
        on_header=AsyncMock(return_value=True),
    )

    assert outcome.status == "incomplete"
    assert outcome.failure_reason == "provider_failed"
    assert event.delivered_text_parts == ["accepted"]
    assert finish_events[0]["status"] == "incomplete"
    assert finish_events[0]["segment_count"] == 1
    assert finish_events[0]["failure_reason"] == "provider_failed"


@pytest.mark.asyncio
async def test_persona_stream_cancellation_cancels_stalled_tts(monkeypatch):
    controller = InteractionOutputController()
    controller._ensure_persona_segment_stream_compatible = lambda _event: None
    controller._resolve_outbound_options = lambda _event: SimpleNamespace(
        tts_enabled=True,
        tts_trigger_probability=1.0,
        tts_use_file_service=False,
        callback_api_base=None,
    )
    controller._next_output_segment_id = lambda _event, _kind: "stream-1"
    controller.build_platform_output_extras = lambda *_args, **_kwargs: {}
    controller._notify_lifecycle = AsyncMock()
    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.SessionServiceManager.should_process_tts_request",
        AsyncMock(return_value=True),
    )

    event = StreamEvent()
    tts_started = asyncio.Event()
    tts_cancelled = asyncio.Event()
    producer_finished = asyncio.Event()
    wait_forever = asyncio.Event()

    async def stalled_synthesis(*_args, **_kwargs):
        tts_started.set()
        try:
            await wait_forever.wait()
        finally:
            tts_cancelled.set()

    monkeypatch.setattr(
        "astrbot.core.interaction.output_controller.synthesize_text",
        stalled_synthesis,
    )

    async def producer(emit_record, _message_id):
        await emit_record({"type": "header", "turn_action": "reply"})
        for segment_index, segment_text in enumerate(("hello", " world")):
            segment = {
                "speech": segment_text,
                "actions": [],
                "thought": "",
                "tendency": {},
            }
            await emit_record(
                {"type": "segment_start", "segment_index": segment_index}
            )
            await emit_record(
                {
                    "type": "speech_delta",
                    "segment_index": segment_index,
                    "delta_index": 0,
                    "text": segment_text,
                }
            )
            await emit_record(
                {
                    "type": "segment_end",
                    "segment_index": segment_index,
                    "segment": segment,
                }
            )
        await emit_record({"type": "segment_start", "segment_index": 2})
        await emit_record(
            {
                "type": "segment_end",
                "segment_index": 2,
                "segment": {
                    "speech": "",
                    "actions": ["blink"],
                    "thought": "",
                    "tendency": {},
                },
            }
        )
        result = PersonaExpressionResult(speech="hello world")
        await emit_record({"type": "finish", "result": result})
        producer_finished.set()
        return result

    task = asyncio.create_task(
        controller.emit_persona_segment_stream(
            event,
            producer=producer,
            on_header=AsyncMock(),
        )
    )
    await asyncio.wait_for(tts_started.wait(), timeout=1)
    await asyncio.wait_for(producer_finished.wait(), timeout=1)
    task.cancel()
    result = await asyncio.wait_for(
        asyncio.gather(task, return_exceptions=True),
        timeout=1,
    )

    assert isinstance(result[0], asyncio.CancelledError)
    assert tts_cancelled.is_set()
    assert event.sender_finished.is_set()
    assert event.delivered_text_parts == ["hello"]
    assert event.get_extra("_interaction_persona_segment_stream_status") == (
        "cancelled"
    )
    assert get_interaction_turn_immediate_reply(event) == "hello"
    assert get_interaction_turn_immediate_persona_state(event)[0] == ()
    visible_outputs = get_interaction_turn_visible_outputs(event)
    assert visible_outputs[-1]["text"] == "hello"
